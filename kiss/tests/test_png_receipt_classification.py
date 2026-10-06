"""Exercise real Desktop tool dispatch and signed receipts with a fixture PNG.

The child only writes embedded image bytes; no native/scientific model runs.
"""
import base64
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from kiss_cli import api
from .test_flowgate import _cfg, _ki, _plan, _session


@pytest.mark.parametrize("kind,passes", [("run", False), ("model_run", False),
                                         ("route", False), ("process", True)])
def test_png_only_run_kinds_cannot_complete_but_plot_process_can(tmp_path, monkeypatch, kind, passes):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))
    picture = io.BytesIO()
    Image.new("RGB", (2, 3), (10, 30, 20)).save(picture, format="PNG")
    encoded = base64.b64encode(picture.getvalue()).decode("ascii")
    ki = _ki(tmp_path, extra_files={"tools/run.py": "import base64,pathlib,sys\n"
                    "out=pathlib.Path(sys.argv[1]);out.parent.mkdir(parents=True,exist_ok=True)\n"
                    f"out.write_bytes(base64.b64decode({encoded!r}))\n"})
    project, flow = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    plan, inventory = _plan(ki)
    plan["steps"][0]["kind"] = kind
    assert flow.write_plan(plan, inventory) == []
    flow.flow.approval.approve(project, by="auto")
    flow.reload_artifacts()
    flow.move("plan_written", {"plan_valid": True})
    flow.move("approved", {"approval": "OK"})
    flow.move("execution_started", {"setup_verified": True})
    result = api.execute_tool("run_ki_tool", {
        "tool_path": "tools/run.py", "arguments": ["artifacts/figure.png"], "plan_step_id": "M:run",
    }, ki, _cfg(project), project_mode=True, flow=flow)
    assert result.startswith("exit_code=0"), result
    summary = json.loads(result.splitlines()[1].removeprefix("[RECEIPT] "))
    assert summary["validation"] == ("passed" if passes else "warning")
    receipt = json.loads(Path(summary["receipt"]).read_text(encoding="utf-8"))
    assert flow.flow.receipts.verify(project, receipt)
    checks = receipt["validation"]["checks"]
    assert any(c["check"].startswith("png_decode:") and c["ok"] for c in checks)
    assert any(c["check"] == "any_numeric_output" and not c["ok"] for c in checks) is not passes
    proof = flow.evidence()
    assert proof["receipts_verified"] is passes
    assert proof["validation"] == ("passed" if passes else "incomplete")
    assert proof["steps_missing"] == ([] if passes else ["M:run"])
