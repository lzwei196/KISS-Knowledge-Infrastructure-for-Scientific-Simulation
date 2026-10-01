"""Captured process diagnostics are evidence, not scientific result columns."""
import json
import sys

import pytest

from ki_tools_common.flow import receipts


FORTRAN_NOTE = "Note: The following floating-point exceptions are signalling: IEEE_UNDERFLOW_FLAG IEEE_DENORMAL\n"
FACTS = {"errored": False, "output_nonempty": True}


@pytest.fixture
def case(tmp_path):
    ki = tmp_path / "ki"
    ki.mkdir()
    (ki / "dag.yaml").write_text("outputs:\n- var: discharge\n  validation_rank: 1\n  unit: m3/s\n", encoding="utf-8")
    result = tmp_path / "result.csv"
    result.write_text("time,discharge\n1,0.4\n2,1.1\n3,0.7\n", encoding="utf-8")
    return ki, result


@pytest.mark.parametrize("name, text", [
    ("shaw.stderr.log", FORTRAN_NOTE),
    ("shaw.stdout.log", "Run Complete\n"),
    ("stderr.log", ""),
    ("MODEL.STDOUT.LOG", "timing 1 2 3\n"),
])
def test_diagnostic_streams_do_not_warn_or_supply_result_values(case, tmp_path, name, text):
    ki, result = case
    diagnostic = tmp_path / name
    diagnostic.write_text(text, encoding="utf-8")
    validation = receipts.validate_outputs(ki, [result, diagnostic], expected_steps=3, run_facts=FACTS)
    assert validation["status"] == "passed"
    assert any(c["check"] == "diagnostic_log:" + name and c["ok"] for c in validation["checks"])
    assert not any(c["check"].endswith(":" + name) and c["check"].startswith(
        ("numeric_content", "no_nan_inf", "time_axis_complete", "physically_required_positive")) for c in validation["checks"])
    logs_only = receipts.validate_outputs(ki, [diagnostic], run_facts=FACTS)
    assert logs_only["status"] != "passed"
    assert any(c["check"] == "any_numeric_output" and not c["ok"] for c in logs_only["checks"])


@pytest.mark.parametrize("bad_data, check", [
    ("time,discharge\n1,nan\n2,1.2\n3,0.9\n", "no_nan_inf:result.csv"),
    ("time,discharge\n1,0\n2,0\n3,0\n", "physically_required_positive:result.csv"),
    ("time,discharge\n1,0.4\n2,0.7\n", "time_axis_complete:result.csv"),
    ("", "non_empty:result.csv"),
])
def test_logs_cannot_hide_invalid_scientific_results(case, tmp_path, bad_data, check):
    ki, result = case
    result.write_text(bad_data, encoding="utf-8")
    diagnostic = tmp_path / "shaw.stdout.log"
    diagnostic.write_text("1,1\n2,2\n3,3\nRun Complete\n", encoding="utf-8")
    validation = receipts.validate_outputs(ki, [result, diagnostic], expected_steps=3, run_facts=FACTS)
    assert validation["status"] == "failed"
    assert any(c["check"] == check and not c["ok"] for c in validation["checks"])


@pytest.mark.parametrize("name", ["simulation.log", "stderr.txt", "result.stderr.log.csv"])
def test_generic_log_and_result_names_keep_numeric_validation(case, tmp_path, name):
    ki, result = case
    other = tmp_path / name
    other.write_text(FORTRAN_NOTE, encoding="utf-8")
    validation = receipts.validate_outputs(ki, [result, other], run_facts=FACTS)
    assert validation["status"] == "warning"
    assert any(c["check"] == "numeric_content:" + name and not c["ok"] for c in validation["checks"])


def test_diagnostics_do_not_override_process_failure_or_missing_artifacts(case, tmp_path):
    ki, result = case
    diagnostic = tmp_path / "shaw.stderr.log"
    assert receipts.validate_outputs(ki, [result, diagnostic], run_facts=FACTS)["status"] == "failed"
    diagnostic.write_text(FORTRAN_NOTE, encoding="utf-8")
    assert receipts.validate_outputs(ki, [result, diagnostic], run_facts={**FACTS, "errored": True})["status"] == "failed"


def test_diagnostic_artifacts_remain_hashed_and_signed(case, tmp_path, tmp_path_factory, monkeypatch):
    ki, result = case
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path_factory.mktemp("diagnostic-test-keys")))
    diagnostic = tmp_path / "shaw.stderr.log"
    diagnostic.write_text(FORTRAN_NOTE, encoding="utf-8")
    validation = receipts.validate_outputs(ki, [result, diagnostic], run_facts=FACTS)
    path = receipts.record_run(tmp_path, ki="M", executable=sys.executable,
        command=[sys.executable, "run.py"], cwd=str(tmp_path), started_at=1, finished_at=2,
        exit_code=0, inputs=[], outputs=[result, diagnostic], plan_step_id="M:run",
        approval_sha256="approved-plan", validation=validation)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipts.verify(tmp_path, receipt)
    entry = next(e for e in receipt["outputs"] if e["path"] == diagnostic.name)
    assert entry["sha256"] == receipts.sha256_file(diagnostic)
    assert receipts._entry_status(tmp_path, entry) == "intact"
    diagnostic.write_text("changed diagnostics\n", encoding="utf-8")
    assert receipts._entry_status(tmp_path, entry) == "changed"
    assert receipt["validation"]["status"] == "passed"
