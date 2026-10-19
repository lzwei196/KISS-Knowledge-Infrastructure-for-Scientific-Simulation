"""The explicit inspection action is per-message and never an approval."""
import json
import subprocess

import pytest

from .test_chat_send_ui import send
from .test_next_phase_ui import NODE, PAGE, RUNNER

pytestmark = pytest.mark.skipif(NODE is None, reason="Node required for shipped UI")


def probe(**options):
    runner = RUNNER.replace("context.renderNextPhaseAction(input.data)",
                            "context.renderInspectionAction(input.data)")
    runner = runner.replace("context.stageNextPhase(input.data,'original')",
                            "context.stageInspection('original')")
    result = subprocess.run([NODE, "-e", runner, str(PAGE)],
        input=json.dumps({"data": {"project_status": {"progress": {"flow_state": "EXECUTING"}}},
                          **options}), capture_output=True, text=True, encoding="utf-8",
        check=True, timeout=10)
    return json.loads(result.stdout)


@pytest.mark.parametrize("zh", [True, False])
def test_explicit_inspection_has_a_visible_readonly_notice(zh):
    result = probe(zh=zh, draft="Explain the latest logs")
    assert ('查看已有文件' if zh else 'Inspect existing files') in result["html"]
    assert result["pending"] == [["original", {"kind": "inspect_existing"}]]
    assert not result["noticeHidden"]
    assert ("不会运行、安装或更改计划" if zh else "cannot run, install or change the plan") in result["notice"]
    assert result["draft"] == "Explain the latest logs"


def test_cancel_keeps_the_draft_but_removes_the_one_turn_mode():
    result = probe(cancel=True, draft="Read existing files")
    assert result["noticeHidden"] and not result["pending"]
    assert result["draft"] == "Read existing files"


@pytest.mark.parametrize("flag", ["busy", "uploading", "switch_before"])
def test_stale_or_busy_button_never_targets_another_project(flag):
    result = probe(**{flag: True}, draft="Kept")
    assert not result["pending"] and result["draft"] == "Kept"


def test_inspection_mode_stays_with_its_project():
    result = probe(switch_after=True, cancel=True)
    assert result["noticeHidden"]
    assert result["pending"] == [["original", {"kind": "inspect_existing"}]]


def test_send_carries_the_explicit_ceiling_without_an_approval():
    result = send(action={"kind": "inspect_existing"}, draft="Read the receipts")
    request = next(item for item in result["requests"] if item["url"].endswith("/chat"))
    assert request["body"]["action"] == {"kind": "inspect_existing"}
    assert result["accepted"] == 1 and not result["pendingAction"]
