"""An invalid adapter destination names the precise field the agent must fix."""
import copy

import pytest

from kiss_cli import api, flowgate
from .test_flowgate import _cfg
from .test_project_data_tools import case
from .test_project_data_formats import WEATHER_CONTRACT


@pytest.fixture(autouse=True)
def keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))


@pytest.mark.parametrize("bad", ["inputs/case/soil.json", "outputs/../soil.json",
                                 "outputs\\soil.json", "${PROJECT}/outputs/soil.json"])
def test_api_rejection_identifies_inventory_output_and_index(tmp_path, bad):
    ki, project, session, plan, inventory, _ = case(tmp_path)
    inventory["items"][-1]["local_paths"] = ["outputs/first.json", bad]
    result = api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
                              ki, _cfg(project), project_mode=True, flow=session)
    assert result.startswith("PLAN NOT WRITTEN")
    assert "step 'M:read': output_id='inspection', inventory.local_paths[1]=" in result
    assert repr(bad) in result
    assert not (project / "runs/plan.json").exists()
    assert not (project / "runs/approval.json").exists()


def test_absolute_output_outside_project_still_fails_with_inventory_identity(tmp_path):
    ki, project, session, plan, inventory, _ = case(tmp_path)
    outside = str(tmp_path / "external" / "result.json")
    inventory["items"][-1]["local_paths"] = [outside]
    errors = session.write_plan(plan, inventory)
    assert any("output_id='inspection', inventory.local_paths[0]=" in error
               and repr(outside) in error for error in errors)


def test_invalid_typed_contract_names_output_and_contract_index(tmp_path):
    project_tools = flowgate.load().project_tools
    valid = copy.deepcopy(WEATHER_CONTRACT)
    invalid = {**valid, "output_id": "second_weather", "path": "inputs/weather.csv"}
    with pytest.raises(ValueError) as error:
        project_tools.output_contracts(tmp_path, [valid, invalid], [valid["output_id"], "second_weather"])
    assert "output_id='second_weather', project_data_tool.output_formats[1].path='inputs/weather.csv'" in str(error.value)
    assert "outputs/ or artifacts/" in str(error.value)


def test_valid_output_resolution_and_authority_are_unchanged(tmp_path):
    plan = flowgate.load().plan
    step = {"outputs": ["a", "b"], "project_data_tool": {}}
    inventory = {"items": [{"id": "a", "local_paths": ["outputs/a.json"]},
                            {"id": "b", "local_paths": [str(tmp_path / "artifacts/b.json")]}]}
    assert plan.project_data_output_paths(step, inventory, tmp_path) == {
        "a": {tmp_path / "outputs/a.json"}, "b": {tmp_path / "artifacts/b.json"}}
    assert not (tmp_path / "outputs").exists()


def test_location_label_does_not_expand_large_untrusted_values():
    tools = flowgate.load().project_tools
    label = tools.output_path_context("x" * 10000, "inventory.local_paths[0]", "y" * 10000)
    assert len(label) < 600
    assert "<non-string>" in tools.output_path_context("x", "path", {"nested": "not a path"})
