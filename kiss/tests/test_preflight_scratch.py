"""Real harmless preflights exercise source-preserving execution copies."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import install, ki_guard, ki_verification, paths
from kiss_cli.catalog import KI


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(tmp_path / "guards"))
    workspace = tmp_path / "work"
    root = workspace / "ki"
    (root / "tools").mkdir(parents=True)
    (root / "SKILL.md").write_text("# Original protocol\n", encoding="utf-8")
    (root / "tools/helper.py").write_text("VALUE = 42\n", encoding="utf-8")
    cfg = paths.KissConfig.default(workspace)
    cfg.python = sys.executable
    cfg.relocation = "none"
    return SimpleNamespace(root=root, cfg=cfg, ki=KI("Demo", root))


def seal(case, source):
    (case.root / "preflight_check.py").write_text(source, encoding="utf-8")
    ki_guard.enroll(case.root)
    return ki_verification.content_digest(case.root)


def run(case, **kwargs):
    return install.run_preflight(case.ki, case.cfg.python, case.cfg,
                                 project=case.cfg.root, **kwargs)


def test_real_child_uses_identical_copy_and_keeps_native_startup_artifacts(case):
    source = """import json, subprocess, sys
from pathlib import Path
root = Path(__file__).resolve().parent
subprocess.run([sys.executable, '-c', "from pathlib import Path; Path('ERROR.OUT').write_text('startup fixture')"], cwd=root, check=True)
print('PREFLIGHT_REPORT=' + json.dumps({'checks':[{'kind':'run','subject':sys.executable,'critical':True,'status':'pass','fix':''}], 'actual_ki':str(root)}))
"""
    before = seal(case, source)
    step = run(case)
    assert step.ok, step.detail
    assert ki_verification.content_digest(case.root) == before
    assert not (case.root / "ERROR.OUT").exists()
    evidence = step.evidence
    scratch = Path(evidence["execution_root"])
    assert scratch != case.root and scratch.is_relative_to(case.cfg.root)
    assert evidence["source_digest"] == evidence["execution_digest"] == before
    assert (scratch / "preflight_check.py").read_bytes() == (case.root / "preflight_check.py").read_bytes()
    assert (scratch / "ERROR.OUT").read_text() == "startup fixture"
    assert "ERROR.OUT" in evidence["created_paths"]
    assert str(scratch) in step.commands[0]
    report = json.loads(step.detail.split("PREFLIGHT_REPORT=", 1)[1].splitlines()[0])
    assert report["actual_ki"] == str(scratch)
    assert report["checks"][0]["subject"] == sys.executable
    record = json.loads(Path(evidence["record_path"]).read_text(encoding="utf-8"))
    assert record["ok"] and record["source_intact"]
    assert "PREFLIGHT_REPORT=" in Path(evidence["output_path"]).read_text(encoding="utf-8")
    ki_guard.require_intact(case.root)


def test_missing_mandatory_data_still_fails_with_original_report(case):
    before = seal(case, "print('PREFLIGHT_REPORT={\"checks\":[{\"critical\":true,\"status\":\"fail\",\"subject\":\"missing cultivar\",\"fix\":\"restore it\"}]}')\nraise SystemExit(1)\n")
    step = run(case)
    assert not step.ok
    assert "missing cultivar" in step.detail
    assert step.evidence["returncode"] == 1
    assert ki_verification.content_digest(case.root) == before


@pytest.mark.parametrize("action", ["edit", "delete", "replace_with_alias"])
def test_preexisting_copy_input_changes_cannot_pass(case, action):
    action_source = {
        "edit": "target.write_text('changed')",
        "delete": "target.unlink()",
        "replace_with_alias": "target.unlink(); target.symlink_to(Path('preflight_check.py'))",
    }[action]
    before = seal(case, "from pathlib import Path\nroot=Path(__file__).parent\ntarget=root/'SKILL.md'\n" + action_source + "\nprint('PASS fixture')\n")
    step = run(case)
    assert not step.ok
    assert "copied KI input" in step.detail
    assert "SKILL.md" in step.evidence["changed_inputs"]
    assert ki_verification.content_digest(case.root) == before


def test_explicit_original_source_write_still_fails_integrity(case):
    seal(case, "from pathlib import Path\nPath(" + repr(str(case.root / "SKILL.md")) + ").write_text('unapproved original write')\nprint('PASS fixture')\n")
    step = run(case)
    assert not step.ok and not step.evidence["source_intact"]
    with pytest.raises(ki_guard.KIIntegrityError, match="changed"):
        ki_guard.require_intact(case.root)
    assert (case.root / "SKILL.md").read_text() == "unapproved original write"


def test_runtime_binding_change_during_probe_cannot_pass(case, monkeypatch):
    seal(case, "print('PASS fixture')\n")
    original = install._run
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        case.cfg.roles["data"] = case.cfg.root / "different-data"
        return result
    monkeypatch.setattr(install, "_run", changed)
    step = run(case)
    assert not step.ok and "runtime binding changed" in step.detail


def test_stop_supervises_child_and_retains_cancelled_evidence(case):
    seal(case, """import subprocess, sys, time
