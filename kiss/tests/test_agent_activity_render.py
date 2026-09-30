"""Exercise the live-chat activity UI with the shipped JavaScript, without a provider."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


PAGE = Path(__file__).parents[1] / "kiss_cli" / "web" / "app.html"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is required")
RUNNER = r"""
const fs=require('node:fs'),vm=require('node:vm');
const page=fs.readFileSync(process.argv[1],'utf8');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const elements=new Map();
function element(key){
  if(!elements.has(key))elements.set(key,{
    innerHTML:'',textContent:'',dataset:{},className:'',
    classList:{toggle(){},remove(){}},
    querySelector(selector){return elements.get(selector)||null;},
    insertBefore(child){elements.set('.liveactivity',child);},
  });
  return elements.get(key);
}
const bubble=element('.bubble');bubble.innerHTML='<p>I will read the KI and look for data.</p>';
const turn=element('.turn');
let rewrites=0;
function cardElement(){
  let html='',nodes=new Map();
  return {className:'',dataset:{},
    get innerHTML(){return html;},set innerHTML(value){html=value;rewrites++;nodes=new Map();},
    querySelector(selector){if(!nodes.has(selector))nodes.set(selector,{textContent:'',open:false});return nodes.get(selector);},
    remove(){elements.delete('.liveactivity');},
  };
}
const flight={provider:'cli:claude',started:1000,lastHeartbeat:601000,
  raw:'I will read the KI and look for data.',...input.flight};
