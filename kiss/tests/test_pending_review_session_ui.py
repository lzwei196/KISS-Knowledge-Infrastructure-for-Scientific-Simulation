"""Delayed pending-review responses must stay with their selected idle chat."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node required for shipped pending-review JavaScript")
PAGE = Path(__file__).resolve().parents[1] / "kiss_cli/web/app.html"

RUNNER = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const page = fs.readFileSync(process.argv[1], 'utf8');
const source = page.slice(page.indexOf('async function maybeShowAction('), page.indexOf('let PROJECT_PICK_RESOLVE='));
const request = {id:'review-1', status:'waiting', created_at:'t', options:[{id:'approve'}]};
let release, reads = 0, shown = [];
const gate = new Promise(resolve => {release = resolve;});
const context = {
  CUR: {id:'original'}, busy:false, SEEN_ACTIONS:new Set(),
  sessionBusy:() => context.busy,
  questionOptions:r => r.options,
  showActionPicker(r,id) {shown.push({id, selected:context.CUR?.id}); return true;},
  async fetch(url) {
    const first = ++reads === 1;
    if(first && input.barrier === 'fetch') await gate;
    return {ok:true, async json() {
      if(first && input.barrier === 'body') await gate;
      return {request};
    }};
  },
};
vm.createContext(context); vm.runInContext(source, context);
(async()=>{
  const pending = context.maybeShowAction('original');
  await new Promise(resolve => setImmediate(resolve));
  if(input.transition === 'switch') context.CUR = {id:'other'};
  if(input.transition === 'close') context.CUR = null;
  if(input.transition === 'busy') context.busy = true;
  release(); await pending;
  const afterDelayed = {shown:shown.slice(), seen:[...context.SEEN_ACTIONS]};
  // Reopening the original idle chat must still offer the ignored request.
  context.CUR = {id:'original'}; context.busy = false;
  await context.maybeShowAction('original');
  await context.maybeShowAction('original');
  process.stdout.write(JSON.stringify({afterDelayed, shown, seen:[...context.SEEN_ACTIONS], reads}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


@pytest.mark.parametrize("barrier", ["fetch", "body"])
@pytest.mark.parametrize("transition", ["switch", "close", "busy"])
def test_stale_pending_response_does_not_render_or_consume_seen_key(barrier, transition):
    result = run_probe(barrier, transition)
    assert result["afterDelayed"] == {"shown": [], "seen": []}
    assert result["shown"] == [{"id": "original", "selected": "original"}]
    assert result["seen"] == ["original:review-1:t"]


@pytest.mark.parametrize("barrier", ["fetch", "body"])
def test_same_idle_chat_still_opens_once_and_keeps_deduplication(barrier):
    result = run_probe(barrier, "same")
    expected = [{"id": "original", "selected": "original"}]
    assert result["afterDelayed"] == {"shown": expected, "seen": ["original:review-1:t"]}
    assert result["shown"] == expected
    assert result["seen"] == ["original:review-1:t"]


def run_probe(barrier, transition):
    process = subprocess.run([NODE, "-e", RUNNER, str(PAGE)],
                             input=json.dumps({"barrier": barrier, "transition": transition}),
                             capture_output=True, text=True, encoding="utf-8", check=True, timeout=10)
    return json.loads(process.stdout)
