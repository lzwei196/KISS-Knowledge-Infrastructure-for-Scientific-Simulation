"""Review cannot approve work without a path to the required run evidence."""
from copy import deepcopy

import pytest

from ki_tools_common.flow import plan


@pytest.fixture
def documents(tmp_path):
    root = tmp_path / "M"
    (root / "tools").mkdir(parents=True)
    tool = root / "tools" / "run.py"
    tool.write_text("print('run')\n", encoding="utf-8")
    pj = {"schema_version": "1.0", "goal": "Validate water balance", "selected_kis": ["M"],
          "created_at": "2026-10-01", "unresolved_questions": [], "scientific_choices": [],
          "steps": [{"id": "run", "ki": "M", "tool": str(tool), "kind": "run",
                     "inputs": ["forcing"], "outputs": ["q"], "status": "planned"}]}
    inv = {"schema_version": "1.0", "items": [
        {"id": "forcing", "required_by": ["M"], "status": "resolved", "local_paths": [],
         "acceptable_sources": ["cmfd_v1", "nasa_power"], "chosen_source": "cmfd_v1",
         "needs_user": False, "agent_resolvable": True}]}
    return pj, inv, {"M": root}


@pytest.mark.parametrize("kind", ["run", "model_run", "process", "prepare", "calibrate", "couple", "route"])
def test_draft_tools_must_be_assigned_before_review(documents, kind):
    pj, inv, roots = documents
    pj["steps"][0].update(kind=kind, tool=None)
    assert plan.validate(pj, inv, ["M"], roots) == []
    for mode in ("for_review", "for_execution"):
        assert any("has no tool" in error for error in plan.validate(pj, inv, ["M"], roots, **{mode: True}))


@pytest.mark.parametrize("outputs", [["outputs/mass_balance.csv"], ["artifacts/report"], ["water_balance"]])
@pytest.mark.parametrize("kind", ["check", "report", "validation"])
def test_informational_kind_cannot_hide_output_production(documents, kind, outputs):
    pj, inv, roots = documents
    pj["steps"][0].update(tool=None, kind=kind, outputs=outputs)
    for mode in ("for_review", "for_execution"):
        errors = plan.validate(pj, inv, ["M"], roots, **{mode: True})
        assert any("declares outputs but has no tool" in error for error in errors)


def test_nonfile_information_and_downloads_remain_reviewable(documents):
    pj, inv, roots = documents
    pj["steps"][0].update(tool=None, kind="check", outputs=[])
    assert plan.validate(pj, inv, ["M"], roots, for_execution=True) == []
    pj["steps"][0].update(kind="download", inputs=[], outputs=["forcing"])
    assert plan.validate(pj, inv, ["M"], roots, for_execution=True) == []


def test_review_allows_pending_user_input_but_execution_needs_a_source(documents):
    pj, inv, roots = documents
    inv["items"][0].update(status="missing", chosen_source=None, needs_user=True)
    assert plan.validate(pj, inv, ["M"], roots, for_review=True) == []
    assert any("still missing" in error for error in plan.validate(pj, inv, ["M"], roots, for_execution=True))


@pytest.mark.parametrize("source", [
    {"chosen_source": "nasa_power"}, {"dataset_id": "cmfd_v1", "delivery": "served"},
    {"dataset_id": "cmfd_v1", "delivery": "subset"}, {"decision": "use the KI default"},
])
def test_known_acquisition_can_run_after_approval(documents, source):
    pj, inv, roots = documents
    inv["items"][0].update({"status": "missing", "chosen_source": None, **source})
    assert plan.validate(pj, inv, ["M"], roots, for_execution=True) == []


def test_earlier_receipted_step_can_resolve_a_missing_input(documents):
    pj, inv, roots = documents
    inv["items"][0].update(status="missing", chosen_source=None)
    prepare = {**deepcopy(pj["steps"][0]), "id": "prepare", "kind": "prepare",
               "inputs": [], "outputs": ["forcing"]}
    pj["steps"].insert(0, prepare)
    assert plan.validate(pj, inv, ["M"], roots, for_execution=True) == []
    prepare.update(tool=None, kind="check")
    errors = plan.validate(pj, inv, ["M"], roots, for_execution=True)
    assert any("still missing" in error for error in errors)


def source_choice(pj, **changes):
    choice = {"id": "data:forcing", "kind": "data_source", "item": "forcing", "high_impact": True,
              "options": ["cmfd_v1", "nasa_power"], "picked": "cmfd_v1", **changes}
    pj["scientific_choices"] = [choice]
    return choice


@pytest.mark.parametrize("changes,expected", [
    ({"picked": "nasa_power"}, "uses 'cmfd_v1'"),
    ({"picked": "unknown"}, "not among its options"),
    ({"item": "missing"}, "not in the data inventory"),
    ({"decision": "nasa_power"}, "decision and picked recommendation disagree"),
    ({"options": []}, "nonempty array"),
    ({"options": [{"id": "cmfd_v1"}]}, "source strings"),
])
def test_data_choice_cannot_disagree_with_the_acquired_source(documents, changes, expected):
    pj, inv, roots = documents
    source_choice(pj, **changes)
    assert any(expected in error for error in plan.data_source_errors(pj, inv))
    assert any(expected in error for error in plan.validate(pj, inv, ["M"], roots))


def test_external_source_and_inventory_recommendation_are_valid(documents):
    pj, inv, roots = documents
    inv["items"][0]["chosen_source"] = "nasa_power"
    source_choice(pj, picked="nasa_power")
    assert plan.validate(pj, inv, ["M"], roots, for_review=True) == []
    pj["scientific_choices"][0].pop("picked")
    assert plan.data_source_errors(pj, inv) == []


def test_conflicting_choices_for_the_same_input_are_rejected(documents):
    pj, inv, _roots = documents
    first = source_choice(pj)
    pj["scientific_choices"].append({**first, "id": "alternative", "picked": "nasa_power"})
    assert any("alternative" in error and "uses 'cmfd_v1'" in error
               for error in plan.data_source_errors(pj, inv))
