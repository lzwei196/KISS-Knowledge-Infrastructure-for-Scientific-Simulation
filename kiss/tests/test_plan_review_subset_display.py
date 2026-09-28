"""A selected project clip must not be displayed as its whole catalogue product.

Uses the real estimate/stamp/issued-review path with a deterministic fake estimate
client. No provider, remote job, file download or scientific run is allowed.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from kiss_cli import acquire, flowgate, obs_access, obs_subset, plan_review, project_status


@pytest.fixture
def clip_review(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    catalogue = {"datasets": [
        {"id": "cmfd", "name": "CMFD", "delivery": "manual", "size": 242_000_000_000,
         "start_date": "1979-01-01", "end_date": "2024-12-31", "bbox": [70, 15, 140, 55],
         "subsettable": True},
        {"id": "other", "name": "Other forcing", "delivery": "served", "size": 1_000_000,
         "start_date": "1990-01-01", "end_date": "2020-12-31", "bbox": [-180, -90, 180, 90]},
    ]}
    monkeypatch.setattr(obs_access, "load_catalogue", lambda: copy.deepcopy(catalogue))

    def forbidden(*_args, **_kwargs):
        pytest.fail("display projection must not contact a server, approve, download, or execute")

    monkeypatch.setattr(obs_access, "Client", forbidden)
    monkeypatch.setattr(obs_access, "refresh_catalogue", forbidden)
    monkeypatch.setattr(obs_subset, "approve", forbidden)
    monkeypatch.setattr(obs_subset, "download", forbidden)
    monkeypatch.setattr(acquire, "run", forbidden)
    project = tmp_path / "project"
    (project / "runs").mkdir(parents=True)
    ki = project / "models/M/ki"
    (ki / "tools").mkdir(parents=True)
    (ki / "dag.yaml").write_text("outputs: []\n")
    (ki / "SKILL.md").write_text("# Fixture model\nUse tools/run.py.\n")
    tool = ki / "tools/run.py"
    tool.write_text("raise AssertionError('must not run')\n")
    fs = flowgate.FlowSession.open(project, {"M": ki})
    monkeypatch.setattr(fs.flow.approval, "approve", forbidden)
    fs.move("task_received")
    fs.move("kis_resolved", {"selected_kis": ["M"]})
    request = {"dataset_id": "cmfd", "bbox": [115, 37, 117, 39], "variables": ["prec"],
               "start": "2003-01-01", "end": "2003-01-02"}
    estimate = {"subsettable": True, "estimated_output_bytes": 4096, "over_output_cap": False,
                "coverage_complete": True, "missing": [], "transformations": [], "n_parts": 1,
                "snapped_output_bounds": [115, 37, 117, 39], "variables": ["prec"],
                "processing_version": "fixture/1", "source_version": "v1"}
    client = SimpleNamespace(_json=lambda *a, **k: copy.deepcopy(estimate))
    state = obs_subset.estimate(project, request, client=client)
    item = {"id": "forcing", "required_by": ["M"], "acceptable_sources": ["cmfd", "other"],
            "local_paths": [], "dataset_id": "cmfd", "chosen_source": "cmfd", "acquisition_id": state["id"]}
    obs_subset.stamp_item(project, item)
    plan = {"schema_version": "1.0", "goal": "Prepare fixture forcing", "created_at": "fixture",
            "selected_kis": ["M"], "unresolved_questions": [],
            "scientific_choices": [{"id": "data:forcing", "kind": "data_source", "item": "forcing",
                                    "options": ["cmfd", "other"], "picked": "cmfd", "high_impact": True}],
            "steps": [{"id": "M:run", "ki": "M", "kind": "run", "tool": str(tool),
                       "inputs": ["forcing"], "outputs": ["q"], "status": "planned"}]}
    inventory = {"schema_version": "1.0", "items": [item]}
    assert fs.write_plan(plan, inventory) == []
    return SimpleNamespace(project=project, fs=fs, request=request, state=state, plan=plan,
                           inventory=inventory, item=item, catalogue=catalogue)


def test_issued_review_matches_selected_subset_and_project_status(clip_review):
    env = clip_review
    before = copy.deepcopy(env.inventory)
    env.fs.move("plan_written", {"plan_valid": True})
    card = plan_review.issue(env.project, env.fs, env.plan, env.inventory, "fixture")
    selected = card["plan_review"]["data_choices"][0]["options"][0]
    assert selected["delivery"] == "subset"
    assert selected["size"] == 4096 and selected["size_label"] == "4 KB"
    assert selected["period"] == ["2003-01-01", "2003-01-02"]
    assert selected["bbox"] == [115, 37, 117, 39]
    grouped = card["plan_review"]["data"]["fetch"][0]
    assert grouped["how"] == "clip" and grouped["size"] == selected["size"]
    status = project_status.snapshot(env.project)["plan_data"]["items"][0]
    assert status["how"] == "clip" and status["action"] == "acquire_subset"
    assert status["size"] == selected["size"]
    assert not card["plan_review"]["data"]["you"]
    assert env.inventory == before
    assert not (env.project / "runs/approval.json").exists()
    assert not obs_subset.read(env.project, env.state["id"]).get("job_id")


def test_selected_clip_does_not_relabel_other_candidate(clip_review):
    env = clip_review
    rows = plan_review._data_choices(env.plan, env.inventory)[0]["options"]
    other = rows[1]
    assert other["dataset_id"] == "other" and other["delivery"] == "served"
    assert other["size"] == 1_000_000
    assert other["period"] == ["1990-01-01", "2020-12-31"]
    assert other["bbox"] == [-180, -90, 180, 90]


def test_same_dataset_for_another_item_does_not_borrow_the_clip(clip_review):
    env = clip_review
    env.plan["scientific_choices"].append({
        "id": "data:other_period", "kind": "data_source", "item": "other_period",
        "options": ["cmfd"], "picked": "cmfd",
    })
    env.inventory["items"].append({"id": "other_period", "dataset_id": "cmfd", "delivery": "manual"})
    rows = plan_review._data_choices(env.plan, env.inventory)
    assert rows[0]["options"][0]["delivery"] == "subset"
    unestimated = rows[1]["options"][0]
    assert unestimated["delivery"] == "manual" and unestimated["size"] == 242_000_000_000
    assert unestimated["period"] == ["1979-01-01", "2024-12-31"]


@pytest.mark.parametrize("change", ["no_estimate", "different_dataset", "not_subset"])
def test_capability_or_unselected_estimate_is_not_a_project_subset(clip_review, change):
    env = clip_review
    if change == "no_estimate":
        env.item.pop("acquisition_id")
    elif change == "different_dataset":
        env.item["dataset_id"] = "other"
    else:
        env.item["delivery"] = "manual"
    option = plan_review._data_choices(env.plan, env.inventory)[0]["options"][0]
    assert option["delivery"] == "manual" and option["size"] == 242_000_000_000


def test_unknown_clip_scope_does_not_fall_back_to_whole_product_facts(clip_review):
    env = clip_review
    env.item["catalogue"] = {"name": "cmfd", "size": None}
    env.item["estimate_summary"] = {"bytes": None}
    env.item["requirements"] = {}
    option = plan_review._data_choices(env.plan, env.inventory)[0]["options"][0]
    assert option["delivery"] == "subset"
    assert option["size"] is None and option["size_label"] == ""
    assert option["period"] is None and option["bbox"] is None


@pytest.mark.parametrize("field,value", [
    ("bbox", [110, 30, 112, 32]), ("start", "2010-01-01"), ("end", "2010-01-02"),
])
def test_changed_scope_is_rejected_by_existing_submission_boundary(clip_review, field, value):
    env = clip_review
    proposed = copy.deepcopy(env.inventory)
    proposed["items"][0]["requirements"][field] = value
    before = (env.project / "runs/data-inventory.json").read_bytes()
    errors = env.fs.write_plan(env.plan, proposed)
    assert any(f"Acquisition {field} differs" in error for error in errors)
    assert (env.project / "runs/data-inventory.json").read_bytes() == before
    assert not (env.project / "runs/plan-review.json").exists()


def test_projection_keeps_stamped_version_until_host_restamps_inventory(clip_review):
    env = clip_review
    estimate = copy.deepcopy(env.state["estimate"])
    estimate.update(source_version="v2", estimated_output_bytes=8192)
    client = SimpleNamespace(_json=lambda *a, **k: copy.deepcopy(estimate))
    obs_subset.refresh_estimate(env.project, env.state["id"], client=client)
    # A display read does not silently adopt another estimate/version from the cache.
    option = plan_review._data_choices(env.plan, env.inventory)[0]["options"][0]
    assert option["size"] == 4096
    assert env.item["estimate_summary"]["source_version"] == "v1"
    # The existing submission/stamping boundary supplies the updated facts.
    assert env.fs.write_plan(env.plan, env.inventory) == []
    option = plan_review._data_choices(env.plan, env.inventory)[0]["options"][0]
    assert option["size"] == 8192
    assert env.item["estimate_summary"]["source_version"] == "v2"
