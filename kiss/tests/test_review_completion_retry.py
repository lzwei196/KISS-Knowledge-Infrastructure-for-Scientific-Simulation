"""Bounded review completion and same-context incomplete-role retry."""
from copy import deepcopy
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from kiss_cli import api, kdtstudio, ki_investigation as inv, ki_review_agents as review, providers
from .test_ki_investigation import case, new, reviewer
from .test_ki_review_agents import bundle, report, cli_help
from .test_review_citation_feedback import diagnostic_result


def wire_raw(wire, text="", calls=()):
    if wire == "anthropic":
        return ([{"type": "tool_use", "id": ident, "name": name, "input": args}
                 for ident, name, args in calls] if calls else [{"type": "text", "text": text}])
    return {"role": "assistant", "content": text, "tool_calls": []} if calls else {"role": "assistant", "content": text}


@pytest.mark.parametrize("wire", ["openai", "anthropic"])
def test_reserved_report_rounds_keep_two_corrections_without_executing_final_tools(bundle, monkeypatch, wire):
    monkeypatch.setattr(review, "MAX_ROUNDS", 6)
    turns = []

    def turn(_prov, _model, _system, messages, tools, _key, **_kwargs):
        turns.append((deepcopy(messages), deepcopy(tools)))
        number = len(turns)
        if number <= 3:
            calls = [(str(number), "read_evidence", {"path": "log.txt"})] if number == 1 else [
                (str(number), "list_evidence", {})]
            return "", calls, wire_raw(wire, calls=calls)
        assert not tools
        if number == 5:
            calls = [("denied", "read_evidence", {"path": "long.txt"})]
            return "", calls, wire_raw(wire, calls=calls)
        text = json.dumps(report("long.txt" if number == 4 else "log.txt"))
        return text, [], wire_raw(wire, text)

    monkeypatch.setattr(api, "_anthropic_turn" if wire == "anthropic" else "_openai_turn", turn)
    result = review.review("data_science", *bundle,
        provider="api:anthropic" if wire == "anthropic" else "api:deepseek",
        stop_event=threading.Event(), emit=lambda _: None)
    assert result["status"] == "completed" and result["rounds"] == 6
    assert result["report_repair_attempts"] == 2
    assert [item["path"] for item in result["evidence_reads"]] == ["log.txt"]
    assert "budget is almost exhausted" in turns[2][0][-1]["content"]
    assert "final report-only phase" in turns[3][0][-1]["content"]
    assert "Tools remain unavailable" in turns[4][0][-1]["content"]
    assert "no tools were executed" in turns[5][0][-1]["content"]
    assert len(result["report_validation_errors"]) == 2
    assert review.MAX_REPORT_REPAIRS == 2


def test_report_only_tool_requests_remain_incomplete(bundle, monkeypatch):
    monkeypatch.setattr(review, "MAX_ROUNDS", 3)
    calls = []

    def turn(_prov, _model, _system, messages, tools, _key, **_kwargs):
        assert not tools
        calls.append(1)
        wanted = [("read", "read_evidence", {"path": "log.txt"})]
        return "", wanted, wire_raw("openai", calls=wanted)

    monkeypatch.setattr(api, "_openai_turn", turn)
    result = review.review("data_science", *bundle, provider="api:deepseek",
        stop_event=threading.Event(), emit=lambda _: None)
    assert len(calls) == 3 and result["status"] == "failed"
    assert not result["evidence_reads"] and "findings" not in result


def test_time_reserve_requests_honest_limited_report_without_new_reads(bundle, monkeypatch):
    cancel = SimpleNamespace(deadline=review.time.monotonic() + 50, check=lambda: None, handle=api.TurnHandle())
    result = {"context_digest": bundle[1], "role": "data_science"}
    limited = {"summary": "Evidence coverage is incomplete.", "findings": [],
               "uncertainties": ["Relevant files were not read."], "tests_not_run": ["Native model run"]}

    def turn(_prov, _model, _system, messages, tools, _key, **_kwargs):
        assert not tools and "already read" in messages[-1]["content"]
        return json.dumps(limited), [], wire_raw("openai", json.dumps(limited))

    monkeypatch.setattr(api, "_openai_turn", turn)
    assert review._api_review(api.PROVIDERS["deepseek"], "", bundle[0], "Review", cancel, lambda _: None, result) == limited
    assert result["rounds"] == 1 and not result["evidence_reads"]


