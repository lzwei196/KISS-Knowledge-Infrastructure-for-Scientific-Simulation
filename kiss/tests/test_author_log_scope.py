"""Current repair output is not input evidence; completed history stays readable."""
from copy import deepcopy
import json
from pathlib import Path
import os
import threading

import pytest

from kiss_cli import api, ki_review_agents as review, paths, providers
from kiss_cli.catalog import KI
from .test_ki_review_agents import bundle, draft, author_report, cli_help

PAGE_HEADER = "[GeoForge text page] "


def page_text(value):
    """File text from a paged read result that must cover the whole file."""
    header, separator, text = value.partition("\n")
    assert header.startswith(PAGE_HEADER) and separator, value[:200]
    metadata = json.loads(header[len(PAGE_HEADER):])
    assert metadata["read_eof"] and metadata["next_start_line"] is None
    return text


def prior_evidence(root):
    (root / "runs/repair-author-completed.log").write_text(
        "Historical incomplete repair; inspect current candidate.\n" * 150, encoding="utf-8")
    (root / "evidence/requested-source.txt").write_text("Source-backed task evidence", encoding="utf-8")


@pytest.mark.parametrize("wire", ["openai", "anthropic"])
def test_actual_api_author_tools_exclude_current_log_keep_completed_history(draft, monkeypatch, wire):
    root, candidate, active, _states = draft
    prior_evidence(root)
    turns = []
    log_name = None
    def turn(_prov, _model, _system, messages, _tools, _key, **_kwargs):
        nonlocal log_name
        turns.append(deepcopy(messages))
        raw = [] if wire == "anthropic" else {"role": "assistant", "content": ""}
        if len(turns) == 1:
            log = next(p for p in (root / "runs").glob("repair-author-*.log")
                       if p.name != "repair-author-completed.log")
            log_name = log.relative_to(root).as_posix()
            prompt = messages[0]["content"]
            assert "Inspect the current candidate files and the supplied evidence" in prompt
            assert "optional historical context" in prompt
            assert "NEVER read this pass's active output log: " + log_name in prompt
            assert "and the prior runs/repair-author-*.log records first" not in prompt
            return "", [
                ("listing", "list_work_files", {"subdir": "."}),
                ("runs", "list_work_files", {"subdir": "runs"}),
                ("own", "read_work_file", {"path": log_name}),
                ("old", "read_work_file", {"path": "runs/repair-author-completed.log"}),
                ("candidate", "read_work_file", {"path": "candidate/SKILL.md"}),
                ("evidence", "read_work_file", {"path": "evidence/requested-source.txt"}),
            ], raw
        outputs = ({b["tool_use_id"]: b["content"] for b in messages[-1]["content"]}
                   if wire == "anthropic" else {m["tool_call_id"]: m["content"]
                       for m in messages if m["role"] == "tool"})
        assert log_name not in outputs["listing"] and log_name not in outputs["runs"]
        assert "runs/repair-author-completed.log" in outputs["listing"]
        assert "runs/repair-author-completed.log" in outputs["runs"]
        assert outputs["own"].startswith("ERROR: The current author output log")
        assert page_text(outputs["old"]) == (root / "runs/repair-author-completed.log").read_text(encoding="utf-8")
        assert page_text(outputs["candidate"]) == (candidate / "SKILL.md").read_text(encoding="utf-8")
        assert page_text(outputs["evidence"]) == "Source-backed task evidence"
        text = author_report()
        return text, [], [] if wire == "anthropic" else {"role": "assistant", "content": text}
    monkeypatch.setattr(api, "_anthropic_turn" if wire == "anthropic" else "_openai_turn", turn)
    before = (candidate / "SKILL.md").read_bytes()
    result = review.author_draft("fixture", provider="api:anthropic" if wire == "anthropic" else "api:deepseek",
        author_notes="Read current source; preserve finished history.",
        stop_event=threading.Event(), emit=lambda _: None, managed_roots=[active])
    assert result["status"] == "completed" and len(turns) == 2
    assert not result["verified"] and not result["native_execution_verified"]
    assert (candidate / "SKILL.md").read_bytes() == before
    assert Path(result["log"]).is_file()
    # Once a later pass has a different active log, this completed log is normal
    # readable history. There is no blanket ban on runs/ or older transcripts.
    cfg = paths.KissConfig.default(root)
    out = review._author_tool("read_work_file", {"path": log_name},
        KI("KDT", review.kdtstudio.engine_root()), cfg, candidate,
        active_log=root / "runs/repair-author-next.log")
    assert "Read current source; preserve finished history." in out


