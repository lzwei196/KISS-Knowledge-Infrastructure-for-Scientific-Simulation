"""Discovery-like labels cannot silently select a database acquisition."""
from copy import deepcopy

import pytest

from kiss_cli import acquire, flowgate, obs_access, plan_review
from .test_generated_inventory import case


CATALOGUE = {"datasets": [
    {"id": "dssat_data", "name": "DSSAT Crop Model Data Library (80+ crops)",
     "delivery": "manual", "size": 289254747, "format": "directory"},
    {"id": "avhrr_landcover", "delivery": "manual"},
]}


@pytest.mark.parametrize("field,value", [
    ("id", "dssat_runtime_data_tree"),
    ("id", "dssat_data_bundle_report"),
    ("id", "dssat_data report"),
    ("id", "dssat_data: local"),
    ("id", "dssat_data (generated report)"),
    ("chosen_source", "AVHRR_1km_LANDCOVER_1981_1994"),
    ("chosen_source", "KI-declared DSSAT runtime data installation"),
])
def test_labels_remain_labels_even_when_one_catalogue_match_exists(field, value):
    item = {"id": "runtime", "status": "resolved", "local_paths": [],
            "chosen_source": "KI-declared managed installation", field: value}
    inv = {"items": [item]}
    before = deepcopy(inv)
    assert obs_access.stamp_inventory(inv, catalogue=CATALOGUE) == []
    assert inv == before


@pytest.mark.parametrize("selection", [
    {"dataset_id": "dssat_data"},
    {"chosen_source": "dssat_data"},
    {"chosen_source": "dssat_data (manual, 275.9 MB)"},
    {"chosen_source": "dssat_data, manual"},
    {"id": "dssat_data"},
    {"chosen_source": "existing_local", "dataset_id": "dssat_data"},
])
def test_exact_existing_selection_forms_keep_authentic_manual_facts(selection):
    item = {"id": "runtime", "status": "missing", **selection}
    assert obs_access.stamp_inventory({"items": [item]}, catalogue=CATALOGUE) == []
    assert item["dataset_id"] == "dssat_data"
    assert item["delivery"] == "manual"
    assert item["catalogue"]["size"] == 289254747
    assert item["status"] == "resolved"


@pytest.mark.parametrize("unknown", ["dssat_runtime_data_tree", "dssat_data (manual)", "missing_id"])
def test_explicit_unknown_id_cannot_fall_back_to_a_known_name(unknown):
    item = {"id": "dssat_data", "chosen_source": "dssat_data", "dataset_id": unknown}
    before = deepcopy(item)
    errors = obs_access.stamp_inventory({"items": [item]}, catalogue=CATALOGUE)
    assert len(errors) == 1 and "not in the GeoForge Database" in errors[0]
    assert item == before


@pytest.mark.parametrize("preference", ["auto", "manual"])
def test_delivery_preference_does_not_choose_a_dataset(preference):
    inv = {"delivery_preference": preference, "items": [
        {"id": "dssat_runtime_data_tree", "status": "resolved",
         "chosen_source": "KI-declared managed installation", "local_paths": []}]}
    before = deepcopy(inv)
    assert obs_access.stamp_inventory(inv, catalogue=CATALOGUE) == []
    assert inv == before


@pytest.mark.parametrize("existing", [False, True])
def test_real_runtime_inventory_review_does_not_create_manual_acquisition(case, existing):
    project, root, plan, inventory = case
    # Reproduce the fresh-project draft: the existing runtime is a consumed
    # input, not a generated artifact, and its descriptive name resembles a
    # different manual database bundle. Test real local paths as well.
    runtime = project.parent / "managed/DSSAT/Data"
    runtime.mkdir(parents=True)
    (runtime / "MODEL.ERR").write_bytes(b"unchanged runtime fixture\n")
    item = inventory["items"][0]
    item.clear()
    item.update(id="dssat_runtime_data_tree", required_by=["DSSAT"],
                status="ready" if existing else "resolved",
                local_paths=[str(runtime)] if existing else [],
                chosen_source="KI-declared managed installation", acceptable_sources=[],
                needs_user=False, agent_resolvable=True,
                rationale=f"Managed installation at {runtime}; no acquisition requested.")
    before = deepcopy(item)
    plan["steps"] = plan["steps"][1:]
    plan["steps"][0]["inputs"] = [item["id"]]
    assert obs_access.stamp_inventory(inventory, project=project, plan=plan) == []
    assert item == before
    assert acquire.needed(plan, inventory, project) == []
    groups = plan_review.input_groups(plan, inventory, project)
    assert not any(row["how"] == "manual" for row in groups["you"])
    flow = flowgate.load()
    flow.plan.write_artifacts(project, plan, inventory)
    ctx = flow.states.FlowContext.load(project)
    ctx.selected_kis = ["DSSAT"]
    ctx.state = flow.states.State.PLAN_REVIEW
    ctx.save()
    fs = flowgate.FlowSession.open(project, {"DSSAT": root})
    card = plan_review.issue(project, fs, plan, inventory, "Fixture policy")
    assert not any(line.startswith("manual download needed:")
                   for line in card["plan_review"]["blockers"])
    assert flow.approval.check(project) == "MISSING"
    assert not (project / "outputs").exists()
    assert (runtime / "MODEL.ERR").read_bytes() == b"unchanged runtime fixture\n"


def test_generated_exact_catalogue_id_still_cannot_request_acquisition(case):
    project, _, plan, inventory = case
    item = inventory["items"][1]
    item["dataset_id"] = "dssat_data"
    before = deepcopy(inventory)
    errors = obs_access.stamp_inventory(inventory, project=project, plan=plan)
    assert errors and "generated item" in errors[0]
    assert inventory == before
