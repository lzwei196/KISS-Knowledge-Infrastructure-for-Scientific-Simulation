"""Review catches occupied stdout paths without invalidating captured receipts."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, execution, flowgate, flowrun
from kiss_cli.catalog import KI
from .test_execution import _execute, _receipt_docs
from .test_stdout_artifacts import approved, helpers


def draft(tmp_path, monkeypatch):
    ctx = approved(tmp_path, monkeypatch)
    ctx.flow.request_replan("Review a new reader attempt")
    return ctx


def occupied(ctx):
    path = ctx.project / "outputs/check/readout.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"previous": 1}')
    return path


@pytest.mark.parametrize("route", ["flow_session", "api", "cli"])
def test_occupied_destination_is_refused_before_new_review(tmp_path, monkeypatch, route):
    ctx = draft(tmp_path, monkeypatch)
    path = occupied(ctx)
    before = {p: p.read_bytes() for p in (ctx.project / "runs").glob("*.json")}
    if route == "flow_session":
        message = "\n".join(ctx.flow.write_plan(ctx.plan, ctx.inventory))
    elif route == "api":
        message = api.execute_tool("write_plan", {"plan": ctx.plan, "data_inventory": ctx.inventory},
            KI("M", ctx.root), ctx.cfg, project_mode=True, flow=ctx.flow)
        assert message.startswith("PLAN NOT WRITTEN")
    else:
        # CLI providers author their draft files; host completion still reviews
        # them before issuing the user approval card.
        ctx.flow.flow.plan.write_artifacts(ctx.project, ctx.plan, ctx.inventory)
        turn = flowrun.Turn(ctx.flow, False, "", False,
            SimpleNamespace(provider="claude"), "fixture", provider_succeeded=True)
        result = flowrun.after(ctx.project, turn, "Reader plan ready")
        assert result.request is None
        message = (ctx.project / "runs/plan-validation.txt").read_text(encoding="utf-8")
    assert "outputs/check/readout.json" in message and "already exists" in message
    assert "fresh output path" in message and "inventory local_paths" in message
    assert "preserve the existing file" in message
    assert path.read_bytes() == b'{"previous": 1}'
    assert not (ctx.project / "runs/approval.json").exists()
    assert not _receipt_docs(ctx)
    if route != "cli":
        assert all(p.read_bytes() == content for p, content in before.items())


def test_fresh_path_and_matching_inventory_make_replan_reviewable(tmp_path, monkeypatch):
    ctx = draft(tmp_path, monkeypatch)
    old = occupied(ctx)
    plan, inventory = deepcopy(ctx.plan), deepcopy(ctx.inventory)
    plan["steps"][0]["stdout_artifact"]["path"] = "outputs/check/attempt2/readout.json"
    # Changing just the capture path must not silently retarget its inventory.
    assert any("declared local_paths" in e for e in ctx.flow.write_plan(plan, inventory))
    row = next(i for i in inventory["items"] if i["id"] == "readout")
    row["local_paths"] = ["outputs/check/attempt2/readout.json"]
    assert ctx.flow.write_plan(plan, inventory) == []
    assert old.read_bytes() == b'{"previous": 1}'
    assert not (ctx.project / row["local_paths"][0]).exists()


def test_file_created_after_approval_still_blocks_before_launch(tmp_path, monkeypatch):
    ctx = approved(tmp_path, monkeypatch)
    path = occupied(ctx)
    monkeypatch.setattr(execution, "run_process", lambda *a, **kw: pytest.fail("reader launched"))
    with pytest.raises(flowgate.FlowDenied, match="fresh destination"):
        _execute(ctx)
    assert path.read_bytes() == b'{"previous": 1}'
    assert not _receipt_docs(ctx)


def test_completed_capture_keeps_runtime_validation_and_signed_receipt_valid(tmp_path, monkeypatch):
    ctx = approved(tmp_path, monkeypatch)
    result = _execute(ctx)
    assert result.receipt["validation"] == "passed"
    receipt_path = Path(result.receipt["receipt"])
    signed = receipt_path.read_bytes()
    receipt, = _receipt_docs(ctx)
    step = ctx.plan["steps"][0]
    assert helpers().step_errors(step, ctx.project, ctx.inventory) == []
    assert helpers().receipt_errors(ctx.project, step, ctx.inventory, receipt) == []
    assert ctx.flow.flow.plan.validate(ctx.plan, ctx.inventory, ["M"], {"M": ctx.root},
        project=ctx.project, for_execution=True) == []
    assert ctx.flow.flow.receipts.verify(ctx.project, receipt)
    assert ctx.flow.evidence()["receipts_verified"] is True
    # Only a proposed NEW review of that occupied destination is refused.
    assert any("already exists" in e for e in ctx.flow.flow.plan.validate(
        ctx.plan, ctx.inventory, ["M"], {"M": ctx.root}, project=ctx.project, for_review=True))
    assert receipt_path.read_bytes() == signed