@pytest.mark.parametrize("spelling", ["relative", "absolute", "dotdot", "hardlink"])
def test_exact_active_log_identity_is_blocked_but_independent_same_bytes_are_not(draft, spelling):
    root, candidate, _active, _states = draft
    log = root / "runs/active.log"
    log.write_text("Live output", encoding="utf-8")
    completed = root / "runs/completed.log"
    completed.write_bytes(log.read_bytes())
    if spelling == "relative": value = "runs/active.log"
    elif spelling == "absolute": value = str(log)
    elif spelling == "dotdot": value = "candidate/../runs/active.log"
    else:
        alias = root / "runs/active-alias.log"
        os.link(log, alias)
        value = "runs/active-alias.log"
    cfg = paths.KissConfig.default(root)
    engine = KI("KDT", review.kdtstudio.engine_root())
    with pytest.raises(review.ReviewError, match="current author output log"):
        review._author_tool("read_work_file", {"path": value}, engine, cfg, candidate, active_log=log)
    listing = review._author_tool("list_work_files", {"subdir": "runs"}, engine, cfg, candidate, active_log=log)
    assert "active.log" not in listing and "active-alias.log" not in listing
    assert "runs/completed.log" in listing
    assert page_text(review._author_tool("read_work_file", {"path": "runs/completed.log"},
        engine, cfg, candidate, active_log=log)) == "Live output"
    assert log.read_text(encoding="utf-8") == "Live output"


@pytest.mark.parametrize("name", ["claude", "codex"])
def test_cli_authors_get_same_candidate_first_and_explicit_active_log_rule(draft, monkeypatch, name):
    root, candidate, active, _states = draft
    prior_evidence(root)
    cli_help(monkeypatch)
    def run(prov, prompt, cwd, **kwargs):
        assert cwd == candidate
        current = next(p for p in (root / "runs").glob("repair-author-*.log")
                       if p.name != "repair-author-completed.log")
        assert "Inspect the current candidate files and the supplied evidence" in prompt
        assert "optional historical context" in prompt
        assert "NEVER read this pass's active output log: " + current.relative_to(root).as_posix() in prompt
        assert "Do not inventory or summarize all logs." in prompt
        assert (root / "runs/repair-author-completed.log").is_file()
        assert [Path(g.path) for g in kwargs["pol"].all_grants() if g.kind == "write"] == [candidate]
        kwargs["session_out"]["returncode"] = 0
        yield author_report()
    monkeypatch.setattr(providers, "run", run)
    result = review.author_draft("fixture", provider="cli:" + name,
        stop_event=threading.Event(), emit=lambda _: None, managed_roots=[active])
    assert result["status"] == "completed" and not result["verified"]


def test_no_active_log_keeps_existing_tool_contract(draft):
    root, candidate, _active, _states = draft
    prior_evidence(root)
    cfg = paths.KissConfig.default(root)
    engine = KI("KDT", review.kdtstudio.engine_root())
    assert "repair-author-completed.log" in review._author_tool(
        "list_work_files", {"subdir": "runs"}, engine, cfg, candidate)
    with pytest.raises(review.ReviewError, match="candidate directory"):
        review._author_tool("write_work_file", {"path": "runs/new.log", "content": "No"},
            engine, cfg, candidate, active_log=root / "runs/current.log")
    with pytest.raises(review.ReviewError, match="no command"):
        review._author_tool("run_setup_command", {"command": ["model.exe"]},
            engine, cfg, candidate, active_log=root / "runs/current.log")
