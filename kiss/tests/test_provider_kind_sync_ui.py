"""A started chat keeps showing the provider it was started with.

On a fresh Desktop start the chat is drawn before the deferred provider
detection finishes. The provider kind must be adopted once the list arrives;
otherwise a started API chat shows a local CLI, the send path posts that CLI as
an update, and the server (correctly) refuses to switch a locked chat.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


NODE = shutil.which("node")
PAGE = Path(__file__).resolve().parents[1] / "kiss_cli" / "web" / "app.html"


def _function(page: str, name: str) -> str:
    start = page.index(f"function {name}(")
    end = page.index("\nfunction ", start + 1)
    return page[start:end]


@pytest.mark.skipif(NODE is None, reason="Node is required")
def test_started_api_chat_adopts_its_kind_after_late_provider_detection():
    page = PAGE.read_text(encoding="utf-8")
    code = _function(page, "kindOf") + "\n" + _function(page, "drawProviders")
    script = """
const elements={};
function el(id){return elements[id]||(elements[id]={id,innerHTML:"",value:"",textContent:"",
  insertAdjacentHTML(){},remove(){},onclick:null});}
const $=sel=>sel==="#kindgap"||sel==="#gatebanner"||sel==="#quick-recheck"?null:el(sel);
const document={querySelectorAll(){return [];}};
const esc=s=>String(s);const providerOptionLabel=p=>p.label;const providerIssue=()=>"";
function setControls(){} function drawLLM(){} function refreshProviders(){}
let KIND="cli", KIND_SYNCED_FOR;
let CUR={id:"s1",provider:"api:deepseek"};
let PROV={providers:[],any_usable:false};
""" + code + """
drawProviders();                         // chat drawn before detection finished
const before={kind:KIND,synced:KIND_SYNCED_FOR};
PROV={providers:[
  {name:"cli:claude",kind:"cli",usable:true,installed:true,label:"Claude Code"},
  {name:"api:deepseek",kind:"api",usable:true,installed:true,label:"DeepSeek (API)"}],
  any_usable:true,default:"cli:claude"};
drawProviders();                         // detection arrives
console.log(JSON.stringify({before,kind:KIND,value:$("#prov").value}));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                            encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout.strip().splitlines()[-1])
    assert state["before"] == {"kind": "cli"}      # unknown yet: not marked synced
    assert state["kind"] == "api" and state["value"] == "api:deepseek"


@pytest.mark.skipif(NODE is None, reason="Node is required")
def test_a_user_switch_is_not_overruled_on_later_redraws():
    # The original reason for syncing once per session must still hold.
    page = PAGE.read_text(encoding="utf-8")
    code = _function(page, "kindOf") + "\n" + _function(page, "drawProviders")
    script = """
const elements={};
function el(id){return elements[id]||(elements[id]={id,innerHTML:"",value:"",textContent:"",
  insertAdjacentHTML(){},remove(){},onclick:null});}
const $=sel=>sel==="#kindgap"||sel==="#gatebanner"||sel==="#quick-recheck"?null:el(sel);
const document={querySelectorAll(){return [];}};
const esc=s=>String(s);const providerOptionLabel=p=>p.label;const providerIssue=()=>"";
function setControls(){} function drawLLM(){} function refreshProviders(){}
let KIND="cli", KIND_SYNCED_FOR;
let CUR={id:"s2",provider:"cli:claude"};
let PROV={providers:[
  {name:"cli:claude",kind:"cli",usable:true,installed:true,label:"Claude Code"},
  {name:"api:deepseek",kind:"api",usable:true,installed:true,label:"DeepSeek (API)"}],any_usable:true};
""" + code + """
drawProviders();
KIND="api";                              // the user clicks API in a new chat
drawProviders();
console.log(JSON.stringify({kind:KIND,value:$("#prov").value}));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                            encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout.strip().splitlines()[-1])
    assert state == {"kind": "api", "value": "api:deepseek"}
