"""Review the exact fallback source; never execute its code or HTML."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from kiss_cli import flowgate, plan_review, project_data_tools


def card(tmp_path, source="raise AssertionError('review must not execute')\n", mutate=False):
    flow = flowgate.load()
    result = project_data_tools.write(tmp_path, "M", "reader", source, "reader")
    step = {"id": "inspect", "ki": "M", "kind": "prepare", "tool": result["tool"],
            "project_data_tool": result["project_data_tool"], "inputs": [],
            "outputs": ["outputs/observations.csv"]}
    if mutate:
        Path(result["tool"]).write_text("raise AssertionError('changed')\n")
    fs = SimpleNamespace(project=tmp_path, database_access_mode="off")
    fs.flow = flow
    return plan_review._card(flow, fs, {"goal": "Inspect actual data", "selected_kis": ["M"],
                            "steps": [step]}, {"items": []}, "fixture")


def test_review_shows_source_and_bound_invocation_without_execution(tmp_path):
    shown = card(tmp_path)["plan_review"]["steps"][0]["project_data_tool"]
    assert shown["source_path"].startswith("project_tools/")
    assert shown["source_preview"] == "raise AssertionError('review must not execute')\n"
    assert not shown["source_truncated"] and not shown["errors"]
    assert shown["purpose"] == "reader" and len(shown["source_sha256"]) == 64
    assert shown["arguments"] == [] and shown["cwd"] == "." and shown["timeout_seconds"] == 120


def test_changed_source_is_not_shown_as_approved_code(tmp_path):
    shown = card(tmp_path, mutate=True)["plan_review"]["steps"][0]["project_data_tool"]
    assert shown["errors"] and "source_preview" not in shown


def test_source_preview_is_explicitly_bounded(tmp_path):
    shown = card(tmp_path, "# comment\n" * 3000)["plan_review"]["steps"][0]["project_data_tool"]
    assert shown["source_truncated"] and len(shown["source_preview"]) == 24000


@pytest.mark.parametrize("zh", [False, True])
def test_actual_review_renderer_escapes_source_and_arguments(tmp_path, zh):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for shipped renderer")
    review = card(tmp_path)["plan_review"]
    binding = review["steps"][0]["project_data_tool"]
    attack = '<img src=x onerror="throw Error(1)">'
    binding.update(source_preview=attack, arguments=[attack], source_truncated=True)
    html = (Path(__file__).parents[1] / "kiss_cli/web/app.html").read_text(encoding="utf-8")
    begin = html.index("function renderPlanReview(r,rawMessage){")
    function = html[begin:html.index("function closeActionPicker", begin)]
    program = r'''
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
const chineseUI=()=>input.zh,howLabels=()=>({}),itemNote=()=>'';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
''' + function + "process.stdout.write(renderPlanReview(input.review,''));"
    rendered = subprocess.run([node, "-e", program], input=json.dumps({"review": review, "zh": zh}),
                              capture_output=True, text=True, encoding="utf-8", check=True, timeout=10).stdout
    assert "<img" not in rendered and "&lt;img" in rendered
    assert ("项目专用数据工具" if zh else "Project data tool") in rendered
    assert ("代码预览已截断" if zh else "Code preview is truncated") in rendered
    assert binding["source_sha256"] in rendered
