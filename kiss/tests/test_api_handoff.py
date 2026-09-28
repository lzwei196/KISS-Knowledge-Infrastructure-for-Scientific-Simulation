"""Step 1 of FLOW-TARGET-2026-09-17: focused database tools, prose-only nudge, transport retry."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from kiss_cli import api, flowgate

PROV = api.ApiProvider(name="demo", label="Demo API", wire="openai",
                       base_url="https://example.invalid", env_key="DEMO_API_KEY",
                       models={"demo": "demo"}, default_model="demo")


def _flow(state, project=Path("/nowhere")):
    return SimpleNamespace(state=SimpleNamespace(value=state), provider_succeeded=False,
                           api_tools=lambda: frozenset(), check_tool=lambda name: None,
                           project=project)


def _env(tmp_path):
    return SimpleNamespace(root=tmp_path), SimpleNamespace(root=tmp_path)


def _run(turns, flow=None, execute=None):
    with mock.patch.dict(api.os.environ, {"DEMO_API_KEY": "test"}), \
         mock.patch.object(api, "_openai_turn", side_effect=turns) as turn, \
         mock.patch.object(api, "execute_tool", side_effect=execute or (lambda *a, **k: "ok")), \
         mock.patch.object(api, "tool_schemas", return_value=[]):
        out = "".join(api.run(PROV, SimpleNamespace(), SimpleNamespace(), "sys", "task",
                              project_mode=True, flow=flow))
    return out, turn.call_count


def _prose(text):
    return (text, [], {"role": "assistant", "content": text})


def _call(name, args, text=""):
    return (text, [("c1", name, args)], {"role": "assistant", "content": text, "tool_calls": []})


@pytest.mark.parametrize("state", ["RESOLVING_KIS", "PLANNING", "REPLAN_REQUIRED"])
def test_prose_only_turn_is_nudged_once_then_ends(state):
    flow = _flow(state)
    out, calls = _run([_prose("I will now write the plan."), _prose("Still just talking.")], flow)
    assert calls == 2
    assert "asking Demo API to finish it" in out
    assert flow.provider_succeeded is True      # the turn ended; flowrun.after reports the gap


def test_nudge_is_skipped_after_a_real_handoff():
    flow = _flow("PLANNING")
    turns = [_call("write_plan", {"plan": {}, "data_inventory": {}}), _prose("Done, waiting for approval.")]
    out, calls = _run(turns, flow, execute=lambda *a, **k: "Plan files written: runs/plan.json")
    assert calls == 2 and "asking Demo API" not in out


def test_partial_write_plan_does_not_count_as_handoff():
    flow = _flow("PLANNING")
    turns = [_call("write_plan", {"plan": {}}), _prose("part one sent"), _prose("...")]
    out, calls = _run(turns, flow, execute=lambda *a, **k: "Plan part stored; send data_inventory next")
    assert calls == 3 and "asking Demo API" in out


def test_intake_report_ready_is_a_handoff():
    flow = _flow("RESOLVING_KIS")
    turns = [_call("report_project_progress", {"status": "working", "summary": "s", "selected_kis": ["VIC"],
                                               "intake": {"understanding": "x", "ready_for_planning": True, "missing": []}}),
             _prose("Understood; moving to planning.")]
    out, calls = _run(turns, flow)
    assert calls == 2 and "asking Demo API" not in out


def test_intake_question_in_prose_is_nudged_to_a_card():
    # Live DeepSeek 2026-09-17: reported not-ready with one missing question, then asked it in prose.
    flow = _flow("RESOLVING_KIS")
    turns = [_call("report_project_progress", {"status": "waiting_for_user", "summary": "s", "selected_kis": ["DSSAT"],
                                               "intake": {"understanding": "x", "ready_for_planning": False, "missing": ["spring or winter wheat?"]}}),
             _prose("One question for you: spring or winter wheat?"),
             _call("request_user_action", {"title": "Wheat type", "options": []})]
    out, calls = _run(turns, flow)
    assert calls == 3 and out.count("asking Demo API") == 1 and "waiting for your answer" in out


def test_no_nudge_outside_handoff_states():
    flow = _flow("EXECUTING")
    out, calls = _run([_prose("Run finished.")], flow)
    assert calls == 1 and "asking Demo API" not in out


def test_transport_failure_is_retried_once():
    boom = api.ToolError("provider stream interrupted: TimeoutError: timed out")
    out, calls = _run([boom, _prose("recovered")], _flow("EXECUTING"))
    assert calls == 2 and "retrying once" in out and "recovered" in out
    boom2 = api.ToolError("provider stream interrupted: TimeoutError: timed out")
    out, calls = _run([boom, boom2, _prose("never")], _flow("EXECUTING"))
    assert calls == 2 and "Demo API failed" in out


def test_focused_tools_map_onto_the_legacy_handler(monkeypatch, tmp_path):
    ki, cfg = _env(tmp_path)
    seen = []

    def fake_search(**kw):
        seen.append(kw)
        return {"ok": True}
    from kiss_cli import obs_access, obs_subset
    monkeypatch.setattr(obs_access, "search_catalogue", fake_search)
    flow = _flow("PLANNING", tmp_path)
    api.execute_tool("search_catalogue", {"query": "bengbu", "parent_id": "cmfd_china_daily_010", "bbox": "1,2,3,4"},
                     ki, cfg, project_mode=True, flow=flow)
    api.execute_tool("describe_dataset", {"dataset_id": "cmfd_china_daily_010"},
                     ki, cfg, project_mode=True, flow=flow)
    assert seen[0]["q"] == "bengbu" and seen[0]["resolve_dataset_id"] == "cmfd_china_daily_010"
    assert seen[1]["describe_dataset_id"] == "cmfd_china_daily_010"
    estimates = []
    monkeypatch.setattr(obs_subset, "estimate", lambda project, body: estimates.append(body) or {"id": "x"})
    api.execute_tool("estimate_clip", {"dataset_id": "d", "bbox": [1, 2, 3, 4], "variables": ["prec"], "extra": 1},
                     ki, cfg, project_mode=True, flow=flow)
    assert estimates == [{"dataset_id": "d", "bbox": [1, 2, 3, 4], "variables": ["prec"]}]


def test_intake_estimates_are_capped(monkeypatch, tmp_path):
    from kiss_cli import obs_subset
    ki, cfg = _env(tmp_path)
    monkeypatch.setattr(obs_subset, "estimate", lambda project, body: {"id": "x"})
    flow = _flow("RESOLVING_KIS", tmp_path)
    for _ in range(api.INTAKE_ESTIMATE_CAP):
        api.execute_tool("estimate_clip", {"dataset_id": "d", "bbox": [1, 2, 3, 4]},
                         ki, cfg, project_mode=True, flow=flow)
    with pytest.raises(api.ToolError, match="at most"):
        api.execute_tool("estimate_clip", {"dataset_id": "d", "bbox": [1, 2, 3, 4]},
                         ki, cfg, project_mode=True, flow=flow)


def test_database_tools_follow_access_mode(tmp_path):
    fs = flowgate.FlowSession.open(tmp_path, {}, database_access_mode="direct")
    assert {"search_catalogue", "describe_dataset", "estimate_clip"} <= fs.api_tools()
    fs = flowgate.FlowSession.open(tmp_path, {}, database_access_mode="off")
    assert not ({"search_catalogue", "describe_dataset", "estimate_clip", "search_observation_data"} & fs.api_tools())


def test_request_cards_are_never_readable_by_agents(tmp_path):
    from kiss_cli import setup as setup_flow
    ki, cfg = _env(tmp_path)
    project = tmp_path / "project"; project.mkdir()
    (project / "note.txt").write_text("fine")
    setup_flow.request_user(project, {"kind": "download", "title": "Get data", "message": "code: s3cr3t",
                                      "url": "https://pan.baidu.com/s/x", "expected_path": str(project / "inputs/x")})
    setup_flow.resume(project, "done")            # archives the card as setup-request-<ts>.json
    setup_flow.request_user(project, {"kind": "download", "title": "Again", "message": "code: s3cr3t"})
    flow = _flow("EXECUTING", project)
    listing = api.execute_tool("list_project_files", {}, ki, cfg, project_mode=True, flow=flow,
                               setup_context={"project_root": str(project)})
    assert "note.txt" in listing and "setup-request" not in listing
    with pytest.raises(api.ToolError, match="request card"):
        api.execute_tool("read_project_file", {"path": "setup-request.json"}, ki, cfg, project_mode=True,
                         flow=flow, setup_context={"project_root": str(project)})


def test_chat_handler_never_reads_a_local_before_assigning_it():
    """Review B-2: `waiting.get(...)` in _stream_session_chat read a local that is only assigned
    200 lines later (UnboundLocalError), crashing every message sent while a no-options card
    (the manual download card) was waiting."""
    import ast
    from kiss_cli import gui
    tree = ast.parse(Path(gui.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_stream_session_chat")
    first_store, first_load = {}, {}
    comprehension_vars = {n.id for c in ast.walk(fn) if isinstance(c, ast.comprehension)
                          for n in ast.walk(c.target) if isinstance(n, ast.Name)}
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id not in comprehension_vars:
            table = first_store if isinstance(node.ctx, ast.Store) else first_load
            table.setdefault(node.id, node.lineno)
            if isinstance(node.ctx, ast.Store):
                table[node.id] = min(table[node.id], node.lineno)
            else:
                table[node.id] = min(table[node.id], node.lineno)
    params = {a.arg for a in fn.args.args}
    bad = {name: (first_load[name], first_store[name]) for name in first_store
           if name in first_load and name not in params and first_load[name] < first_store[name]}
    assert not bad, f"locals read before their first assignment: {bad}"


def test_a_question_card_ends_the_planning_turn():
    """Montreal 2026-09-18: the agent asked a question and wrote the plan in the same turn."""
    flow = _flow("PLANNING")
    turns = [_call("request_user_action", {"title": "Site?", "options": []}),
             _call("write_plan", {"plan": {}, "data_inventory": {}}),
             _prose("done")]
    out, calls = _run(turns, flow, execute=lambda name, *a, **k: "Plan files written" if name == "write_plan" else "shown")
    assert calls == 1 and "waiting for your answer" in out and flow.provider_succeeded is True
