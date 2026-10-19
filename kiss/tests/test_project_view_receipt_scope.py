"""Display-only history omission preserves current receipt authority checks."""
import pytest

from kiss_cli import projectview
from .test_project_view_reports import report, signed_report  # real signed fixture; no execution


def test_view_skips_historical_scan_but_keeps_exact_current_association(signed_report, monkeypatch):
    (project, path), flow, record, receipt = signed_report
    def forbidden(*args):
        raise AssertionError("The view must not inspect historical output bytes")
    monkeypatch.setattr(flow.receipts, "_historical_outputs", forbidden)
    associations = projectview._report_receipts(project)
    assert associations[path.relative_to(project).as_posix()]["receipt"]["path"] == receipt.relative_to(project).as_posix()
    path.write_bytes(b'{"changed":true}')
    assert not projectview._report_receipts(project)


def test_default_evidence_retains_history_and_current_checks_are_identical(signed_report, monkeypatch):
    (project, path), flow, record, receipt = signed_report
    plan, inventory = flow.plan.read_artifacts(project)
    approval = flow.approval.read(project)
    calls = []
    original = flow.receipts._historical_outputs
    def history(*args):
        calls.append(True)
        return original(*args)
    monkeypatch.setattr(flow.receipts, "_historical_outputs", history)
    full = flow.receipts.evidence(project, plan, approval, inventory=inventory)
    assert calls == [True]
    display = flow.receipts.evidence(project, plan, approval, inventory=inventory,
                                    output_dirs=(), include_history=False)
    assert calls == [True]
    for key in ("runs", "steps_passed", "steps_missing", "stale_steps", "current_failures",
                "rejected_receipts", "receipts_verified", "validation"):
        assert display[key] == full[key]


@pytest.mark.parametrize("directories", [("outputs",), ["outputs"], iter(("outputs",))])
def test_history_omission_refuses_artifact_classification(signed_report, directories):
    (project, path), flow, record, receipt = signed_report
    with pytest.raises(ValueError, match="display-only"):
        flow.receipts.evidence(project, {}, {}, output_dirs=directories, include_history=False)


def test_history_omission_with_default_completion_arguments_is_refused(signed_report):
    (project, path), flow, record, receipt = signed_report
    with pytest.raises(ValueError, match="display-only"):
        flow.receipts.evidence(project, {}, {}, include_history=False)


def test_later_failed_attempt_still_removes_association(signed_report):
    (project, path), flow, record, receipt = signed_report
    assert projectview._report_receipts(project)
    record(5, False)
    assert not projectview._report_receipts(project)


def test_default_completion_still_rechecks_old_output_bytes(signed_report):
    (project, path), flow, record, receipt = signed_report
    previous = path.with_name("previous.json")
    previous.write_bytes(b'{"retained":true}')
    record(3, outputs=[path, previous])
    flow.approval.approve(project, by="user")
    record(6)
    plan, inventory = flow.plan.read_artifacts(project)
    approval = flow.approval.read(project)
    original = flow.receipts.evidence(project, plan, approval, inventory=inventory)
    assert original["receipts_verified"] is True
    assert [entry["path"] for entry in original["historical_outputs"]] == [previous.relative_to(project).as_posix()]
    previous.write_bytes(b'{"retained":false}')
    changed = flow.receipts.evidence(project, plan, approval, inventory=inventory)
    assert changed["receipts_verified"] is False
    assert previous.relative_to(project).as_posix() in changed["unreceipted_artifacts"]
    # Unrelated old output corruption cannot falsely grant completion, and does
    # not revoke the view's distinct exact current-file association either.
    assert path.relative_to(project).as_posix() in projectview._report_receipts(project)