@pytest.mark.parametrize("provider", ["api:deepseek", "cli:claude", "cli:codex"])
def test_current_issue_is_upfront_from_sealed_packet_before_long_history(bundle, monkeypatch, tmp_path, provider):
    root = bundle[0]
    issue = "Repair only the current frozen WOFOST runtime-path mismatch."
    outside = tmp_path / "live-secret.txt"
    outside.write_text("LIVE-CONTENT-MUST-NOT-BE-READ")
    (root / "investigation.json").write_text(json.dumps({
        "session": {"project": str(outside), "history": "obsolete history " * 6000}, "issue": issue}), encoding="utf-8")
    for rel in ("kis/WOFOST/preflight_check.py", "project/models/WOFOST/kiss.toml", "project/runs/plan.json"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("frozen fixture")
    digest = kdtstudio.tree_digest(root)
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path != outside, "review navigation must never consult live paths from session metadata"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    prompts = []

    def turn(_prov, _model, system, messages, _tools, _key, **_kwargs):
        prompts.append(system)
        if len(messages) == 1:
            calls = [("read", "read_evidence", {"path": "log.txt"})]
            return "", calls, wire_raw("openai", calls=calls)
        return json.dumps(report()), [], wire_raw("openai", json.dumps(report()))

    def cli_run(_prov, prompt, _cwd, **kwargs):
        prompts.append(prompt)
        kwargs["session_out"]["returncode"] = 0
        yield json.dumps(report())

    cli_help(monkeypatch)
    monkeypatch.setattr(api, "_openai_turn", turn)
    monkeypatch.setattr(providers, "run", cli_run)
    result = review.review("data_science", root, digest, provider=provider,
        stop_event=threading.Event(), emit=lambda _: None)
    assert result["status"] == "completed"
    assert issue in prompts[0] and "obsolete history" not in prompts[0]
    assert "historical chronology" in prompts[0]
    assert "project/models/WOFOST/kiss.toml" in prompts[0] and "project/runs/plan.json" in prompts[0]
    assert "existence only, not citation-read credit" in prompts[0]
    assert kdtstudio.tree_digest(root) == digest
    if provider.startswith("api"):
        assert [item["path"] for item in result["evidence_reads"]] == ["log.txt"]


def test_context_brief_is_bounded_and_tampering_still_rejects(bundle, monkeypatch):
    root = bundle[0]
    metadata = root / "investigation.json"
    metadata.write_text(json.dumps({"issue": "scope", "session": {"history": "x" * 200}}))
    digest = kdtstudio.tree_digest(root)
    monkeypatch.setattr(review, "MAX_CONTEXT_METADATA_BYTES", 100)
    assert "exceeds the bounded" in review._context_brief(root)
    metadata.write_text('{"issue":"changed"}')
    monkeypatch.setattr(api, "_openai_turn", lambda *a, **k: pytest.fail("tampered context must not launch"))
    result = review.review("data_science", root, digest, provider="api:deepseek",
        stop_event=threading.Event(), emit=lambda _: None)
    assert result["status"] == "failed" and "context changed" in result["error"]


def incomplete(case, *, status="failed"):
    job = new(case)

    def run(role, context, digest, stop, emit):
        return diagnostic_result(digest, status) if role == "data_science" else reviewer(role, context, digest, stop, emit)

    return inv.run_reviews(case[0], job["id"], run)


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_retry_only_incomplete_role_uses_fresh_conversation_and_preserves_completed(case, monkeypatch, status):
    job = incomplete(case, status=status)
    before = {row["role"]: deepcopy(row) for row in job["reviewers"] if row["status"] == "completed"}
    assert job["can_retry_review"] and job["retry_review_roles"] == ["data_science"]
    starts, roles = [], []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-only")

    def turn(_prov, _model, _system, messages, _tools, _key, **_kwargs):
        if len(messages) == 1:
            starts.append(deepcopy(messages))
            assert all(row["report"]["summary"] not in json.dumps(messages) for row in before.values())
            calls = [("read", "read_evidence", {"path": "kis/M/tools/reader.py"})]
            return "", calls, wire_raw("openai", calls=calls)
        value = report("kis/M/tools/reader.py")
        return json.dumps(value), [], wire_raw("openai", json.dumps(value))

    monkeypatch.setattr(api, "_openai_turn", turn)

    def run(role, context, digest, stop, emit):
        roles.append(role)
        assert context == Path(job["context"]["root"]) and digest == job["context"]["digest"]
        assert not stop.is_set()
        return review.review(role, context, digest, provider="api:deepseek", stop_event=stop, emit=emit)

    result = inv.retry_incomplete_reviews(case[0], job["id"], run)
    assert result["status"] == "reviewed" and roles == ["data_science"] and len(starts) == 1
    assert not result["can_retry_review"]
    assert {row["role"]: row for row in result["reviewers"] if row["role"] in before} == before
    assert len(result["combined_report"]["findings"]) == 3
    history = result["review_attempt_history"]
    assert len(history) == 1 and history[0]["result"]["status"] == status
    assert "report" not in history[0]["result"] and "findings" not in history[0]["result"]
    assert history[0]["result"]["diagnostics"]["rounds"] == 48
    assert inv._load(case[0], job["id"])["review_attempt"] == 2


@pytest.mark.parametrize("changed", ["project", "ki", "context"])
def test_retry_refuses_changed_source_or_context_before_provider(case, changed):
    job = incomplete(case)
    target = {"project": case[0] / "runs/plan.json", "ki": case[1] / "tools/reader.py",
              "context": Path(job["context"]["root"]) / "investigation.json"}[changed]
    target.write_text("changed")
    with pytest.raises(inv.InvestigationError, match="changed|fresh"):
        inv.retry_incomplete_reviews(case[0], job["id"], lambda *args: pytest.fail("must not launch"))
    assert inv._load(case[0], job["id"])["review_attempt"] == 1


@pytest.mark.parametrize("changed", ["project", "context"])
def test_retry_change_during_provider_cannot_publish_completed_report(case, changed):
    job = incomplete(case)

    def run(role, context, digest, stop, emit):
        target = case[0] / "runs/plan.json" if changed == "project" else context / "investigation.json"
        target.write_text("changed during retry")
        return reviewer(role, context, digest, stop, emit)

    result = inv.retry_incomplete_reviews(case[0], job["id"], run)
    assert result["status"] == "stale" and not result["can_retry_review"]
    assert next(row for row in result["reviewers"] if row["role"] == "data_science")["status"] == "failed"
    assert len(result["combined_report"]["findings"]) == 2
    with pytest.raises(inv.InvestigationError, match="three reviews"):
        inv.create_draft(case[0], job["id"], "M")


def test_retry_concurrent_worker_and_cancel_are_safe(case):
    job = incomplete(case)
    entered, release = threading.Event(), threading.Event()
    results = []

    def run(role, context, digest, stop, emit):
        entered.set()
        assert release.wait(5)
        return reviewer(role, context, digest, stop, emit)

    worker = threading.Thread(target=lambda: results.append(inv.retry_incomplete_reviews(case[0], job["id"], run)))
    worker.start()
    try:
        assert entered.wait(5)
        assert not inv.get(case[0], job["id"])["can_retry_review"]
        with pytest.raises(inv.InvestigationError, match="active"):
            inv.retry_incomplete_reviews(case[0], job["id"], lambda *args: pytest.fail("duplicate worker"))
        inv.cancel(case[0], job["id"])
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive() and results[0]["status"] == "cancelled"
    assert next(row for row in results[0]["reviewers"] if row["role"] == "data_science")["status"] == "cancelled"
    assert results[0]["can_retry_review"]
    assert inv.retry_incomplete_reviews(case[0], job["id"], reviewer)["status"] == "reviewed"


def test_retry_history_is_bounded_without_promoting_failed_findings(case):
    job = incomplete(case)
    completed = [row for row in job["reviewers"] if row["status"] == "completed"]
    for _ in range(inv.MAX_REVIEW_ATTEMPT_HISTORY + 2):
        result = inv.retry_incomplete_reviews(case[0], job["id"],
            lambda role, context, digest, stop, emit: diagnostic_result(digest))
    assert result["status"] == "review_failed"
    assert len(result["review_attempt_history"]) == inv.MAX_REVIEW_ATTEMPT_HISTORY
    assert result["review_history_dropped"] == 2
    assert [row for row in result["reviewers"] if row["status"] == "completed"] == completed
    assert len(result["combined_report"]["findings"]) == 2
    with pytest.raises(inv.InvestigationError, match="three reviews"):
        inv.create_draft(case[0], job["id"], "M")


@pytest.mark.parametrize("failure", ["unsupported", "draft", "completed_context", "unsigned"])
def test_ineligible_or_unauthenticated_retry_does_not_launch(case, failure):
    job = incomplete(case, status="unsupported" if failure == "unsupported" else "failed")
    doc = inv._load(case[0], job["id"])
    if failure == "draft":
        doc["draft"] = {"path": str(case[1])}
        inv._save(case[0], doc)
    elif failure == "completed_context":
        next(row for row in doc["reviewers"] if row["status"] == "completed")["report"]["context_digest"] = "a" * 64
        inv._save(case[0], doc)
    elif failure == "unsigned":
        doc["issue"] = "unauthenticated mutation"
        (inv._root(case[0], job["id"]) / "job.json").write_text(json.dumps(doc))
    with pytest.raises(inv.InvestigationError):
        inv.retry_incomplete_reviews(case[0], job["id"], lambda *args: pytest.fail("ineligible retry launched"))
