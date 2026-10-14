"""All citation errors are actionable together; failed diagnostics grant nothing."""
from copy import deepcopy
import json
import threading

import pytest

from kiss_cli import api, ki_investigation as inv, ki_review_agents as review
from .test_ki_review_agents import bundle, report
from .test_ki_investigation import case, new, reviewer


@pytest.mark.parametrize("wire", ["openai", "anthropic"])
def test_one_feedback_exposes_three_unread_files_then_requires_actual_reads(bundle, monkeypatch, wire):
    value = report()
    citations = ["log.txt", "manifest.json", "long.txt"]
    value["findings"][0]["evidence"] = citations
    history = []

    def turn(_prov, _model, system, messages, _tools, _key, **_kwargs):
        history.append(deepcopy(messages))
        assert "Read every exact file before citing it" in system
        assert "successful read_evidence call in this review" in system
        if len(history) == 2:
            assert all("did not read: " + path in messages[-1]["content"] for path in citations)
            calls = [(str(i), "read_evidence", {"path": path}) for i, path in enumerate(citations)]
            raw = ([{"type": "tool_use", "id": ident, "name": name, "input": args}
                    for ident, name, args in calls] if wire == "anthropic" else
                   {"role": "assistant", "content": "", "tool_calls": []})
            return "", calls, raw
        text = json.dumps(value)
        raw = ([{"type": "text", "text": text}] if wire == "anthropic" else
               {"role": "assistant", "content": text})
        return text, [], raw

    monkeypatch.setattr(api, "_anthropic_turn" if wire == "anthropic" else "_openai_turn", turn)
    result = review.review("data_science", *bundle,
        provider="api:anthropic" if wire == "anthropic" else "api:deepseek",
        stop_event=threading.Event(), emit=lambda _: None)
    assert result["status"] == "completed" and result["rounds"] == 3
    assert result["report_repair_attempts"] == 1
    assert len(result["report_validation_errors"]) == 1
    assert [read["path"] for read in result["evidence_reads"]] == citations
    assert result["findings"] == value["findings"]
    assert review.MAX_REPORT_REPAIRS == 2 and review.MAX_ROUNDS == 64


@pytest.mark.parametrize("bad", ["missing.txt", "../outside.txt", "C:/outside.txt", "log.txt:ads", None])
def test_invalid_path_and_all_unread_paths_are_reported_without_acceptance(bundle, bad):
    value = report()
    value["findings"][0]["evidence"] = ["log.txt", bad]
    second = deepcopy(value["findings"][0])
    second["evidence"] = ["long.txt"]
    value["findings"].append(second)
    with pytest.raises(review.ReviewError) as exc:
        review._report(json.dumps(value), bundle[0], read_paths=set())
    assert "did not read: log.txt" in str(exc.value)
    assert "findings[0].evidence[1]" in str(exc.value)
    assert "did not read: long.txt" in str(exc.value)


def test_listing_cannot_satisfy_batched_unread_citations(bundle):
    reads = []
    review._evidence_tool("list_evidence", {}, bundle[0], reads)
    value = report()
    value["findings"][0]["evidence"] = ["log.txt", "manifest.json"]
    with pytest.raises(review.ReviewError, match="did not read"):
        review._report(json.dumps(value), bundle[0], read_paths={item["path"] for item in reads})
    assert not reads


def diagnostic_result(digest, status="failed"):
    return {"status": status, "context_digest": digest, "error": "Unread evidence",
        "rounds": 48, "report_repair_attempts": 2,
        "report_validation_errors": ["Unread file one", "Unread file two", "Unread file three"],
        "evidence_reads": [{"path": "kis/M/tools/reader.py", "offset": 0, "characters": 20, "eof": True}],
        "summary": "Unaccepted prose", "findings": [{"claim": "Must not be accepted"}],
        "raw_response": "Must not be persisted as a review", "native_verified": True}


@pytest.mark.parametrize("status", ["failed", "cancelled", "unsupported"])
def test_failed_diagnostics_survive_signed_job_without_authorizing_draft(case, status):
    job = new(case)

    def run(role, context, digest, stop, emit):
        return (diagnostic_result(digest, status) if role == "data_science" else
                reviewer(role, context, digest, stop, emit))

    result = inv.run_reviews(case[0], job["id"], run)
    assert result["status"] == "review_failed"
    saved = inv._load(case[0], job["id"])
    failed = next(row for row in saved["reviewers"] if row["role"] == "data_science")
    assert failed["status"] == status
    assert set(failed) == {"role", "status", "error", "diagnostics"}
    assert failed["diagnostics"] == {key: value for key, value in diagnostic_result(job["context"]["digest"]).items()
        if key in {"rounds", "report_repair_attempts", "report_validation_errors", "evidence_reads", "context_digest"}}
    assert len(result["combined_report"]["findings"]) == 2
    assert all(row["reviewer"] != "data_science" for row in result["combined_report"]["findings"])
    with pytest.raises(inv.InvestigationError, match="three reviews"):
        inv.create_draft(case[0], job["id"], "M")


def test_failed_diagnostics_are_bounded_redacted_and_context_scoped(bundle, monkeypatch):
    secret = "fixture-diagnostic-secret-12345"
    monkeypatch.setenv("TEST_API_KEY", secret)
    value = diagnostic_result(bundle[1])
    value["rounds"] = True
    value["report_repair_attempts"] = 100
    value["report_validation_errors"] = [secret + "x" * 20_000] * 4
    value["evidence_reads"] = [
        {"path": "log.txt", "offset": 0, "characters": 12, "eof": True, "content": secret},
        {"path": "../escape", "offset": 0, "characters": 12, "eof": True},
        {"path": "log.txt", "offset": -1, "characters": 12, "eof": True},
    ] + [{"path": "log.txt", "offset": 0, "characters": 12, "eof": True}] * 2000
    row = inv._normal_report("data_science", value, bundle[0], bundle[1])
    diag = row["diagnostics"]
    assert "rounds" not in diag and "report_repair_attempts" not in diag
    assert len(diag["report_validation_errors"]) == 3
    assert all(len(item) <= 16_000 for item in diag["report_validation_errors"])
    assert len(diag["evidence_reads"]) <= 1920 and diag["truncated"] is True
    assert secret not in json.dumps(row)
    assert all(set(read) == {"path", "offset", "characters", "eof"} for read in diag["evidence_reads"])
    value["context_digest"] = "a" * 64
    assert "diagnostics" not in inv._normal_report("data_science", value, bundle[0], bundle[1])
