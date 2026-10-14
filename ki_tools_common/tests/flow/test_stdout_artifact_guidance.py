"""Shared-provider discovery of explicit KI stdout checks, without running tools."""
from copy import deepcopy
import json
import re

import pytest

from ki_tools_common.flow import contracts, stdout_artifacts


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("KI_HARNESS_FULL", "0")
    ki = tmp_path / "Example"
    (ki / "tools").mkdir(parents=True)
    (ki / "SKILL.md").write_text(
        "# Example KI\n> **MANDATORY EXECUTION POLICY**\n"
        "> Use the declared tools; never substitute a toy model.\n\n"
        "## Execution protocol\nRun tools/read_results.py to inspect native results.\n",
        encoding="utf-8",
    )
    (ki / "tools/read_results.py").write_text(
        "raise RuntimeError('prompt tests cannot execute a reader')\n", encoding="utf-8"
    )
    plan = {"selected_kis": ["Example"], "steps": [], "scientific_choices": []}
    inventory = {"schema_version": "1.0", "items": []}
    return {"Example": ki}, plan, inventory, tmp_path / "project"


def check_guidance(text):
    assert text.count("[SHIPPED KI STDOUT CHECKS]") == 1
    for rule in (
        "canonical absolute path to the shipped KI tool",
        "approved kind:'check' step",
        "literal command array containing only its documented arguments",
        "not the interpreter or tool path",
        "cwd:'.' (project root)",
        "output_id exactly once in step.outputs and never in step.inputs",
        "status:'missing'",
        "do not mark it ready before capture",
        "fresh .json path under outputs/ or artifacts/",
        "no overwrite, aliases or collision",
        "integer max_bytes from 1 to 1048576 before approval",
        "usual run_ki_tool or run-tool receipt path",
        "full successful stdout, separately from stderr and diagnostic tails",
        "finite numbers and no duplicate keys",
        "failed, stopped, truncated or oversized result cannot supply this evidence",
        "Do not add shell redirection, wrap/reimplement the KI reader",
        "unavailable for tool:null, project_data_tool, calibration or model-run steps",
        "check evidence only, never model-execution evidence or scientific validation",
        "model run still needs its own native result evidence",
    ):
        assert rule in text


@pytest.mark.parametrize("provider", ["api", "claude", "codex", "gemini"])
def test_planning_reveals_stdout_contract_for_api_and_each_cli(case, provider):
    kis, plan, inventory, project = case
    before = deepcopy((plan, inventory))
    wrappers = None if provider == "api" else {"run_tool": "kiss run-tool", "fetch": "kiss fetch"}
    text = contracts.planning_block(kis, plan, inventory, project, wrappers=wrappers)
    check_guidance(text)
    assert "NO execution" in text
    assert "stdout_artifact?:{version,output_id,path,format,max_bytes}" in text
    assert (plan, inventory) == before and not project.exists()


@pytest.mark.parametrize("provider", ["api", "claude", "codex", "gemini"])
def test_execution_repeats_same_contract_without_promoting_check_to_model_evidence(case, provider):
    kis, plan, inventory, project = case
    before = deepcopy((plan, inventory))
    wrappers = None if provider == "api" else {"run_tool": "kiss run-tool", "fetch": "kiss fetch"}
    text = contracts.execution_block(kis, plan, {}, project, provider=provider, wrappers=wrappers)
    check_guidance(text)
    assert (plan, inventory) == before and not project.exists()


def test_prompt_json_example_matches_real_binding_validator_and_keeps_output_uncreated(case):
    kis, plan, inventory, project = case
    text = contracts.planning_block(kis, plan, inventory, project)
    capture = json.loads(re.search(r"stdout_artifact: (\{[^}]+\})", text).group(1))
    assert set(capture) == stdout_artifacts.FIELDS
    assert capture["max_bytes"] == stdout_artifacts.MAX_BYTES
    project.mkdir()
    tool = (kis["Example"] / "tools/read_results.py").resolve()
    step = {"id": "read-results", "ki": "Example", "tool": str(tool), "kind": "check",
            "command": [], "cwd": ".", "inputs": [], "outputs": [capture["output_id"]],
            "stdout_artifact": capture}
    row = {"id": capture["output_id"], "local_paths": [capture["path"]], "status": "missing"}
    inventory["items"].append(row)
    value, item, destination = stdout_artifacts.contract(step, project, inventory)
    assert value == capture and item == row
    assert destination == project / capture["path"] and not destination.exists()
    assert stdout_artifacts.step_errors(step, project, inventory) == []


def test_short_continuation_does_not_duplicate_full_instruction_block(case):
    kis, plan, _inventory, project = case
    text = contracts.execution_block(kis, plan, {}, project, short=True)
    assert "[SHIPPED KI STDOUT CHECKS]" not in text
    assert "STAGE GROUNDING" in text
