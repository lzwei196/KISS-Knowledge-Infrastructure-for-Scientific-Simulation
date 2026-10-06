"""An explicit Pan/manual choice survives planning and acquisition unchanged.

All records, credentials and HTTP responses are synthetic. No network, Pan login,
real catalogue or scientific model is used.
"""
from __future__ import annotations

import copy
import json

import pytest

from kiss_cli import acquire, flowgate, obs_access, obs_subset, plan_review, settings
from kiss_cli import setup as setup_flow
from .test_acquisition_mixed_delivery import _approve
from .test_flowgate import _ki, _plan, _session
from .test_obs_access import Opener, Response, json_response
from .test_obs_subset import EST


MANUAL = {"id": "regional_cmfd", "delivery": "manual", "size": 2_000_000_000,
          "bbox": [115, 37, 117, 39], "variables": ["prec", "temp"]}
PARENT = {"id": "cmfd_china_daily_010", "delivery": "manual", "size": 240_000_000_000}
CHILD = {"id": "cmfd_china_daily_010__prec_2003", "parent_id": PARENT["id"],
         "delivery": "manual", "variable": "prec", "year": 2003, "time_step": "daily"}
SERVED = {"id": "small_gauge", "delivery": "served", "size": 100}
CATALOGUE = {"ok": True, "datasets": [MANUAL, PARENT, CHILD, SERVED]}


@pytest.fixture(autouse=True)
def _isolated_host(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))


def _item(dataset=MANUAL["id"], **extra):
    return {"id": "forcing", "status": "missing", "dataset_id": dataset,
            "requirements": {"bbox": [115, 37, 117, 39], "variable": "prec",
                             "start": "2003-01-01", "end": "2003-12-31"}, **extra}


