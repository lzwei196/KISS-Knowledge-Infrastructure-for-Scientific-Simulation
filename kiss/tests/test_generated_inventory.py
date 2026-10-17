"""Catalogue IDs describe external inputs, never computed reports/intermediates."""
from copy import deepcopy

import pytest

from kiss_cli import acquire, flowgate, ki_guard, obs_access, plan_review


CATALOGUE = {"datasets": [{"id": "dssat_data", "name": "DSSAT supporting data",
                           "delivery": "manual", "size": 289302118}]}


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setattr(obs_access, "refresh_catalogue", lambda **kw: deepcopy(CATALOGUE))
    monkeypatch.setattr(obs_access, "resolved_records", lambda: [])
    monkeypatch.setattr(obs_access.Client, "download", lambda *a, **kw: pytest.fail("test must not download"))
    project = tmp_path / "project"
    root = project / "models/DSSAT/ki"
    (root / "tools").mkdir(parents=True)
    tool = root / "tools/check.py"
    tool.write_text("raise RuntimeError('fixture must not execute')\n", encoding="utf-8")
    (root / "SKILL.md").write_text("# DSSAT fixture\n", encoding="utf-8")
    (root / "dag.yaml").write_text("outputs:\n- var: final\n  validation_rank: 1\n  unit: 1\n", encoding="utf-8")
    ki_guard.enroll(root)
    plan = {"schema_version": "1.0", "goal": "Inspect authentic supporting data",
            "selected_kis": ["DSSAT"], "created_at": "fixture", "coupling": [],
            "scientific_choices": [], "unresolved_questions": [], "steps": [
        {"id": "download", "ki": "DSSAT", "kind": "download", "tool": None,
         "inputs": [], "outputs": ["dssat_data_bundle"], "status": "planned"},
        {"id": "inspect", "ki": "DSSAT", "kind": "check", "tool": str(tool),
         "command": [], "cwd": ".",
         "inputs": ["dssat_data_bundle"], "outputs": ["dssat_data_bundle_report"], "status": "planned"},
        {"id": "summarize", "ki": "DSSAT", "kind": "check", "tool": str(tool),
         "command": [], "cwd": ".",
         "inputs": ["dssat_data_bundle_report"], "outputs": ["final"], "status": "planned"}]}
    inventory = {"schema_version": "1.0", "items": [
        {"id": "dssat_data_bundle", "dataset_id": "dssat_data", "status": "missing", "required_by": ["DSSAT"],
         "local_paths": ["inputs/observations/dssat_data"], "needs_user": False, "agent_resolvable": True},
        {"id": "dssat_data_bundle_report", "status": "missing", "required_by": ["DSSAT"],
         "local_paths": ["outputs/diagnosis/report.json"], "output_validation": "json_report_v1",
         "needs_user": False, "agent_resolvable": True},
        {"id": "final", "status": "missing", "required_by": ["DSSAT"],
         "local_paths": ["outputs/diagnosis/final.json"], "output_validation": "json_report_v1",
         "needs_user": False, "agent_resolvable": True}]}
    return project, root, plan, inventory


def test_dssat_report_fuzzy_match_no_longer_becomes_manual_acquisition(case):
    project, root, plan, inventory = case
    report = deepcopy(inventory["items"][1])
    assert obs_access._pinned_id(report, {"dssat_data": CATALOGUE["datasets"][0]}) is None
    assert obs_access.stamp_inventory(inventory, project=project, plan=plan) == []
    assert inventory["items"][0]["dataset_id"] == "dssat_data"
    assert inventory["items"][0]["delivery"] == "manual"
    assert inventory["items"][1] == report
    assert flowgate.load().plan.validate(plan, inventory, ["DSSAT"], {"DSSAT": root},
                                        for_review=True, project=project) == []
    assert [item["id"] for item in acquire.needed(plan, inventory, project)] == ["dssat_data_bundle"]


def test_consumed_generated_intermediate_is_not_acquired_even_with_stale_metadata(case):
    project, _, plan, inventory = case
    assert obs_access.stamp_inventory(inventory, project=project, plan=plan) == []
    inventory["items"][1].update(dataset_id="dssat_data", delivery="manual")
    assert [item["id"] for item in acquire.needed(plan, inventory, project)] == ["dssat_data_bundle"]
    errors = flowgate.load().plan.data_source_errors(plan, inventory)
    assert len(errors) == 1 and "generated item 'dssat_data_bundle_report'" in errors[0]


