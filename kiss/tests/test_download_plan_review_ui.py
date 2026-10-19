"""Host acquisition is executable without a model tool; model steps are not."""
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("zh", [False, True])
def test_download_without_tool_is_host_acquisition_but_missing_model_tool_stays_blocked(zh):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for shipped renderer")
    source = (Path(__file__).parents[1] / "kiss_cli/web/app.html").read_text(encoding="utf-8")
    begin = source.index("function renderPlanReview(r,rawMessage){")
    renderer = source[begin:source.index("function closeActionPicker", begin)]
    program = r'''
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
const chineseUI=()=>input.zh,howLabels=()=>({}),itemNote=()=>'';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
''' + renderer + "process.stdout.write(renderPlanReview(input.review,''));"
    review = {"steps": [
        {"id": "archive", "kind": "download", "tool": None},
        {"id": "model", "kind": "model_run", "tool": None},
        {"id": "prepare", "kind": "prepare", "tool": None},
        {"id": "bound_model", "kind": "model_run", "tool": "tools/run.py"},
    ]}
    rendered = subprocess.run([node, "-e", program],
        input=json.dumps({"review": review, "zh": zh}), capture_output=True,
        text=True, encoding="utf-8", check=True, timeout=10).stdout
    steps = dict(re.findall(r"<li><b>([^<]+)</b>(.*?)</li>", rendered, re.S))
    missing = "缺少工具，无法执行" if zh else "no tool — cannot execute"
    acquisition = "由 GeoForge 下载并记录回执" if zh else "downloaded by GeoForge with a receipt"
    assert acquisition in steps["archive"] and missing not in steps["archive"]
    assert missing in steps["model"] and missing in steps["prepare"]
    assert "<code>tools/run.py</code>" in steps["bound_model"]
    assert missing not in steps["bound_model"]