def _forbid_discovery(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("manual or invalid preference must not request a server clip")
    monkeypatch.setattr(obs_subset, "estimate", forbidden)
    monkeypatch.setattr(obs_subset, "refresh_estimate", forbidden)
    monkeypatch.setattr(obs_subset, "approve", forbidden)
    monkeypatch.setattr(obs_subset, "stamp_item", forbidden)


@pytest.mark.parametrize("scope", ["inventory", "item"])
@pytest.mark.parametrize("record", [MANUAL, CHILD])
def test_manual_preference_preserves_real_delivery_and_scientific_scope(
        tmp_path, monkeypatch, scope, record):
    _forbid_discovery(monkeypatch)
    item = _item(record["id"])
    inventory = {"items": [item]}
    (inventory if scope == "inventory" else item)["delivery_preference"] = "manual"
    requirements = copy.deepcopy(item["requirements"])

    assert obs_access.stamp_inventory(inventory, catalogue=CATALOGUE, project=tmp_path) == []
    assert item["delivery"] == "manual" and item["dataset_id"] == record["id"]
    assert item["requirements"] == requirements
    assert item["status"] == "resolved" and not item.get("acquisition_id")
    assert inventory.get("delivery_preference") == ("manual" if scope == "inventory" else None)
    # Inheritance is not copied into an item override; changing the default remains possible.
    assert item.get("delivery_preference") == ("manual" if scope == "item" else None)


def test_explicit_item_override_manual_wins_over_inventory_auto(tmp_path, monkeypatch):
    _forbid_discovery(monkeypatch)
    inventory = {"delivery_preference": "auto", "items": [_item(delivery_preference="manual")]}
    assert obs_access.stamp_inventory(inventory, catalogue=CATALOGUE, project=tmp_path) == []
    assert inventory["items"][0]["delivery"] == "manual"


@pytest.mark.parametrize("preference", [None, "auto"])
def test_default_auto_still_estimates_and_selects_a_clip(tmp_path, monkeypatch, preference):
    item = _item()
    inventory = {"items": [item]}
    if preference is not None:
        # An explicit per-item auto overrides the inherited manual preference.
        inventory["delivery_preference"] = "manual"
        item["delivery_preference"] = preference
    opener = Opener(json_response(EST))
    client = obs_access.Client(opener=opener, token_getter=lambda: "synthetic-token")
    monkeypatch.setattr(obs_access, "Client", lambda: client)

    assert obs_access.stamp_inventory(inventory, catalogue=CATALOGUE, project=tmp_path) == []
    assert item["delivery"] == "subset" and item["acquisition_id"]
    assert len(opener.requests) == 1
    assert opener.requests[0][0].full_url.endswith("/subsets/estimate")
    assert json.loads(opener.requests[0][0].data)["dataset_id"] == MANUAL["id"]


@pytest.mark.parametrize("with_project", [False, True])
def test_manual_whole_product_parent_requires_exact_children_not_clip(
        tmp_path, monkeypatch, with_project):
    _forbid_discovery(monkeypatch)
    inventory = {"delivery_preference": "manual", "items": [_item(PARENT["id"])]}
    before = copy.deepcopy(inventory)
    errors = obs_access.stamp_inventory(inventory, catalogue=CATALOGUE,
                                        project=tmp_path if with_project else None)
    assert len(errors) == 1
    assert "whole-product parent" in errors[0] and "exact delivery child IDs" in errors[0]
    assert inventory == before


@pytest.mark.parametrize("scope", ["inventory", "item"])
@pytest.mark.parametrize("value", [None, "pan", "Manual", "", False, [], {}])
def test_invalid_preference_stops_entire_inventory_before_discovery(
        tmp_path, monkeypatch, scope, value):
    _forbid_discovery(monkeypatch)
    monkeypatch.setattr(obs_access, "refresh_catalogue", lambda: pytest.fail("no catalogue refresh"))
    first, second = _item(), _item(id="later")
    inventory = {"items": [first, second]}
    (inventory if scope == "inventory" else second)["delivery_preference"] = value
    before = copy.deepcopy(inventory)
    errors = obs_access.stamp_inventory(inventory, project=tmp_path)
    assert errors and "delivery_preference must be" in errors[0]
    assert "delivery_preference must be" in obs_subset.refresh_inventory(tmp_path, inventory)["inventory"][0]
    assert obs_subset.approve_inventory(tmp_path, inventory)[0]["ok"] is False
    assert inventory == before


@pytest.mark.parametrize("selection", [{"delivery": "subset"}, {"acquisition_id": "a" * 32}])
def test_manual_conflict_blocks_stamp_refresh_and_job_approval(tmp_path, monkeypatch, selection):
    _forbid_discovery(monkeypatch)
    monkeypatch.setattr(obs_access, "refresh_catalogue", lambda: pytest.fail("no catalogue refresh"))
    inventory = {"delivery_preference": "manual", "items": [_item(**selection)]}
    errors = obs_access.stamp_inventory(inventory, project=tmp_path)
    assert errors and "conflicts" in errors[0]
    assert "conflicts" in obs_subset.refresh_inventory(tmp_path, inventory)["inventory"][0]
    result = obs_subset.approve_inventory(tmp_path, inventory)
    assert result and result[0]["ok"] is False and "conflicts" in result[0]["error"]


@pytest.mark.parametrize("record", [SERVED, {"id": "unknown_delivery"},
                                    {**CHILD, "delivery": "served"}])
def test_manual_is_not_invented_for_a_served_or_unknown_record(tmp_path, monkeypatch, record):
    _forbid_discovery(monkeypatch)
    inventory = {"delivery_preference": "manual", "items": [_item(record["id"])]}
    before = copy.deepcopy(inventory)
    errors = obs_access.stamp_inventory(inventory, catalogue={"datasets": [record]}, project=tmp_path)
    assert errors and "manual delivery is unavailable or unconfirmed" in errors[0]
    assert inventory == before


def test_direct_prefer_clip_honors_manual_and_rejects_invalid_preferences(tmp_path):
    client = obs_access.Client(opener=Opener(), token_getter=lambda: "synthetic-token")
    item = _item(delivery="manual", delivery_preference="manual")
    assert obs_subset.prefer_clip(tmp_path, item, MANUAL, client=client) is False
    for change in ({"delivery_preference": "pan"}, {"acquisition_id": "a" * 32}):
        with pytest.raises(ValueError):
            obs_subset.prefer_clip(tmp_path, {**item, **change}, MANUAL, client=client)
    assert not client._provided_opener.requests


class _UnreadBinary(Response):
    def read(self, *args, **kwargs):
        pytest.fail("manual-only delivery must not read a binary payload")


def test_manual_only_transport_refuses_binary_before_reading_or_writing_it(tmp_path):
    response = _UnreadBinary(b"must not be consumed", {"Content-Type": "application/octet-stream"})
    opener = Opener(response)
    client = obs_access.Client(opener=opener, token_getter=lambda: "synthetic-token")
    with pytest.raises(obs_access.ObsAccessError) as failure:
        client.download(MANUAL["id"], tmp_path, manual_only=True)
    assert failure.value.code == "manual_delivery_unavailable"
    assert len(opener.requests) == 1 and response.closed
    assert not list(tmp_path.rglob("*.part")) and not (tmp_path / "inputs").exists()


@pytest.mark.parametrize("payload", [{"served": True, "download_url": "https://example.invalid/file"}, [], {}])
def test_manual_only_transport_refuses_served_or_invalid_json(tmp_path, payload):
    opener = Opener(json_response(payload))
    client = obs_access.Client(opener=opener, token_getter=lambda: "synthetic-token")
    with pytest.raises(obs_access.ObsAccessError) as failure:
        client.download(MANUAL["id"], tmp_path, manual_only=True)
    assert failure.value.code == "manual_delivery_unavailable"
    assert not (tmp_path / "inputs").exists()


def _manual_plan(tmp_path, monkeypatch, preference_at):
    ki = _ki(tmp_path)
    project, flow = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": [ki.name]})])
    plan, inventory = _plan(ki)
    plan["scientific_choices"] = []
    item = inventory["items"][0]
    item.update(dataset_id=MANUAL["id"], chosen_source=MANUAL["id"],
                acceptable_sources=[MANUAL["id"]], delivery="manual")
    (inventory if preference_at == "inventory" else item)["delivery_preference"] = "manual"
    monkeypatch.setattr(settings, "database_access_mode", lambda: "direct")
    monkeypatch.setattr(obs_access, "token_state", lambda: "configured")
    monkeypatch.setattr(obs_access, "load_catalogue", lambda: CATALOGUE)
    monkeypatch.setattr(obs_access, "refresh_catalogue", lambda **_k: CATALOGUE)
    monkeypatch.setattr(obs_access, "resolved_records", lambda: [])
    assert flow.write_plan(plan, inventory) == []
    flow.move("plan_written", {"plan_valid": True})
    card = plan_review.issue(project, flow, plan, inventory, "Synthetic manual-preference test")
    return project, flow, ki, card


@pytest.mark.parametrize("scope", ["inventory", "item"])
def test_approved_manual_preference_reaches_transport_and_keeps_handoff(
        tmp_path, monkeypatch, scope):
    project, flow, ki, card = _manual_plan(tmp_path, monkeypatch, scope)
    calls = []
    class ManualOnlyClient:
        def download(self, dataset_id, destination_project, *, manual_only=False):
            calls.append((dataset_id, manual_only))
            assert manual_only is True
            return {"served": False, "name": "Synthetic forcing",
                    "baidu_url": "https://example.invalid/private-share", "baidu_pwd": "private-code",
                    "path_in_share": "prec/prec_2003.nc", "size": 20,
                    "destination": str(destination_project / "inputs" / "observations" / dataset_id)}
    monkeypatch.setattr(obs_access, "Client", ManualOnlyClient)
    _approve(project, ki, card)

    assert calls == [(MANUAL["id"], True)]
    state = acquire.status(project)
    assert state["status"] == "waiting" and state["items"]["forcing"]["status"] == "waiting"
    assert "private-share" not in json.dumps(state) and "private-code" not in json.dumps(state)
    request = setup_flow.request(project)
    assert request["id"] == acquire.MANUAL_REQUEST_ID
    assert request["rows"][0]["path_in_share"] == "prec/prec_2003.nc"
    assert not state["items"]["forcing"].get("receipt")
    _, saved = flow.flow.plan.read_artifacts(project)
    assert (saved if scope == "inventory" else saved["items"][0])["delivery_preference"] == "manual"


def test_approved_pan_choice_fails_closed_if_server_changes_to_binary(tmp_path, monkeypatch):
    project, _, ki, card = _manual_plan(tmp_path, monkeypatch, "inventory")
    response = _UnreadBinary(b"must not be consumed", {"Content-Type": "application/zip"})
    opener = Opener(response)
    client = obs_access.Client(opener=opener, token_getter=lambda: "synthetic-token")
    monkeypatch.setattr(obs_access, "Client", lambda: client)
    _approve(project, ki, card)

    status = acquire.status(project)
    assert status["status"] == "failed"
    item = status["items"]["forcing"]
    assert item["status"] == "failed" and "manual delivery" in item["error"]
    assert not item.get("receipt") and len(opener.requests) == 1
    assert not list(project.rglob("*.part")) and not (project / "inputs").exists()


def test_planning_guidance_records_preference_without_changing_science():
    contracts = flowgate.load().contracts
    hint = obs_access.study_hint_block([MANUAL], "regional cmfd")
    for text in (obs_access.DATA_DISCOVERY_RULES, contracts._PLAN_SCHEMA_NOTE, hint):
        assert "delivery_preference" in text and "manual" in text
    assert "Manual delivery needs no clip estimate" in obs_access.DATA_DISCOVERY_RULES
    assert "total bytes" in contracts._PLAN_SCHEMA_NOTE
