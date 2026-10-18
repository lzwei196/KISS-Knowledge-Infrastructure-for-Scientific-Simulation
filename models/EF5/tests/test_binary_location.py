"""The EF5 binary path is the same in run_ef5.py, preflight_check.py and knowledge_infrastructure.yaml."""
import importlib.util
import os
import sys
from pathlib import Path

import yaml

KI = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_one_binary_path_everywhere():
    run_ef5 = _load("run_ef5_binloc", KI / "tools" / "run_ef5.py")
    preflight = _load("preflight_binloc", KI / "preflight_check.py")
    ki_yaml = yaml.safe_load((KI / "knowledge_infrastructure.yaml").read_text())
    path = ki_yaml["package"]["binary"]["path"]
    assert path == run_ef5.MANAGED_BINARY == str(preflight.EF5_BINARY)
    assert path.endswith("/EF5/bin/ef5")


def test_run_ef5_binary_defaults_to_first_existing_candidate(tmp_path, monkeypatch):
    """No --binary: main() passes the first existing candidate (managed install first) on to the run."""
    run_ef5 = _load("run_ef5_binloc2", KI / "tools" / "run_ef5.py")
    managed = tmp_path / "EF5" / "bin" / "ef5"
    source = tmp_path / "EF5" / "source" / "repo" / "bin" / "ef5"
    cands = (str(managed), str(source))
    monkeypatch.setattr(run_ef5, "BINARY_CANDIDATES", cands)
    monkeypatch.setattr(run_ef5.find_binary, "__defaults__", (cands,))
    seen = {}

    def stop(control, binary):
        seen["binary"] = binary
        raise SystemExit(3)

    monkeypatch.setattr(run_ef5, "preflight_check", stop)
    monkeypatch.setattr(sys, "argv", ["run_ef5.py", "--control", "missing_control.txt"])
    for present, expect in ((source, source), (managed, managed)):
        _fake_bin(present)
        seen.clear()
        try:
            run_ef5.main()
        except SystemExit as exc:
            assert exc.code == 3
        assert seen["binary"] == os.path.abspath(str(expect))


def _fake_bin(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_search_order_managed_then_source_build(tmp_path):
    run_ef5 = _load("run_ef5_binloc3", KI / "tools" / "run_ef5.py")
    preflight = _load("preflight_binloc3", KI / "preflight_check.py")
    # Both lists name the same two paths in the same order: managed bin/ef5, then source/repo/bin/ef5.
    assert run_ef5.BINARY_CANDIDATES == (run_ef5.MANAGED_BINARY, run_ef5.SOURCE_BUILD_BINARY)
    assert tuple(str(c) for c in preflight.EF5_BINARY_CANDIDATES) == run_ef5.BINARY_CANDIDATES
    assert run_ef5.SOURCE_BUILD_BINARY.endswith("/EF5/source/repo/bin/ef5")

    managed = tmp_path / "EF5" / "bin" / "ef5"
    source = tmp_path / "EF5" / "source" / "repo" / "bin" / "ef5"
    cands = (str(managed), str(source))
    assert run_ef5.find_binary(cands) is None
    _fake_bin(source)
    assert run_ef5.find_binary(cands) == str(source)
    _fake_bin(managed)
    assert run_ef5.find_binary(cands) == str(managed)


def test_preflight_pick_binary_order(tmp_path, monkeypatch):
    preflight = _load("preflight_binloc4", KI / "preflight_check.py")
    managed = tmp_path / "EF5" / "bin" / "ef5"
    source = tmp_path / "EF5" / "source" / "repo" / "bin" / "ef5"
    monkeypatch.setattr(preflight, "EF5_BINARY_CANDIDATES", (managed, source))
    assert preflight.pick_binary() is None
    _fake_bin(source)
    assert preflight.pick_binary() == source
    _fake_bin(managed)
    assert preflight.pick_binary() == managed


def test_preflight_literal_declaration_matches_managed_path():
    import re
    text = (KI / "preflight_check.py").read_text()
    preflight = _load("preflight_binloc5", KI / "preflight_check.py")
    # Same regex as kiss_cli.runnable.declared(): exactly one declared binary, the managed path.
    found = re.findall(r"""check_file\(\s*['"]([^'"]+)['"]""", text)
    assert found == [str(preflight.EF5_BINARY)]


def test_run_ef5_no_binary_found_names_both(tmp_path, monkeypatch, capsys):
    run_ef5 = _load("run_ef5_binloc6", KI / "tools" / "run_ef5.py")
    cands = (str(tmp_path / "a" / "ef5"), str(tmp_path / "b" / "ef5"))
    monkeypatch.setattr(run_ef5, "BINARY_CANDIDATES", cands)
    monkeypatch.setattr(run_ef5.find_binary, "__defaults__", (cands,))
    monkeypatch.setattr(run_ef5, "preflight_check", lambda *a: (_ for _ in ()).throw(AssertionError("ran")))
    monkeypatch.setattr(sys, "argv", ["run_ef5.py", "--control", "missing_control.txt"])
    try:
        run_ef5.main()
        raise AssertionError("main() returned")
    except SystemExit as exc:
        assert exc.code == 1
    err = capsys.readouterr().err
    assert cands[0] in err and cands[1] in err
