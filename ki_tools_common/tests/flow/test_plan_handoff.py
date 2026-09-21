"""Portable regressions from the desktop's real VIC/CaMa planning probes."""
from pathlib import Path

import pytest

from ki_tools_common.flow import contracts, plan, policy, resolve, states
from ki_tools_common.flow.tools import is_ki_tool


def documents():
    return ({"schema_version": "1.0", "goal": "plan only", "selected_kis": ["VIC"],
             "created_at": "2026-08-31", "unresolved_questions": [], "scientific_choices": [],
             "steps": [{"id": "check", "ki": "VIC", "tool": None, "kind": "check",
                        "inputs": [], "outputs": [], "status": "planned"}]},
            {"schema_version": "1.0", "items": []})


@pytest.mark.parametrize("field,value", [
    ("selected_kis", [{}]), ("selected_kis", "VIC"), ("steps", {}),
    ("scientific_choices", 1), ("unresolved_questions", "ask"), ("coupling", True),
])
def test_malformed_plan_returns_errors_not_an_exception(field, value):
    pj, inv = documents()
    pj[field] = value
    assert plan.validate(pj, inv, ["VIC"])


@pytest.mark.parametrize("field,value", [("ki", {}), ("tool", {}), ("inputs", [{}]), ("outputs", "q.csv")])
def test_malformed_step_returns_repairable_errors(field, value):
    pj, inv = documents()
    pj["steps"][0][field] = value
    assert plan.validate(pj, inv, ["VIC"])


def test_malformed_inventory_returns_errors():
    pj, inv = documents()
    inv["items"] = 1
    assert plan.validate(pj, inv, ["VIC"])


@pytest.mark.parametrize("prompt", ["准备 VIC-CaMa，输入数据", "Prepare VIC-CaMa, input data"])
def test_punctuation_does_not_drop_the_coupled_model(prompt):
    cat = [{"id": "VIC"}, {"id": "CaMa_Flood"}]
    result = resolve.resolve_kis(prompt, ["VIC"], cat)
    assert result.resolved == ["VIC", "CaMa_Flood"]
    assert resolve.is_scientific_task(prompt)


def test_only_declared_stage_scripts_are_tools(tmp_path):
    root = tmp_path / "KI"
    stage = root / "s1_grid"
    stage.mkdir(parents=True)
    script = stage / "prepare.py"
    script.write_text("pass\n")
    assert not is_ki_tool(root, script)
    (root / "SKILL.md").write_text("Use s1_grid/prepare.py to prepare the grid.")
    assert is_ki_tool(root, script)
    (root / "preflight_check.py").write_text("pass\n")
    assert not is_ki_tool(root, root / "preflight_check.py")
    outside = tmp_path / "outside.py"
    outside.write_text("pass\n")
    (root / "tools").mkdir()
    link = root / "tools" / "escape.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this host")
    assert not is_ki_tool(root, link)


@pytest.mark.parametrize("state", [states.State.PLANNING, states.State.REPLAN_REQUIRED,
                                  states.State.PLAN_REVIEW, states.State.WAITING_FOR_USER])
def test_preflight_is_not_a_readonly_planning_tool(state):
    assert not policy.api_tool_allowed(state, "run_preflight")
    assert not policy.api_tool_allowed(state, "run_ki_tool")
    assert not policy.api_tool_allowed(state, "fetch_data")


def test_unicode_absolute_claude_paths_and_planning_contract(tmp_path):
    project = tmp_path / "带 空格的项目"
    assert policy.claude_path(project) == "/" + str(project)
    assert policy.claude_path(r"C:\Users\User Name\项目") == "//c/Users/User Name/项目"
    pp = policy.for_state(states.State.PLANNING, "claude", project, {})
    assert "dontAsk" not in pp.argv_delta and "dontAsk" in pp.argv_extra and "Bash(" not in " ".join(pp.argv_delta)
    pj, inv = documents()
    pj.update(summary="bad draft", coupling=[None])
    text = contracts.planning_block({}, pj, inv, project, replan_reason="missing input ID")
    assert "kind:'check', tool:null" in text and "missing input ID" in text
    assert "do NOT compile" in text


def test_bundled_catalogue_matches_its_manifest():
    import hashlib
    import json
    data = Path(plan.__file__).parent / "data"
    manifest = data / "MANIFEST.json"
    if not manifest.is_file():
        pytest.skip("server uses its live catalogue; no desktop snapshot present")
    entries = json.loads(manifest.read_text())["files"]
    assert entries
    for relative, expected in entries.items():
        path = (data / relative).resolve()
        assert path.is_relative_to(data.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, relative


@pytest.mark.parametrize("key,value", [("scientific_choices", [None]),
    ("scientific_choices", [{"high_impact": "false"}]),
    ("scientific_choices", [{"high_impact": False, "options": 1}]),
    ("coupling", [None]), ("coupling", [{"edge_id": {}}])])
def test_review_card_fields_cannot_crash_after_validation(key, value):
    pj, inv = documents()
    pj[key] = value
    assert plan.validate(pj, inv, ["VIC"])


def test_duplicate_step_ids_and_bad_paths_are_rejected(tmp_path):
    pj, inv = documents()
    pj["steps"].append(dict(pj["steps"][0]))
    assert any("unique" in e for e in plan.validate(pj, inv, ["VIC"]))
    assert not is_ki_tool(tmp_path, "bad\x00path.py")


def test_declared_model_binary_is_a_tool(tmp_path):
    from ki_tools_common.flow.tools import is_declared_binary
    root = tmp_path / "KI"
    root.mkdir()
    exe = tmp_path / "binaries" / "vic_classic.exe"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\necho vic\n")
    exe.chmod(0o755)
    assert not is_ki_tool(root, exe)                       # nothing declared yet
    (root / "knowledge_infrastructure.yaml").write_text(
        f"model:\n  binary:\n    path: {exe}\n    type: ELF\n")
    assert is_ki_tool(root, exe) and is_declared_binary(root, exe)
    other = tmp_path / "binaries" / "other"
    other.write_text("#!/bin/sh\n")
    other.chmod(0o755)
    assert not is_ki_tool(root, other)                     # declared paths only
