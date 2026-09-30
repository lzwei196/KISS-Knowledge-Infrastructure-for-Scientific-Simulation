"""Execute the shipped picker functions/handlers in Node with a tiny DOM stub.

This checks interaction logic, not browser layout: no app server, live provider,
network connection, or additional JavaScript package is needed.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node required for actual picker JavaScript")
PAGE = Path(__file__).resolve().parents[1] / "kiss_cli" / "web" / "app.html"


def _request(**overrides):
    return {
        "id": "planning-question", "kind": "choice", "status": "waiting",
        "title": "Which dataset?", "allow_note": True, "picked": "source-0",
        "options": [{"id": f"source-{index}", "label": f"Source {index}",
                     "response": f"Use source {index}"} for index in range(12)],
        **overrides,
    }


def _picker(request, *, operation="inspect", selection=None, note=""):
    page = PAGE.read_text(encoding="utf-8")
    functions = page[page.index("function closeActionPicker(){"):page.index("async function maybeShowAction(")]
    handlers = page[page.index('$("#action-later").onclick='):page.index('$("#openproject").onclick=')]
    program = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
function classes() {
  const values = new Set();
  return {add:v=>values.add(v), remove:v=>values.delete(v), contains:v=>values.has(v),
    toggle:(v,on)=>{if(on)values.add(v);else values.delete(v);}};
}
function element() {
  return {textContent:'',value:'',style:{},hidden:false,classList:classes(),buttons:[],
    set innerHTML(value) {
      this.html=value;
      this.buttons=Array.from(value.matchAll(/data-index="(\d+)"/g), m=>({
        dataset:{index:m[1]},classList:classes()}));
    },
    get innerHTML(){return this.html||'';},
    querySelectorAll(){return this.buttons;}};
}
const elements=new Map();
const $=selector=>{if(!elements.has(selector))elements.set(selector,element());return elements.get(selector);};
const chineseUI=()=>false, esc=value=>String(value), renderPlanReview=()=>'<div>review</div>';
const document={querySelectorAll:()=>[]};
let ACTION_REQUEST=null, ACTION_SESSION=null, ACTION_INDEX=-1;
const CUR={id:'test-session'}, PENDING_ACTIONS=new Map(), DRAFTS=new Map(), sent=[];
const send=async()=>sent.push({text:$('#msg').value, action:PENDING_ACTIONS.get(CUR.id)||null});
""" + functions + "\n" + handlers + r"""
(async()=>{
  const originalCount=input.request.options.length;
  const options=questionOptions(input.request);
  const displayed=showActionPicker(input.request,CUR.id);
  const before={index:ACTION_INDEX, selected:$('#action-options').buttons.filter(b=>b.classList.contains('selected')).length,
    buttons:$('#action-options').buttons.length};
  if(input.selection!==null){
    const index=input.selection==='custom'?options.findIndex(o=>o.id==='__custom_answer__'):input.selection;
    if(index>=0)$('#action-options').buttons[index].onclick();
  }
  $('#action-note').value=input.note;
  if(input.operation==='continue')await $('#action-continue').onclick();
  if(input.operation==='ask')await $('#action-ask').onclick();
  process.stdout.write(JSON.stringify({displayed,originalCount,afterOriginalCount:input.request.options.length,
    ids:options.map(o=>o.id),before,sent,error:$('#action-error').textContent,
    open:$('#actionpick').classList.contains('open')}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    # Node always writes UTF-8; the locale default (GBK on Chinese Windows) cannot decode it.
    result = subprocess.run(
        [NODE, "-e", program],
        input=json.dumps({"request": request, "operation": operation, "selection": selection, "note": note}),
        capture_output=True, text=True, encoding="utf-8", check=True, timeout=10,
    )
    return json.loads(result.stdout)


def test_picker_preserves_more_than_eight_choices_without_default_selection():
    observed = _picker(_request())
    assert observed["ids"] == [f"source-{index}" for index in range(12)] + ["__custom_answer__"]
    assert observed["originalCount"] == observed["afterOriginalCount"] == 12
    assert observed["before"] == {"index": -1, "selected": 0, "buttons": 13}
    assert observed["displayed"] and observed["sent"] == []


def test_final_review_keeps_every_input_in_expandable_groups():
    page = PAGE.read_text(encoding="utf-8")
    functions = page[page.index("function howLabels(zh){"):page.index("function closeActionPicker(){")]
    program = ("const chineseUI=()=>false,esc=x=>String(x);\n" + functions +
               "\nconst rows=Array.from({length:12},(_,i)=>({id:'input-'+i,how:'provide'}));"
               "process.stdout.write(renderPlanReview({data:{total:24,fetch:rows,you:rows,run:[]}},''));")
    html = subprocess.run([NODE, "-e", program], capture_output=True, text=True,
                          encoding="utf-8", check=True, timeout=10).stdout
    assert html.count("Show remaining 4 inputs") == 2
    assert html.count("<code>input-11</code>") == 2
    assert html.count("<code>input-0</code>") == 2


def test_continue_without_selection_does_not_send_or_accept_a_default():
    observed = _picker(_request(), operation="continue")
    assert observed["sent"] == [] and observed["open"]
    assert "Choose one option first" in observed["error"]


def test_custom_choice_requires_nonempty_note_before_sending():
    observed = _picker(_request(), operation="continue", selection="custom", note="  ")
    assert observed["sent"] == [] and observed["open"]
    assert "Enter your answer or file location" in observed["error"]


@pytest.mark.parametrize("answer", ["0.25", "inputs/uploads/my soil.csv"])
def test_custom_choice_sends_explicit_answer_not_approval(answer):
    observed = _picker(_request(), operation="continue", selection="custom", note=answer)
    assert not observed["open"] and len(observed["sent"]) == 1
    sent = observed["sent"][0]
    assert sent["action"] == {"request_id": "planning-question", "option_id": "__custom_answer__", "note": answer}
    assert answer in sent["text"]


def test_last_candidate_is_selectable_and_sends_its_original_response():
    observed = _picker(_request(), operation="continue", selection=11)
    assert observed["sent"][0]["action"]["option_id"] == "source-11"
    assert "Use source 11" in observed["sent"][0]["text"]


@pytest.mark.parametrize("override", [
    {"kind": "permission"}, {"kind": "download"}, {"kind": "login"},
    {"allow_note": False}, {"plan_review": {"goal": "test"}},
    {"id": "flow-approve-test"}, {"id": "flow-acquisition-blocked"},
    {"id": "flow-manual-download"},
])
def test_protected_cards_have_no_custom_answer_option(override):
    observed = _picker(_request(**override))
    assert "__custom_answer__" not in observed["ids"]


@pytest.mark.parametrize("options", [[], _request()["options"]])
def test_ask_about_choices_sends_only_clarification_prose(options):
    observed = _picker(_request(options=options), operation="ask")
    assert len(observed["sent"]) == 1
    assert observed["sent"][0]["action"] is None
    assert "cannot decide" in observed["sent"][0]["text"]
    assert "then ask me again" in observed["sent"][0]["text"]
