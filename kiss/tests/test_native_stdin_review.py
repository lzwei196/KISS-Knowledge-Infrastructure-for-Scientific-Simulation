"""Literal native-model answers reach approval unchanged, never execution here."""
import html as html_escape
import json
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from kiss_cli import api, flowgate, plan_review, prompt
from kiss_cli.catalog import KI
from .test_flowrun import _ki
from .test_plan_review_lifecycle import review_project, _click, _draft


def _review(tmp_path, text="Trial.303.inp\r\n\n"):
    step = {"id": "run", "ki": "Fixture", "kind": "model_run", "tool": "fixture.exe",
            "command": ["bin/fixture.exe"], "cwd": "outputs/trial",
            "stdin": {"text": text}, "inputs": [], "outputs": []}
    flow = flowgate.load()
    fs = SimpleNamespace(project=tmp_path, database_access_mode="off", flow=flow)
    plan = {"goal": "Review model answers", "selected_kis": ["Fixture"], "steps": [step]}
    return plan_review._card(flow, fs, plan, {"items": []}, "fixture")["plan_review"], step


def _render(review, zh=False):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for shipped renderer")
    source = (Path(__file__).parents[1] / "kiss_cli/web/app.html").read_text(encoding="utf-8")
    begin = source.index("function renderPlanReview(r,rawMessage){")
    function = source[begin:source.index("function closeActionPicker", begin)]
    program = r'''
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
const chineseUI=()=>input.zh,howLabels=()=>({}),itemNote=()=>'';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
''' + function + "process.stdout.write(renderPlanReview(input.review,''));"
    return subprocess.run([node, "-e", program], input=json.dumps({"review": review, "zh": zh}),
                          capture_output=True, text=True, encoding="utf-8", check=True, timeout=10).stdout


def test_card_preserves_exact_answers_and_independent_invocation(tmp_path):
    review, step = _review(tmp_path)
    shown = review["steps"][0]
    for key in ("stdin", "command", "cwd"):
        assert shown[key] == step[key]
    step["stdin"]["text"] = "changed"
    step["command"].append("changed")
    assert shown["stdin"]["text"] == "Trial.303.inp\r\n\n"
    assert shown["command"] == ["bin/fixture.exe"]


@pytest.mark.parametrize("zh", [False, True])
@pytest.mark.parametrize("text", ["Trial.303.inp\r\n\n", "0\n1", "", "1\n" * 2048])
def test_renderer_displays_every_exact_character_including_no_final_newline(tmp_path, zh, text):
    review, _ = _review(tmp_path, text)
    rendered = _render(review, zh)
    previews = re.findall(r"<pre\b[^>]*>(.*?)</pre>", rendered, re.S)
    assert json.dumps(text) in [html_escape.unescape(value) for value in previews]
    assert ("模型交互输入" if zh else "Model prompt answers") in rendered
    assert ("不会额外添加换行" if zh else "adds no newline") in rendered
    assert "\\r" in rendered and "\\n" in rendered
    assert "outputs/trial" in rendered and "bin/fixture.exe" in rendered


@pytest.mark.parametrize("zh", [False, True])
def test_renderer_escapes_untrusted_answers_command_and_cwd(tmp_path, zh):
    attack = '<img src=x onerror="throw Error(1)">'
    review, _ = _review(tmp_path, attack)
    shown = review["steps"][0]
    shown.update(command=[attack], cwd=attack)
    rendered = _render(review, zh)
    assert "<img" not in rendered
    assert rendered.count("&lt;img") == 3


def test_renderer_does_not_invent_stdin_for_ordinary_steps(tmp_path):
    review, _ = _review(tmp_path)
    review["steps"][0].pop("stdin")
    assert "Model prompt answers" not in _render(review)


@pytest.mark.parametrize("execute", [False, True])
@pytest.mark.parametrize("count", [1, 2])
def test_shared_provider_prompt_explains_bounded_approved_input(tmp_path, execute, count):
    kis = [KI(source.name, source.root)
           for source in [_ki(tmp_path, f"Fixture{i}") for i in range(count)]]
    text = prompt.compose_multi(kis, execute=execute, headless=True, strict=True)
    assert text.count("[DECLARED NATIVE MODEL PROMPTS]") == 1
    assert 'stdin: {"text":"case.inp\\n\\n"}' in text
    for required in ("4096 UTF-8 bytes", "relative\nto that cwd", "input inventory",
                     "no final newline", "per-call override", "revised plan and approval",
                     "Planning still cannot run the model"):
        assert required in text


def test_api_advertises_plan_input_without_tool_call_override(tmp_path):
    tools = {tool["name"]: tool for tool in api.tool_schemas(KI("Fixture", tmp_path), project_mode=True)}
    assert "stdin:{text:string}" in tools["write_plan"]["description"]
    run = tools["run_ki_tool"]
    assert "declared native model binary" in run["description"]
    assert "never pass stdin as a tool-call argument" in run["description"]
    assert "stdin" not in run["input_schema"]["properties"]
    step = tools["write_plan"]["input_schema"]["properties"]["plan"]["properties"]["steps"]["items"]
    assert "stdin" not in step["required"]
    assert set(step["required"]).issubset(step["properties"])
    assert "never stdin" in step["properties"]["command"]["description"]
    assert step["properties"]["stdin"]["required"] == ["text"]
    assert step["properties"]["stdin"]["additionalProperties"] is False
    assert "Exact UTF-8" in step["properties"]["stdin"]["description"]


def test_directly_authored_invalid_stdin_is_shown_and_cannot_be_approved(review_project):
    env = review_project
    _draft(env)
    flow = flowgate.load()
    plan, inventory = flow.plan.read_artifacts(env.project)
    # A CLI can write plan files directly. The review and final approval must
    # enforce Desktop's extra contract even if write_plan() was never called.
    plan["steps"][0]["stdin"] = {"text": "yes\n"}
    flow.plan.write_artifacts(env.project, plan, inventory)
    fs = flowgate.FlowSession.open(env.project, {"M": env.ki.root}, database_access_mode="off")
    card = plan_review.issue(env.project, fs, plan, inventory, "fixture")
    assert any("declared native model binary" in error for error in card["plan_review"]["not_ready"])
    result = _click(env, card)
    assert "declared native model binary" in result.replan_reason
    assert not (env.project / "runs/approval.json").exists()
