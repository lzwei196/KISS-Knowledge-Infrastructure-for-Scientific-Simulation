"""Known-location discovery is finite, cancellable, and never verification."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from kiss_cli import execution, install, processes, setup_discovery as discovery


def request(**changes):
    value = {"schema_version": 1, "request_id": "a" * 32, "model": "Demo",
             "hints": ["Demo"], "existing_paths": [], "limit": 24,
             "timeout": 8.0, "input_limited": False}
    return {**value, **changes}


@pytest.fixture
def local_scope(monkeypatch, tmp_path):
    area = tmp_path / "known-location"
    area.mkdir()
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(discovery, "_conventional_roots", lambda: [area])
    return area


def test_scan_visits_only_direct_entries_and_exact_selected_paths(local_scope):
    root = local_scope
    chosen = root.parent / "chosen-custom-name"
    chosen.mkdir()
    direct = root / "Demo-install"
    direct.mkdir()
    hidden = root / "unrelated" / "Demo-deep"
    hidden.mkdir(parents=True)
    result = discovery._scan(request(existing_paths=[str(chosen)]))
    assert result["state"] == "complete" and result["complete"]
    assert set(result["candidates"]) == {str(direct.resolve()), str(chosen.resolve())}
    assert str(hidden) not in result["candidates"]
    assert result["scope"]["recursive"] is False
    assert result["scope"]["indexed"] is False
    assert "machine-wide absence" in result["reason"]


def test_nonmatching_entries_consume_the_shared_budget(local_scope):
    for index in range(550):
        (local_scope / f"unrelated-{index}").touch()
    result = discovery._scan(request())
    assert result["state"] == "limited" and not result["complete"]
    assert result["stats"]["entries_checked"] == 512
    assert not result["candidates"]
    assert "entry limit" in result["reason"]


def test_result_limit_is_incomplete_and_does_not_scan_rest(local_scope):
    for index in range(6):
        (local_scope / f"Demo-{index}").mkdir()
    result = discovery._scan(request(limit=2))
    assert len(result["candidates"]) == 2
    assert result["state"] == "limited" and not result["complete"]
    assert result["stats"]["entries_checked"] < 6
    assert "result limit" in result["reason"]


def test_refuses_broad_selected_roots_and_relative_paths(local_scope):
    result = discovery._scan(request(existing_paths=[
        str(Path.home()), str(Path(local_scope.anchor)), "relative-install"]))
    assert result["state"] == "limited" and not result["candidates"]
    assert "disk/home root" in result["reason"] and "not absolute" in result["reason"]


def test_directory_link_is_not_followed_or_promoted_to_candidate(local_scope):
    outside = local_scope.parent / "outside"
    outside.mkdir()
    link = local_scope / "Demo-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink not available: {error}")
    result = discovery._scan(request(existing_paths=[str(link)]))
    assert not result["candidates"]


def test_path_lookup_is_exact_and_keeps_executable_launcher_spelling(local_scope, monkeypatch):
    tools = local_scope.parent / "tools"
    tools.mkdir()
    target = tools / ("demo.exe" if os.name == "nt" else "demo")
    target.write_bytes(b"fixture; never executed")
    target.chmod(0o700)
    (tools / "demo-extra").touch()
    monkeypatch.setenv("PATH", str(tools))
    result = discovery._scan(request(hints=["demo"]))
    assert str(target) in result["candidates"]
    assert str(tools / "demo-extra") not in result["candidates"]


def test_conventional_root_also_on_path_still_gets_direct_listing(local_scope, monkeypatch):
    candidate = local_scope / "Demo installation"
    candidate.mkdir()
    monkeypatch.setenv("PATH", str(local_scope))
    result = discovery._scan(request())
    assert str(candidate.resolve()) in result["candidates"]
    assert result["stats"]["roots_checked"] == 1
    assert result["state"] == "complete" and result["complete"]


def test_unreadable_root_is_incomplete(local_scope, monkeypatch):
    original = discovery.os.scandir
    def blocked(path):
        if Path(path) == local_scope:
            raise PermissionError("fixture unreadable directory")
        return original(path)
    monkeypatch.setattr(discovery.os, "scandir", blocked)
    result = discovery._scan(request())
    assert result["state"] == "limited" and not result["complete"]
    assert "could not be inspected" in result["reason"]


def test_root_limit_and_hint_limit_are_reported(local_scope, monkeypatch):
    roots = [local_scope / f"path-{index}" for index in range(70)]
    for root in roots:
        root.mkdir()
    monkeypatch.setenv("PATH", os.pathsep.join(map(str, roots)))
    monkeypatch.setenv("PATHEXT", "")
    result = discovery._scan(request())
    assert result["stats"]["roots_checked"] == 64
    assert result["state"] == "limited" and "root limit" in result["reason"]
    names, limited = discovery._hints("Demo", (f"hint-{index}" for index in range(50)))
    assert len(names) == 12 and limited


def test_real_worker_finds_exact_selected_path_and_cleans_temporary_files(tmp_path, monkeypatch):
    root = tmp_path / "setup"
    root.mkdir()
    candidate = tmp_path / "中国-安装"
    candidate.mkdir()
    monkeypatch.setenv("PATH", "")
    result = discovery.discover("NoSuchFixtureModel", root=root, existing_paths=[str(candidate)])
    assert result["state"] in {"complete", "limited"}, result
    assert str(candidate.resolve()) in result["candidates"]
    assert result["stats"]["entries_checked"] <= 512
    assert len(discovery._encode(result)) <= 65536
    assert not list(root.glob(".geoforge-discovery-*"))


def test_invalid_or_stale_worker_result_cannot_be_accepted(tmp_path, monkeypatch):
    def stale(command, **kwargs):
        result = discovery._report(request())
        Path(command[-1]).write_bytes(discovery._encode(result))
        return execution.ProcessRun("succeeded", 0)
    monkeypatch.setattr(execution, "run_process", stale)
    result = discovery.discover("Demo", root=tmp_path)
    assert result["state"] == "failed" and not result["complete"]
    assert not result["candidates"]


@pytest.mark.parametrize("damage,value", [("stats", None), ("scope", None), ("limits", None),
                                         ("complete", None), ("reason", None), ("state", [])])
def test_malformed_worker_report_is_structured_failure(tmp_path, monkeypatch, damage, value):
    def malformed(command, **kwargs):
        current = discovery._document(Path(command[-2]))
        report = discovery._report(current)
        report[damage] = value
        Path(command[-1]).write_bytes(discovery._encode(report))
        return execution.ProcessRun("succeeded", 0)
    monkeypatch.setattr(execution, "run_process", malformed)
    result = discovery.discover("Demo", root=tmp_path)
    assert result["state"] == "failed" and not result["complete"]
    assert result["stats"]["entries_checked"] == 0


def test_empty_hints_do_not_become_search_names():
    names, limited = discovery._hints("Demo", [None, "", "Demo", "../safe-name", "*"])
    assert names == ["Demo", "safe-name"] and not limited


def test_worker_rejects_path_traversal_hint_and_is_silent(tmp_path, capsys):
    source, target = tmp_path / "input.json", tmp_path / "output.json"
    source.write_bytes(discovery._encode(request(hints=["../secret"])))
    assert discovery.worker_main(source, target) == 2
    assert not target.exists()
    assert capsys.readouterr() == ("", "")


def test_large_request_does_not_launch_and_has_bounded_report(tmp_path, monkeypatch):
    monkeypatch.setattr(execution, "run_process", lambda *args, **kwargs: pytest.fail("must not launch"))
    result = discovery.discover("Demo", root=tmp_path, existing_paths=["x" * 70000])
    assert result["state"] == "limited" and not result["complete"]
    assert len(discovery._encode(result)) <= 65536


def test_frozen_command_uses_host_app_internal_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    source, result = tmp_path / "input.json", tmp_path / "output.json"
    assert discovery._command(source, result) == [
        sys.executable, "_setup-discovery-worker", str(source), str(result)]


def test_source_worker_cannot_import_an_agent_workspace_shadow(tmp_path, monkeypatch):
    root = tmp_path / "setup"
    root.mkdir()
    package = root / "kiss_cli"
    package.mkdir()
    marker = root / "shadow-executed"
    (package / "__init__.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n"
        "raise RuntimeError('workspace code must never execute')\n", encoding="utf-8")
    (root / "json.py").write_text("raise RuntimeError('shadow stdlib')\n", encoding="utf-8")
    candidate = tmp_path / "selected-install"
    candidate.mkdir()
    monkeypatch.setenv("PATH", "")
    result = discovery.discover("Demo", root=root, existing_paths=[str(candidate)])
    assert str(candidate.resolve()) in result["candidates"], result
    assert not marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows environment keys and conventional roots")
def test_real_worker_receives_windows_programfiles_regardless_of_key_case(tmp_path, monkeypatch):
    root = tmp_path / "setup"
    root.mkdir()
    programs = tmp_path / "Program Files"
    programs.mkdir()
    candidate = programs / "Demo installation"
    candidate.mkdir()
    monkeypatch.setenv("PROGRAMFILES", str(programs))
    monkeypatch.setenv("PATH", "")
    result = discovery.discover("Demo", root=root)
    assert str(candidate.resolve()) in result["candidates"], result


def test_cancelled_or_old_generation_never_starts_discovery(tmp_path, monkeypatch):
    first = execution.begin_turn(tmp_path)
    execution.begin_turn(tmp_path)
    monkeypatch.setattr(execution, "run_process", lambda *args, **kwargs: pytest.fail("must not launch"))
    with pytest.raises(install.InstallStopped):
        discovery.discover("Demo", root=tmp_path, turn_id=first)


def _pid_running(pid):
    if os.name == "nt":
        created = processes._windows_creation_time(pid)
        return created is not None and processes._windows_running(pid, created)
    try:
        info = Path(f"/proc/{pid}/stat")
        if info.exists() and info.read_text().split(")", 1)[1].split()[0] == "Z":
            return False
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


@pytest.mark.parametrize("control", ["deadline", "callback", "marker"])
def test_stuck_filesystem_worker_and_child_are_stopped_without_harming_sentinel(
        tmp_path, monkeypatch, control):
    root = tmp_path / "setup"
    root.mkdir()
    generation = execution.begin_turn(root)
    marker = root / "fixture-processes.json"
    stopper, observed = threading.Event(), []
    identities = []
    # A test harness replaces one actual directory read inside the real child.
    # Production has no sleep/test switch and the real supervisor is unchanged.
    harness = (
        "import json,os,subprocess,sys,time\nfrom pathlib import Path\n"
        "from kiss_cli import setup_discovery as d\n"
        f"base=Path({str(root)!r})\n"
        "os.environ['PATH']=''\nd._conventional_roots=lambda:[base]\n"
        "def blocked(path):\n"
        " child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(45)'],"
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
        "creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))\n"
        f" Path({str(marker)!r}).write_text(json.dumps([os.getpid(),child.pid]))\n"
        " time.sleep(45)\n"
        "d.os.scandir=blocked\n"
        "raise SystemExit(d.worker_main(*sys.argv[1:]))\n"
    )
    monkeypatch.setattr(discovery, "_command", lambda source, target:
        [sys.executable, "-S", "-c", harness, str(source), str(target)])
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(45)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def observe():
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                observed.extend(json.loads(marker.read_text()))
                if os.name == "nt":
                    identities.extend((pid, processes._windows_creation_time(pid)) for pid in observed)
                break
            except (OSError, ValueError):
                time.sleep(0.02)
        if control == "callback":
            stopper.set()
        elif control == "marker":
            execution.request_stop(root)

    observer = threading.Thread(target=observe, daemon=True)
    started = time.monotonic()
    try:
        observer.start()
        if control == "deadline":
            result = discovery.discover("Demo", root=root, timeout=2, turn_id=generation)
            assert result["state"] == "limited" and not result["complete"]
            assert "time limit" in result["reason"]
        else:
            with pytest.raises(install.InstallStopped):
                discovery.discover("Demo", root=root, timeout=8, stop=stopper.is_set,
                                   turn_id=generation)
        observer.join(2)
        assert len(observed) == 2, "the worker and its child must actually start"
        assert time.monotonic() - started < 12
        deadline = time.monotonic() + 3
        while any(_pid_running(pid) for pid in observed) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not any(_pid_running(pid) for pid in observed)
        assert sentinel.poll() is None
        assert not list(root.glob(".geoforge-discovery-*"))
    finally:
        stopper.set()
        observer.join(2)
        if sentinel.poll() is None:
            sentinel.terminate()
        sentinel.wait(5)
        if os.name == "nt":
            processes.terminate_snapshot([(pid, stamp) for pid, stamp in identities if stamp])
        else:
            import signal
            for pid in observed:
                if _pid_running(pid):
                    os.kill(pid, signal.SIGKILL)
