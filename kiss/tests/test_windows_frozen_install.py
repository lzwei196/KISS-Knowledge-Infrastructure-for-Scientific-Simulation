"""Installer launches that the windowed Windows Desktop depends on.

Real cmd.exe, real directory junctions and a real child process holding a
directory open: the bugs these guard against live in Windows' own parsing and
file locking, which a mocked subprocess cannot show.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from kiss_cli import api, execution, install

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows cmd.exe, junctions and file locking")


def _echo_script(directory: Path) -> Path:
    script = directory / "argv echo.py"
    script.write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
    return script


def test_quoted_build_arguments_survive_the_supervised_shell(tmp_path):
    # Manifest build commands such as VIC's `make ... CC="gcc -fcommon"` and a
    # quoted executable path must reach the tool exactly as with shell=True.
    script = _echo_script(tmp_path)
    command = (f'"{sys.executable}" "{script}" "hello world" '
               'CC="gcc -fcommon" F90FLAGS="-w -O3"')
    with install.cancellation_context(stop=lambda: False):
        rc, out = install._run(command, cwd=tmp_path, timeout=60)
    assert rc == 0, out
    assert json.loads(out.strip().splitlines()[-1]) == [
        "hello world", "CC=gcc -fcommon", "F90FLAGS=-w -O3"]


@windows_only
def test_supervised_shell_command_line_is_the_one_popen_shell_builds(tmp_path):
    command = 'mingw32-make CC="gcc -fcommon"'
    with mock.patch.object(execution, "run_process",
                           return_value=execution.ProcessRun("succeeded", 0, "", "")) as run, \
            install.cancellation_context(stop=lambda: False):
        install._run(command, cwd=tmp_path)
    # CPython's Windows _execute_child: '{} /c "{}"'.format(comspec, args)
    assert run.call_args.args[0] == '{} /c "{}"'.format(
        os.environ.get("COMSPEC", "cmd.exe"), command)


def _install_tree_case(root: Path):
    prefix = root / "binaries dir" / "Demo 1"
    binary = prefix / "build" / "bin" / "demo.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"MZ")
    preflight = root / "preflight_check.py"
    preflight.write_text(
        "def check_file(path, label, executable=False): pass\n"
        f'check_file("{root.as_posix()}/Declared Tree/build/bin/demo.exe", "Demo", executable=True)\n',
        encoding="utf-8")
    return prefix, binary, SimpleNamespace(preflight=preflight, root=root / "ki")


def _no_symlinks(self, *args, **kwargs):
    # Developer Mode off: an ordinary user may not create symlinks.
    raise OSError(1314, "A required privilege is not held by the client")


@windows_only
def test_junction_fallback_links_install_tree_through_spaces(tmp_path, monkeypatch):
    root = tmp_path / "work root %PATH%"
    prefix, binary, ki = _install_tree_case(root)
    monkeypatch.setattr(Path, "symlink_to", _no_symlinks)

    notes = install.place_where_the_ki_expects(ki, binary, SimpleNamespace(root=root), prefix)

    link = root / "Declared Tree"
    assert notes and "linked install tree" in notes[0], notes
    assert not link.is_symlink()                    # a junction, no privilege needed
    assert link.resolve() == prefix.resolve()
    assert (link / "build" / "bin" / "demo.exe").read_bytes() == b"MZ"
    os.rmdir(link)                                   # removes the junction only
    assert binary.is_file()


@windows_only
def test_failed_junction_leaves_no_plain_directory_behind(tmp_path, monkeypatch):
    import _winapi

    def half_made(target, link):
        os.mkdir(link)                                # CreateJunction's first step
        raise OSError(22, "The filename, directory name, or volume label syntax is incorrect")

    root = tmp_path / "work root"
    tools = root / "ki pkg" / "tools"
    tools.mkdir(parents=True)
    preflight = root / "preflight_check.py"
    preflight.write_text(f'check_dir("{root.as_posix()}/Declared KI/tools")\n', encoding="utf-8")
    monkeypatch.setattr(Path, "symlink_to", _no_symlinks)
    monkeypatch.setattr(_winapi, "CreateJunction", half_made)

    notes = install.place_where_the_ki_expects(
        SimpleNamespace(preflight=preflight, root=root / "ki pkg"), None,
        SimpleNamespace(root=root))

    assert notes and "could not place tools/" in notes[0], notes
    assert not os.path.lexists(root / "Declared KI" / "tools")


def test_scratch_directory_is_removed_after_normal_use(tmp_path):
    with install.scratch_directory(".download-", tmp_path) as path:
        (Path(path) / "request.json").write_text("{}", encoding="utf-8")
    assert not list(tmp_path.glob(".download-*"))


def _hold_cwd(directory) -> subprocess.Popen:
    """A surviving descendant whose current directory is inside ``directory``."""
    holder = subprocess.Popen(
        [sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(4)"],
        cwd=str(directory), stdout=subprocess.PIPE, text=True)
    # Windows opens the child's cwd while it initialises, after Popen returns.
    assert holder.stdout.readline().strip() == "ready"
    return holder


def _release(holders) -> None:
    for holder in holders:
        holder.kill()
        holder.wait()
        holder.stdout.close()


@windows_only
def test_locked_scratch_directory_cleanup_cannot_replace_the_result(tmp_path):
    holders = []
    try:
        with install.scratch_directory(".download-", tmp_path) as path:
            holders.append(_hold_cwd(path))
            result = "worker result"
        # TemporaryDirectory's cleanup raised here: on Python 3.11.0 it ends in
        # RecursionError even with ignore_cleanup_errors=True (gh-79325).
        assert result == "worker result"
    finally:
        _release(holders)


@windows_only
def test_managed_download_result_survives_a_locked_worker_directory(tmp_path):
    from kiss_cli.manifest import Acquire, Manifest
    project = tmp_path / "project"
    project.mkdir()
    prefix = project / "binary"
    holders = []

    def worker(command, *, cwd, **kwargs):
        # The worker wrote its result; a descendant still sits in its directory.
        request = Path(command[-1])
        (request.parent / "result.json").write_text(json.dumps({
            "step": asdict(install.Step("acquire[download]", True, "from fixture")),
            "binary": None}), encoding="utf-8")
        holders.append(_hold_cwd(request.parent))
        return execution.ProcessRun("succeeded", 0, "", "")

    manifest = Manifest(model="Demo", acquire=Acquire(strategy="download", url="https://example.invalid/m.zip"))
    try:
        with mock.patch.object(execution, "run_process", side_effect=worker), \
                install.cancellation_context(project):
            step, _ = install.acquire(manifest, prefix, sys.executable)
        assert step.ok, step.detail
        assert step.detail == "from fixture"
    finally:
        _release(holders)


@windows_only
def test_startup_probe_result_is_not_relabelled_by_directory_cleanup(tmp_path):
    root = tmp_path.resolve()
    binary = root / "binaries" / "model.exe"
    binary.parent.mkdir()
    binary.write_bytes(b"MZfixture")
    cfg = SimpleNamespace(root=root, python=sys.executable, roles={"binaries": binary.parent})
    ki = SimpleNamespace(root=root / "ki", name="fixture")
    holders = []

    def probe(argv, *, cwd, **kwargs):
        holders.append(_hold_cwd(cwd))
        return execution.ProcessRun("succeeded", 0, "usage: model [options]", "")

    try:
        with mock.patch.object(execution, "run_process", side_effect=probe):
            result = api.execute_tool(
                "run_setup_command", {"argv": [str(binary), "--help"], "timeout_seconds": 60},
                ki, cfg, setup_mode=True, setup_context={"installation_only": True})
    finally:
        _release(holders)
    assert holders, "the startup probe was not launched"
    assert result.startswith("exit_code=0"), result
    assert "usage: model [options]" in result
