"""Execute shipped database status rendering against local host-status fixtures."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node required for actual status JavaScript")
PAGE = Path(__file__).resolve().parents[1] / "kiss_cli" / "web" / "app.html"


def _render_status(status, *, zh=False):
    page = PAGE.read_text(encoding="utf-8")
    functions = page[page.index("function databaseStatusText(st){"):page.index("// ── database browser:")]
    panel_start = page.index('  drawDatabaseStatus("#obs-status").then(')
    panel_refresh = page[panel_start:page.index("\n  if(obsSearch)", panel_start)]
    program = r"""
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
const elements=new Map();
const $=selector=>{if(!elements.has(selector))elements.set(selector,{textContent:'',className:'',style:{}});return elements.get(selector);};
const chineseUI=()=>input.zh;
const fetch=async()=>({json:async()=>input.status});
""" + functions + r"""
(async()=>{
  await drawDatabaseStatus('#s-obs-status');
""" + panel_refresh + r"""
  await new Promise(resolve=>setImmediate(resolve));
  process.stdout.write(JSON.stringify({text:$('#s-obs-status').textContent,
    pill:$('#s-obs-pill').textContent,className:$('#s-obs-pill').className,
    panelPill:$('#obs-pill').textContent,panelClass:$('#obs-pill').className}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([NODE, "-e", program], input=json.dumps({"status": status, "zh": zh}),
                            capture_output=True, text=True, check=True, timeout=10)
    return json.loads(result.stdout)


def _status(**overrides):
    return {"configured": True, "mode": "direct", "effective_mode": "direct",
            "catalogue_ok": True, "records": 3, "served": 2, "stale": False, "error": "",
            "api_tool": "search_catalogue", "cli_command": "geoforge-db", **overrides}


@pytest.mark.parametrize("zh", [False, True])
def test_rejected_token_with_old_cache_is_unavailable_not_connected(zh):
    result = _render_status(_status(effective_mode="off", catalogue_ok=False, error="Token rejected"), zh=zh)
    assert result["pill"] == ("不可用" if zh else "Unavailable")
    assert result["panelPill"] == result["pill"]
    assert result["className"] == "statuspill warn"
    assert result["panelClass"] == "statuspill warn"
    assert "Token rejected" in result["text"]
    assert ("No token" if not zh else "未配置 Token") not in result["text"]
    assert ("Agent access:" if not zh else "Agent 检索方式") not in result["text"]


@pytest.mark.parametrize("overrides,pill,panel_pill,phrase,css", [
    ({"mode": "off", "effective_mode": "off"}, "Off", "Off", "Disabled:", "warn"),
    ({"configured": False, "effective_mode": "off"}, "Not configured", "Not set up", "No token:", "warn"),
    ({"stale": True, "error": "offline"}, "Connected", "Stale", "stale: offline", "warn"),
    ({}, "Connected", "Local copy", "Agent access:", "ok"),
])
def test_existing_disabled_missing_offline_and_activated_rendering(overrides, pill, panel_pill, phrase, css):
    result = _render_status(_status(**overrides))
    assert result["pill"] == pill and phrase in result["text"]
    assert result["className"] == "statuspill " + css
    assert result["panelPill"] == panel_pill and result["panelClass"] == "statuspill " + css
