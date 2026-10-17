"""Current signed failures must contradict an overbroad provider completion claim."""
import json
import sys
import time

from kiss_cli import execution_context, flowrun
from .test_flowrun import _executing


def test_failed_native_attempt_gets_explicit_host_verdict(tmp_path):
    project, turn, run = _executing(tmp_path, extra_files={
        "tools/run.py": "import sys\nsys.exit(2)\n"})
    assert "exit_code=2" in run(["outputs/q.csv"])
    result = flowrun.after(project, turn, "The end-to-end acceptance is complete.")
    evidence = json.loads((project / "runs/evidence.json").read_text(encoding="utf-8"))
    failure, = evidence["current_failures"]
    assert failure["exit_code"] == 2
    assert failure["plan_step_id"] == turn.session.plan["steps"][0]["id"]
    assert "not complete" in result.message and "exit 2" in result.message
    assert failure["plan_step_id"] in result.message
    assert turn.session.state.value == "FAILED_VALIDATION"
    assert not result.continue_now


def test_failed_check_reason_survives_to_host_verdict_and_next_provider_context(tmp_path):
    project, turn, _ = _executing(tmp_path)
    fs = turn.session
    step = fs.plan["steps"][0]
    fs.flow.receipts.record_run(project, ki="M", executable=sys.executable,
        command=[sys.executable, str(fs.ki_roots["M"] / "tools/run.py"), "outputs/q.csv"],
        cwd=str(project), started_at=time.time(), finished_at=time.time(), exit_code=0,
        inputs=[], outputs=[], approval_sha256=fs.approval_id, plan_step_id=step["id"],
        validation={"status": "failed", "checks": [{"check": "declared_format",
            "ok": False, "detail": "Transformed configuration needs an explicit format contract."}]})
    result = flowrun.after(project, turn, "All complete.")
    evidence = json.loads((project / "runs/evidence.json").read_text(encoding="utf-8"))
    handoff = execution_context.handoff(evidence)
    assert "Transformed configuration needs an explicit format contract" in result.message
    assert "Transformed configuration needs an explicit format contract" in handoff
    assert '"exit_code":0' in handoff  # exit zero alone is not a verified step
    assert '"current_failures"' in handoff


def test_successful_retry_removes_failure_from_current_context_but_preserves_history(tmp_path):
    project, turn, run = _executing(tmp_path, extra_files={"tools/run.py":
        "import pathlib, sys\n"
        "if pathlib.Path('fail-next').exists(): sys.exit(2)\n"
        "p=pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_text('t,q\\n1,0.5\\n2,1.2\\n3,0.8\\n')\n"})
    (project / "fail-next").touch()
    run(["outputs/q.csv"])
    (project / "fail-next").unlink()
    run(["outputs/q.csv"])
    result = flowrun.after(project, turn, "Complete.")
    evidence = json.loads((project / "runs/evidence.json").read_text(encoding="utf-8"))
    assert evidence["current_failures"] == []
    assert len(evidence["superseded_failures"]) == 1
    assert evidence["validation"] == "passed"
    assert "earlier failed attempt" in result.message


def test_later_failure_is_current_even_after_a_success(tmp_path):
    project, turn, run = _executing(tmp_path, extra_files={"tools/run.py":
        "import pathlib, sys\n"
        "if pathlib.Path('fail-next').exists(): sys.exit(2)\n"
        "p=pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_text('t,q\\n1,0.5\\n2,1.2\\n3,0.8\\n')\n"})
    run(["outputs/q.csv"])
    (project / "fail-next").touch()
    run(["outputs/q.csv"])
    evidence = turn.session.evidence()
    failure, = evidence["current_failures"]
    assert failure["exit_code"] == 2 and evidence["validation"] == "failed"
    assert not evidence["superseded_failures"]


def test_failure_presentation_is_bounded_and_does_not_invent_runtime_cause():
    evidence = {"current_failures": [{"plan_step_id": "check_params", "run_id": "current",
        "exit_code": 2, "validation_reason": "stdout check execution did not succeed",
        "failed_checks": []}]}
    verdict = execution_context.failed_verdict(evidence)
    assert "check_params" in verdict and "exit 2" in verdict
    assert "ImportError" not in verdict and "PCSE" not in verdict
    evidence["current_failures"][0]["failed_checks"] = [{"check": "format", "detail": "x\n" * 1000}]
    compact = execution_context.current_failures(evidence)[0]["failed_checks"][0]["detail"]
    assert len(compact) <= 600 and "\n" not in compact