const context={console,CUR:{id:'session'},INFLIGHT:new Map([['session',flight]]),
  Date:{now:()=>601000},chineseUI:()=>Boolean(input.zh),
  providerDisplay:()=> 'Claude Code',elapsedTime:()=> '10m 0s',
  durationLabel:n=>`${Math.floor(n)}s`,workLabel:value=>value,
  runStageLabel:value=>value,sizeLabel:value=>`${value} bytes`,
  esc:value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),
  liveBubble:()=>bubble,$:element,
  document:{querySelector:()=>turn,createElement:cardElement},
};
vm.createContext(context);
vm.runInContext(page.slice(page.indexOf('function agentLiveState(flight){'),page.indexOf('async function refreshAgentStatus')),context);
context.updateActivityUI();
let disclosureRetained;
if(input.update){
  const card=elements.get('.liveactivity'),summary=card.querySelector('summary');
  card.querySelector('details').open=true;
  flight.agentStatus=input.update;
  context.updateActivityUI();
  disclosureRetained=summary===card.querySelector('summary')&&card.querySelector('details').open;
}
if(input.finished){context.INFLIGHT.delete('session');context.updateLiveActivity('session');}
process.stdout.write(JSON.stringify({
  card:elements.get('.liveactivity')?.innerHTML||'',bubble:bubble.innerHTML,
  title:element('#activitytitle').textContent,detail:element('#activitytext').textContent,
  rewrites,disclosureRetained,updatedTitle:elements.get('.liveactivity')?.querySelector('.liveactivity-title').textContent,
}));
"""


def render(**kwargs):
    # Node always writes UTF-8; the locale default (GBK on Chinese Windows) cannot decode it.
    result = subprocess.run([NODE, "-e", RUNNER, str(PAGE)],
                            input=json.dumps(kwargs), capture_output=True,
                            text=True, encoding="utf-8", check=True, timeout=10)
    return json.loads(result.stdout)


def test_activity_remains_visible_in_chat_after_agent_has_written_intro():
    result = render(flight={"agentStatus": {
        "process_alive": True, "event_silence_seconds": 5,
        "activity_kind": "database", "activity": "Bash",
        "activity_state": "tool_running",
        "activity_detail": "geoforge-db soil attribute table --limit 10",
    }})
    assert "GeoForge Database" in result["card"]
    assert "soil attribute table" in result["card"]


def test_completed_tool_is_not_described_as_running_or_still_searching():
    result = render(flight={"agentStatus": {
        "process_alive": True, "work_silence_seconds": 5,
        "activity_state": "tool_finished", "activity_kind": "database",
        "last_activity_name": "Bash", "last_activity_detail": "geoforge-db soil table",
    }})
    assert "Tool returned; waiting for the agent" in result["card"]
    assert "geoforge-db soil table" in result["card"]
    assert "Searching GeoForge Database" not in result["card"]
    assert "not scientific validation" in result["card"]


def test_transport_events_do_not_hide_old_work_evidence():
    result = render(flight={"agentStatus": {
        "process_alive": True, "work_silence_seconds": 520,
        "event_silence_seconds": 0, "activity_state": "tool_running",
        "activity_kind": "database", "activity_detail": "geoforge-db soil table",
    }})
    assert "No new work evidence" in result["card"]
    assert "520s" in result["card"]


def test_failed_status_poll_does_not_leave_frozen_fresh_work_age():
    result = render(flight={"agentStatusAt": 1000, "agentStatus": {
        "process_alive": True, "work_silence_seconds": 1,
    }})
    assert "No new work evidence" in result["card"]
    assert "601s" in result["card"]


def test_first_work_event_is_not_invented_from_startup_or_heartbeat():
    result = render(flight={"agentStatus": {
        "process_alive": True, "work_silence_seconds": 30,
        "work_observed": False, "activity_state": "unknown",
    }})
    assert "No confirmed tool or output event yet" in result["card"]
    assert "Last work event" not in result["card"]


@pytest.mark.parametrize("lifecycle", [{}, {"activity_state": "unknown"}])
def test_legacy_or_unknown_lifecycle_is_only_last_observed_action(lifecycle):
    result = render(flight={"agentStatus": {
        "process_alive": True, "event_silence_seconds": 1,
        "activity_kind": "database", "activity_detail": "geoforge-db soil table", **lifecycle,
    }})
    assert "current execution is unconfirmed" in result["card"]
    assert "last observed action" in result["card"]
    assert "Searching GeoForge Database" not in result["card"]


def test_tool_duration_is_not_the_whole_turn_and_detail_is_escaped():
    result = render(flight={"agentStatus": {
        "process_alive": True, "work_silence_seconds": 1,
        "activity_state": "tool_running", "activity_elapsed_seconds": 9,
        "activity_kind": "database", "activity_detail": "<script>alert(1)</script>",
    }})
    assert "Turn elapsed: 10m 0s · Current tool elapsed: 9s" in result["card"]
    assert "<script>" not in result["card"]
    assert "&lt;script&gt;" in result["card"]


def test_completed_turn_removes_live_card_without_replacing_chat_text():
    result = render(finished=True)
    assert result["card"] == ""
    assert "I will read the KI" in result["bubble"]


def test_status_updates_preserve_disclosure_node_and_only_announce_the_title():
    result = render(flight={"agentStatus": {
        "process_alive": True, "work_silence_seconds": 1,
        "activity_state": "tool_running", "activity_detail": "geoforge-db soil",
    }}, update={"process_alive": True, "work_silence_seconds": 5,
               "activity_state": "tool_finished", "last_activity_detail": "geoforge-db soil"})
    assert result["disclosureRetained"]
    assert result["rewrites"] == 1
    assert "Tool returned" in result["updatedTitle"]
    assert '<b class="liveactivity-title" role="status"' in result["card"]
    assert result["card"].count('aria-live="polite"') == 1


def test_chinese_card_explains_wait_after_tool_returns():
    result = render(zh=True, flight={"agentStatus": {
        "process_alive": True, "work_silence_seconds": 20,
        "activity_state": "tool_finished",
        "last_activity_detail": "runs/data-inventory.json",
    }})
    assert "工具已返回，等待 Agent 下一步" in result["card"]
    assert "本回合已用时" in result["card"]
    assert "I will read the KI" in result["bubble"]


def test_long_silent_action_is_explicit_in_front_of_chat():
    result = render(flight={"agentStatus": {
        "process_alive": True, "event_silence_seconds": 520,
        "activity_kind": "database", "activity": "Bash",
        "activity_detail": "geoforge-db soil attribute table --limit 10",
    }})
    assert "520s" in result["card"]
    assert "No new work evidence" in result["card"]
    assert "soil attribute table" in result["card"]
