"""Execute the actual plan-card JavaScript with synthetic, untrusted estimates."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node required for shipped JavaScript")
PAGE = Path(__file__).resolve().parents[1] / "kiss_cli/web/app.html"


def render(items, zh=False):
    html = PAGE.read_text(encoding="utf-8")
    start = html.index("function preparationEstimateCards(items,zh){")
    source = html[start:html.index("async function refreshPreparationEstimates", start)]
    program = r"""
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
""" + source + "process.stdout.write(preparationEstimateCards(input.items,input.zh));"
    return subprocess.run([NODE, "-e", program],
                          input=json.dumps({"items": items, "zh": zh}),
                          capture_output=True, text=True, encoding="utf-8", check=True,
                          timeout=10).stdout


@pytest.mark.parametrize("zh", [False, True])
def test_estimate_is_never_presented_as_prepared_input_or_model_success(zh):
    output = render([{
        "status": "estimate_available",
        "request": {"model": "shaw", "source": "cmfd", "mode": "daily",
                    "lat": 47.43, "lon": 126.97, "start": "2003-10-01", "end": "2004-05-31"},
        "server_estimate": {"source_cadence": "3-hourly", "transforms": ["daily aggregation"],
                            "outputs": [{"role": "weather", "name": "site.wea"}]},
    }], zh)
    assert "2003-10-01" in output and "2004-05-31" in output
    assert "3-hourly" in output and "daily aggregation" in output
    assert ("尚未准备" if zh else "preparation not run") in output
    assert ("尚未运行模型" if zh else "no model run") in output
    assert "<button" not in output and 'class="statuspill ok"' not in output


def test_blockers_and_html_are_displayed_as_text_without_actions():
    attack = '<img src=x onerror="steal()">'
    output = render([{"status": "blocked", "request": {"model": attack},
                      "server_estimate": {"transforms": [attack], "outputs": [{"name": attack}]},
                      "blockers": ["SOIL_PARAM_COMPLETE.txt not built", attack], "message": attack}])
    assert "SOIL_PARAM_COMPLETE.txt not built" in output
    assert "Prerequisites missing" in output
    assert "<img" not in output and "&lt;img" in output
    assert "<button" not in output and "data-subset-action" not in output


def test_empty_or_unknown_estimate_does_not_imply_success():
    assert "No server preparation plans checked" in render([])
    assert "Needs review" in render([{"status": "unexpected"}])
