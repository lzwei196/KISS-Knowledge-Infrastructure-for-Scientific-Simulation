"""Data readers in a selection do not become model runs or coupling partners."""
from pathlib import Path

import pytest

from kiss_cli import flowgate, prompt
from kiss_cli.catalog import KI

REPO = Path(__file__).resolve().parents[2]
FLOW = flowgate.load()


@pytest.mark.parametrize("model,reader", [
    ("CRHM", "HYDAT_Observations"), ("SHAW", "Agrometeo_Quebec_Observations")])
def test_mixed_draft_exposes_reader_workflow_but_cannot_execute_without_bindings(model, reader, tmp_path):
    roots = {model: REPO/"models"/model, reader: REPO/"kiss/data_kis"/reader}
    full, plan, inventory = FLOW.plan.derive(
        [model,reader], {}, "Model and observed data", FLOW.plan.DataRoots.bundled(
            REPO/"ki_tools_common/ki_tools_common/flow/data"), roots)
    reader_plan = next(item for item in full["plans"] if item["model"] == reader)
    assert plan["summary"]["models"] == 1 and plan["summary"]["data_readers"] == 1
    assert "error" not in reader_plan
    assert reader_plan["package_role"] == "data_reader"
    stages = reader_plan["ki_stages"]
    assert stages[0]["tools"] == [str((roots[reader]/"tools/read_observations.py").resolve())]
    assert "start_date" in stages[0]["required_bindings"] and "end_date" in stages[0]["required_bindings"]
    reader_steps = [step for step in plan["steps"] if step["ki"] == reader]
    assert len(reader_steps) == 1
    step = reader_steps[0]
    assert step["kind"] == "prepare" and step["tool"] is None
    assert step["inputs"] == [] and step["outputs"] == []  # never manufacture inputs or parameters
    assert "source/station/dates" in step["notes"] and "read_observations.py" in step["notes"]
    assert plan["coupling"] == []
    errors = FLOW.plan.validate(plan,inventory,[model,reader],roots,for_review=True,project=tmp_path)
    assert any(step["id"] in error and "has no tool" in error for error in errors)
    assert not any("coupling" in error for error in errors)


@pytest.mark.parametrize("execute", [False, True])
def test_mixed_prompt_distinguishes_model_from_data_reader(execute):
    kis = [KI("CRHM",REPO/"models/CRHM"),
           KI("HYDAT_Observations",REPO/"kiss/data_kis/HYDAT_Observations")]
    text = prompt.compose_multi(kis,execute=execute)
    assert "Scientific models: CRHM. Data readers: HYDAT_Observations." in text
    assert "2 models through" not in text and "[MULTI-MODEL RULES]" not in text
    assert "comparison table" not in text
    assert "does not create a model-coupling requirement" in text
    assert "not model execution or scientific validation" in text
    assert ("approved current phase" if execute else "no reader or model execution") in text


def test_ordinary_model_dag_steps_and_multi_model_rules_remain_unchanged(tmp_path):
    (tmp_path/"dag.yaml").write_text(
        "processes:\n  - id: simulate\n    inputs: [forcing]\n    outputs: [discharge]\n",encoding="utf-8")
    assert FLOW.plan._dag_steps("MODEL",tmp_path) == [{
        "id":"MODEL:simulate","ki":"MODEL","tool":None,"kind":"process",
        "inputs":["forcing"],"outputs":["discharge"],"status":"planned"}]
    kis = [KI("CRHM",REPO/"models/CRHM"), KI("SHAW",REPO/"models/SHAW")]
    text = prompt.compose_multi(kis,execute=True)
    assert "2 models through" in text and "[MULTI-MODEL RULES]" in text
    assert "Run EVERY selected model" in text and "comparison table" in text


def test_unrelated_workflow_does_not_gain_data_reader_draft_treatment(tmp_path):
    (tmp_path/"knowledge_infrastructure.yaml").write_text(
        "package:\n  kind: task_workflow\n  role: other\n",encoding="utf-8")
    assert FLOW.plan._dag_steps("OTHER",tmp_path)[0]["kind"] == "run"