from pathlib import Path
root=Path(__file__).parent
print('BEFORE STOP ' + 'x' * 10000, flush=True)
child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], cwd=root)
(root/'child.pid').write_text(str(child.pid))
time.sleep(60)
""")
    def stopped():
        return any((case.cfg.root / ".geoforge/preflight").glob("*/ki/child.pid"))
    step = run(case, stop=stopped)
    assert not step.ok and step.evidence["state"] == "cancelled"
    assert "Stopped" in step.detail
    output = Path(step.evidence["output_path"]).read_text(encoding="utf-8")
    assert output.startswith("BEFORE STOP ") and len(output) > 10000
    assert step.evidence["output_truncated"] is False
    ki_guard.require_intact(case.root)
    if os.name == "nt":
        pid = (Path(step.evidence["execution_root"]) / "child.pid").read_text()
        result = subprocess.run(["tasklist", "/FI", "PID eq " + pid, "/FO", "CSV", "/NH"],
                                capture_output=True, text=True, timeout=10)
        assert '"' + pid + '"' not in result.stdout


def test_stale_original_source_never_executes(case, monkeypatch):
    seal(case, "print('PASS fixture')\n")
    (case.root / "SKILL.md").write_text("changed before launch")
    monkeypatch.setattr(install, "_run", lambda *a, **k: pytest.fail("must not execute changed source"))
    assert not run(case).ok


def test_contained_aliases_are_preserved_without_expanding_inputs(case):
    (case.root / "alias.py").symlink_to(Path("tools/helper.py"))
    before = seal(case, "from pathlib import Path\nroot=Path(__file__).parent\nassert (root/'alias.py').is_symlink()\nassert (root/'alias.py').read_text() == 'VALUE = 42\\n'\nprint('PASS fixture')\n")
    step = run(case)
    assert step.ok, step.detail
    assert step.evidence["execution_digest"] == before
    assert (Path(step.evidence["execution_root"]) / "alias.py").is_symlink()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction boundary")
def test_evidence_parent_junction_is_rejected_before_writes(case, tmp_path):
    seal(case, "print('PASS fixture')\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = case.cfg.root / ".geoforge"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    try:
        step = run(case)
        assert not step.ok and "reparse" in step.detail
        assert list(outside.iterdir()) == []
    finally:
        junction.rmdir()


def test_parent_relative_preflight_failure_is_not_hidden(case):
    seal(case, "from pathlib import Path\nassert (Path(__file__).parent.parent/'workspace-only').exists(), 'missing original parent file'\n")
    (case.cfg.root / "workspace-only").write_text("outside KI")
    step = run(case)
    assert not step.ok and "missing original parent file" in step.detail


def test_stop_during_final_record_replacement_revokes_success(case, monkeypatch):
    seal(case, "print('PASS fixture')\n")
    stopped = {"value": False}
    replace = install.os.replace
    def stop_at_publication(source, destination):
        result = replace(source, destination)
        if Path(destination).name == "execution.json":
            stopped["value"] = True
        return result
    monkeypatch.setattr(install.os, "replace", stop_at_publication)
    step = run(case, stop=lambda: stopped["value"])
    assert not step.ok and step.evidence["state"] == "cancelled"
    saved = json.loads(Path(step.evidence["record_path"]).read_text(encoding="utf-8"))
    assert not saved["ok"] and saved["state"] == "cancelled"


def test_execution_copy_change_before_launch_is_rejected(case, monkeypatch):
    seal(case, "print('PASS fixture')\n")
    inventory = install._preflight_inputs
    def changed(root):
        rows = inventory(root)
        (root / "preflight_check.py").write_text("print('different code')\n")
        return rows
    monkeypatch.setattr(install, "_preflight_inputs", changed)
    monkeypatch.setattr(install, "_run", lambda *a, **k: pytest.fail("changed copy must not execute"))
    step = run(case)
    assert not step.ok and not step.evidence["launch_attempted"]
    assert "changed before launch" in step.detail


def test_copy_alias_cannot_be_retargeted_to_another_existing_file(case):
    (case.root / "alias.py").symlink_to(Path("tools/helper.py"))
    before = seal(case, "from pathlib import Path\nroot=Path(__file__).parent\na=root/'alias.py'\na.unlink(); a.symlink_to(Path('SKILL.md'))\nprint('PASS fixture')\n")
    step = run(case)
    assert not step.ok and "alias.py" in step.evidence["changed_inputs"]
    assert ki_verification.content_digest(case.root) == before


def test_no_config_legacy_call_still_uses_exact_scratch_copy(case):
    before = seal(case, "print('PASS fixture')\n")
    step = install.run_preflight(case.ki, sys.executable)
    assert step.ok, step.detail
    assert step.evidence["runtime_identity"] is None
    assert step.evidence["source_digest"] == before


@pytest.mark.parametrize("returncode", [0, 1])
def test_large_structured_report_is_retained_with_bounded_ui_detail(case, returncode):
    report = {"model_id": "Demo", "checks": [
        {"kind": "data", "subject": "input-" + str(index), "critical": True,
         "status": "fail" if returncode else "pass", "fix": "required action " * 20}
        for index in range(100)]}
    line = "PREFLIGHT_REPORT=" + json.dumps(report)
    before = seal(case, "import sys\nprint('ORIGINAL OUTPUT START')\nprint(" + repr(line) +
                  ")\nprint('STDERR END', file=sys.stderr)\nraise SystemExit(" + str(returncode) + ")\n")
    step = run(case)
    assert step.ok is (returncode == 0)
    output = Path(step.evidence["output_path"]).read_text(encoding="utf-8")
    assert len(output) > 8000
    assert output.startswith("ORIGINAL OUTPUT START\n")
    assert output.endswith("STDERR END\n")
    assert step.evidence["output_chars"] == len(output)
    assert step.evidence["output_truncated"] is False
    saved_report = json.loads(next(row for row in output.splitlines()
                                  if row.startswith("PREFLIGHT_REPORT=")).partition("=")[2])
    assert saved_report == report
    assert len(step.detail) < 8500
    assert ki_verification.content_digest(case.root) == before


def test_generic_install_runner_keeps_existing_bounded_output_default():
    rc, output = install._run([sys.executable, "-c", "print('START' + 'x' * 10000)"])
    assert rc == 0 and len(output) == 8000
    assert "START" not in output