@pytest.mark.parametrize("metadata", [
    {"dataset_id": "dssat_data"}, {"acquisition_id": "clip-id"},
    {"delivery": "manual"}, {"delivery": "served"}, {"delivery": "subset"},
])
def test_explicit_generated_acquisition_conflict_requires_revised_plan(case, metadata):
    project, root, plan, inventory = case
    inventory["items"][1].update(metadata)
    before = deepcopy(inventory)
    errors = obs_access.stamp_inventory(inventory, project=project, plan=plan)
    assert errors and "remove acquisition fields" in errors[0]
    assert inventory == before, "do not silently reinterpret an explicit source selection"
    assert any("generated item" in error for error in flowgate.load().plan.validate(
        plan, inventory, ["DSSAT"], {"DSSAT": root}, for_review=True, project=project))


def test_download_outputs_remain_external_for_acquisition_and_review(case):
    project, _, plan, inventory = case
    contract = flowgate.load().plan
    assert contract.generated_item_ids(plan) == {"dssat_data_bundle_report", "final"}
    assert obs_access.stamp_inventory(inventory, project=project, plan=plan) == []
    groups = plan_review.input_groups(plan, inventory, project)
    assert [row["id"] for row in groups["you"] if row["how"] == "manual"] == ["dssat_data_bundle"]
    assert {row["id"] for row in groups["run"] if row["how"] == "generated"} == {"dssat_data_bundle_report", "final"}


def test_explicit_download_is_not_hidden_by_another_producer_of_the_same_item(case):
    project, _, plan, inventory = case
    report = inventory["items"][1]
    report["dataset_id"] = "dssat_data"
    plan["steps"][0]["outputs"].append(report["id"])
    assert report["id"] not in flowgate.load().plan.generated_item_ids(plan)
    assert obs_access.stamp_inventory(inventory, project=project, plan=plan) == []
    assert report["delivery"] == "manual"
    assert report["id"] in {item["id"] for item in acquire.needed(plan, inventory, project)}


@pytest.mark.parametrize("same_step", [False, True])
def test_external_input_consumed_before_or_by_its_producer_keeps_exact_source(case, same_step):
    project, _, plan, inventory = case
    report = inventory["items"][1]
    report["dataset_id"] = "dssat_data"
    if same_step:
        plan["steps"][1]["inputs"].append(report["id"])
    else:
        plan["steps"][0]["inputs"].append(report["id"])
    assert report["id"] not in flowgate.load().plan.generated_item_ids(plan)
    assert obs_access.stamp_inventory(inventory, project=project, plan=plan) == []
    assert report["dataset_id"] == "dssat_data" and report["delivery"] == "manual"
    assert report["id"] in {item["id"] for item in acquire.needed(plan, inventory, project)}


def test_generated_source_notes_are_preserved_without_pinning(case):
    project, _, plan, inventory = case
    report = inventory["items"][1]
    report["chosen_source"] = "dssat_data"
    report["notes"] = "Computed from the separate acquired bundle input."
    before = deepcopy(report)
    assert obs_access.stamp_inventory(inventory, project=project, plan=plan) == []
    assert report == before


def test_legacy_stamping_without_plan_keeps_exact_external_input_matching():
    inventory = {"items": [{"id": "dssat_data", "status": "missing"}]}
    assert obs_access.stamp_inventory(inventory, catalogue=CATALOGUE) == []
    assert inventory["items"][0]["dataset_id"] == "dssat_data"


def test_real_review_card_has_one_manual_download_and_generated_report(case):
    project, root, plan, inventory = case
    flow = flowgate.load()
    assert obs_access.stamp_inventory(inventory, project=project, plan=plan) == []
    flow.plan.write_artifacts(project, plan, inventory)
    ctx = flow.states.FlowContext.load(project)
    ctx.selected_kis = ["DSSAT"]
    ctx.state = flow.states.State.PLAN_REVIEW
    ctx.save()
    fs = flowgate.FlowSession.open(project, {"DSSAT": root})
    card = plan_review.issue(project, fs, plan, inventory, "Fixture policy")
    warnings = [line for line in card["plan_review"]["blockers"] if line.startswith("manual download needed:")]
    assert len(warnings) == 1 and warnings[0].count("dssat_data") == 1
    assert "dssat_data_bundle_report" not in warnings[0]
    assert flow.approval.check(project) == "MISSING"
    assert not (project / "outputs").exists()


@pytest.mark.parametrize("bad_id", [[], {}, None, ["report"], {"id": "report"}, 12, False, ""])
def test_malformed_inventory_ids_are_validation_errors_not_parser_crashes(case, bad_id):
    project, root, plan, inventory = case
    inventory["items"][1]["id"] = bad_id
    errors = flowgate.load().plan.validate(plan, inventory, ["DSSAT"], {"DSSAT": root},
                                          for_review=True, project=project)
    assert "inventory item IDs must be nonempty, unique strings" in errors
