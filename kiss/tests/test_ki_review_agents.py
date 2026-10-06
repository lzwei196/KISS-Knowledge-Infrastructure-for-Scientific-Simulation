"""Independent review boundary tests: fake providers, no network or model runs."""
from copy import deepcopy
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from kiss_cli import api, kdtstudio, ki_guard, ki_review_agents as review, providers


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / "context"
    root.mkdir()
    (root / "manifest.json").write_text('{"purpose":"failure evidence"}', encoding="utf-8")
    (root / "log.txt").write_text("model failed: reader header mismatch\n", encoding="utf-8")
    (root / "long.txt").write_text("很长的历史" * 10_000, encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-only")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-only")
    def no_network(*_args, **_kwargs):
        raise AssertionError("No provider network call is allowed in these tests")
    monkeypatch.setattr(api, "_post", no_network)
    return root, kdtstudio.tree_digest(root)


def report(path="log.txt"):
    return {"summary": "The retained log records a reader failure; its cause needs a regression test.",
        "findings": [{"category": "reader", "severity": "high", "claim": "Header mismatch is reported.",
            "evidence": [path], "recommendation": "Repair the reader in a KDT draft and test the retained output."}],
        "uncertainties": ["The native result has not been independently reproduced."],
        "tests_not_run": ["Native model and reader regression"]}


def fake_api(monkeypatch, *, final=None, on_read=None, wire="openai"):
    histories, tools_seen, responses = [], [], []
    def turn(_prov, _model, _system, messages, tools, _key, **_kwargs):
        histories.append(deepcopy(messages))
        tools_seen.append(deepcopy(tools))
        if len(histories) == 1:
            calls = [("read-1", "read_evidence", {"path": "log.txt"})]
            raw = ([{"type": "tool_use", "id": "read-1", "name": "read_evidence", "input": {"path": "log.txt"}}]
                   if wire == "anthropic" else {"role": "assistant", "content": "", "tool_calls": []})
            return "", calls, raw
        if on_read:
            on_read()
        text = json.dumps(final if final is not None else report())
        responses.append(text)
        return text, [], [] if wire == "anthropic" else {"role": "assistant", "content": text}
    monkeypatch.setattr(api, "_anthropic_turn" if wire == "anthropic" else "_openai_turn", turn)
    return histories, tools_seen


def run(bundle, **kwargs):
    root, digest = bundle
    return review.review("contract_runtime", root, digest, provider="api:deepseek",
                         stop_event=kwargs.pop("stop_event", threading.Event()),
                         emit=lambda _: None, **kwargs)


@pytest.mark.parametrize("wire", ["openai", "anthropic"])
def test_api_review_has_only_frozen_read_tools_and_validated_report(bundle, monkeypatch, wire):
    history, tools = fake_api(monkeypatch, wire=wire)
    result = review.review("data_science", *bundle,
        provider="api:anthropic" if wire == "anthropic" else "api:deepseek",
        stop_event=threading.Event(), emit=lambda _: None)
    assert result["status"] == "completed" and result["analysis_only"]
    assert result["native_execution_verified"] is False
    assert result["findings"] == report()["findings"]
    assert {tool["name"] for tool in tools[0]} == {"read_evidence", "list_evidence"}
    assert len(history[0]) == 1 and history[0][0]["role"] == "user"
    assert result["evidence_reads"] == [{"path": "log.txt", "offset": 0,
        "characters": len((bundle[0] / "log.txt").read_text(encoding="utf-8")), "eof": True}]
    assert kdtstudio.tree_digest(bundle[0]) == bundle[1]


def test_each_review_has_a_fresh_history(bundle, monkeypatch):
    starts = []
    def turn(_prov, _model, _system, messages, _tools, _key, **_kwargs):
        if len(messages) == 1:
            starts.append(deepcopy(messages))
            return "", [("r", "read_evidence", {"path": "log.txt"})], {"role": "assistant", "content": ""}
        return json.dumps(report()), [], {"role": "assistant", "content": "final"}
    monkeypatch.setattr(api, "_openai_turn", turn)
    for role in review.ROLES:
        result = review.review(role, *bundle, provider="api:deepseek", stop_event=threading.Event(), emit=lambda _: None)
        assert result["status"] == "completed"
    assert len(starts) == 3 and starts[0] == starts[1] == starts[2]


def test_paged_text_has_no_8000_character_history_truncation(bundle):
    root, _ = bundle
    reads, result, offset = [], [], 0
    while True:
        page = review._evidence_tool("read_evidence", {"path": "long.txt", "offset": offset, "limit": 7501}, root, reads)
        result.append(page["text"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    assert "".join(result) == (root / "long.txt").read_text(encoding="utf-8")
    assert len(reads) > 3 and reads[-1]["eof"]
    first = review._evidence_tool("list_evidence", {"limit": 1}, root, [])
    assert first["total_files"] == 3 and first["next_offset"] == 1


@pytest.mark.parametrize("path", ["../secret.txt", "D:/secret.txt", "log.txt:ads", "missing.txt", "a\\b"])
def test_evidence_reader_rejects_escape_missing_and_ads(bundle, path):
    with pytest.raises(review.ReviewError):
        review._evidence_tool("read_evidence", {"path": path}, bundle[0], [])


def test_unknown_tool_cannot_reach_normal_api_executor(bundle, monkeypatch):
    called, outputs = [], []
    monkeypatch.setattr(api, "execute_tool", lambda *a, **k: called.append(True))
    def turn(_prov, _model, _system, messages, _tools, _key, **_kwargs):
        if len(messages) == 1:
            return "", [("evil", "run_setup_command", {"command": ["model.exe"]})], {"role": "assistant", "content": ""}
        outputs.append(messages[-1]["content"])
        return json.dumps(report()), [], {"role": "assistant", "content": ""}
    monkeypatch.setattr(api, "_openai_turn", turn)
    result = run(bundle)
    assert not called and result["status"] == "failed"
    assert "Only list_evidence" in outputs[0] and "did not read" in result["error"]


@pytest.mark.parametrize("failure", ["invalid_json", "missing_test_scope", "invented_citation", "unread_citation"])
def test_unvalidated_partial_report_never_completes(bundle, monkeypatch, failure):
    value = report()
    if failure == "missing_test_scope":
        value.pop("tests_not_run")
    if failure == "invented_citation":
        value["findings"][0]["evidence"] = ["fake.txt"]
    if failure == "unread_citation":
        value["findings"][0]["evidence"] = ["long.txt"]
    fake_api(monkeypatch, final=value)
    if failure == "invalid_json":
        monkeypatch.setattr(api, "_openai_turn", lambda *a, **k: ('{"summary":"partial', [], {}))
    result = run(bundle)
    assert result["status"] == "failed" and "findings" not in result
    assert result.get("raw_response")


@pytest.mark.parametrize("wire", ["openai", "anthropic"])
def test_invalid_final_can_read_missing_evidence_then_submit_valid_report(bundle, monkeypatch, wire):
    history = []
    def turn(_prov, _model, _system, messages, _tools, _key, **_kwargs):
        history.append(deepcopy(messages))
        if len(history) == 2:
            assert "did not read: log.txt" in messages[-1]["content"]
            assert "No report or finding was accepted" in messages[-1]["content"]
            previous = messages[-2]
            assert previous["role"] == "assistant"
            previous_text = previous["content"][0]["text"] if wire == "anthropic" else previous["content"]
            assert json.loads(previous_text) == report()
            raw = ([{"type": "tool_use", "id": "read", "name": "read_evidence", "input": {"path": "log.txt"}}]
                   if wire == "anthropic" else {"role": "assistant", "content": "", "tool_calls": []})
            return "", [("read", "read_evidence", {"path": "log.txt"})], raw
        text = json.dumps(report())
        raw = [{"type": "text", "text": text}] if wire == "anthropic" else {"role": "assistant", "content": text}
        return text, [], raw
    monkeypatch.setattr(api, "_anthropic_turn" if wire == "anthropic" else "_openai_turn", turn)
    result = review.review("contract_runtime", *bundle,
        provider="api:anthropic" if wire == "anthropic" else "api:deepseek",
        stop_event=threading.Event(), emit=lambda _: None)
    assert result["status"] == "completed" and len(history) == 3
    assert result["report_repair_attempts"] == 1
    assert result["evidence_reads"][0]["path"] == "log.txt"
    assert result["findings"] == report()["findings"]


def test_repeated_invalid_report_stops_after_two_feedback_attempts(bundle, monkeypatch):
    calls = []
    def turn(_prov, _model, _system, messages, _tools, _key, **_kwargs):
        calls.append(deepcopy(messages))
        text = json.dumps(report("missing-evidence.txt"))
        return text, [], {"role": "assistant", "content": text}
    monkeypatch.setattr(api, "_openai_turn", turn)
    result = run(bundle)
    assert result["status"] == "failed" and "findings" not in result
    assert len(calls) == 3 and result["rounds"] == 3
    assert result["report_repair_attempts"] == 2
    assert len(result["report_validation_errors"]) == 3
    assert "missing or outside" in result["error"]


def test_report_correction_does_not_reset_original_round_budget(bundle, monkeypatch):
    monkeypatch.setattr(review, "MAX_ROUNDS", 1)
    monkeypatch.setattr(api, "_openai_turn", lambda *a, **k:
        (json.dumps(report()), [], {"role": "assistant", "content": json.dumps(report())}))
    result = run(bundle)
    assert result["status"] == "failed" and result["rounds"] == 1
    assert "budget exhausted" in result["error"] and "findings" not in result


def test_changed_context_rejected_before_or_after_provider(bundle, monkeypatch):
    root, digest = bundle
    fake_api(monkeypatch, on_read=lambda: (root / "log.txt").write_text("changed"))
    result = run(bundle)
    assert result["status"] == "failed" and "context changed" in result["error"]
    monkeypatch.setattr(api, "_openai_turn", lambda *a, **k: pytest.fail("provider must not launch"))
    assert run((root, digest))["status"] == "failed"


def test_cancelled_api_closes_attached_response_and_rejects_final(bundle, monkeypatch):
    stop = threading.Event()
    closed = threading.Event()
    def turn(*_args, handle=None, **_kwargs):
        handle.attach(SimpleNamespace(close=closed.set))
        stop.set()
        assert closed.wait(2)
        return json.dumps(report()), [], {}
    monkeypatch.setattr(api, "_openai_turn", turn)
    result = run(bundle, stop_event=stop)
    assert result["status"] == "cancelled" and "findings" not in result


def test_protected_already_dirty_ki_is_inspectable_but_new_mutation_is_rejected(bundle, tmp_path, monkeypatch):
    active = tmp_path / "active"
    active.mkdir()
    (active / "SKILL.md").write_text("accepted baseline")
    ki_guard.enroll(active)
    (active / "SKILL.md").write_text("existing unaccepted edit")
    fake_api(monkeypatch)
    assert run(bundle, managed_roots=[active])["status"] == "completed"
    with pytest.raises(ki_guard.KIIntegrityError):
        ki_guard.require_intact(active)
    fake_api(monkeypatch, on_read=lambda: (active / "SKILL.md").write_text("new provider edit"))
    result = run(bundle, managed_roots=[active])
    assert result["status"] == "failed" and "active KI changed" in result["error"]
    assert any((draft / "SKILL.md").read_text() == "new provider edit" for draft in tmp_path.glob("ki-draft-*"))


@pytest.mark.parametrize("name", ["gemini", "kimi", "qwen", "unknown"])
def test_unsupported_cli_is_explicit_and_never_falls_back(bundle, monkeypatch, name):
    monkeypatch.setattr(providers, "run", lambda *a, **k: pytest.fail("unsupported provider must not launch"))
    result = review.review("contract_runtime", *bundle, provider="cli:" + name,
                          stop_event=threading.Event(), emit=lambda _: None)
    assert result["status"] == "unsupported" and "API" in result["error"]


def cli_help(monkeypatch):
    monkeypatch.setattr(review, "_cli_help", lambda prov:
        "--safe-mode --tools --permission-mode dontAsk --no-session-persistence "
        "--sandbox read-only --ignore-user-config --ignore-rules --ephemeral")


@pytest.mark.parametrize("name", ["claude", "codex"])
def test_cli_uses_fresh_private_copy_and_strong_read_only_profile(bundle, monkeypatch, name):
    cli_help(monkeypatch)
    calls = []
    def fake_run(prov, prompt, cwd, **kwargs):
        calls.append((prov, cwd, kwargs))
        assert cwd != bundle[0] and (cwd / "evidence/log.txt").is_file()
        assert not prov.resume_argv and kwargs.get("resume") is None
        assert all(g.kind == "read" for g in kwargs["pol"].all_grants())
        assert kwargs.get("managed_roots") is None and kwargs.get("ki_root") is None
        if name == "claude":
            assert "--safe-mode" in prov.argv and prov.argv[prov.argv.index("--tools") + 1] == "Read,Glob,Grep"
        else:
            assert kwargs["flow_policy"].argv_delta == ["--sandbox", "read-only"]
            assert kwargs["flow_policy"].planning_worktree
        kwargs["session_out"]["returncode"] = 0
        yield json.dumps(report())
    monkeypatch.setattr(providers, "run", fake_run)
    for _ in range(2):
        result = review.review("contract_runtime", *bundle, provider="cli:" + name,
                              stop_event=threading.Event(), emit=lambda _: None)
        assert result["status"] == "completed"
    assert calls[0][1] != calls[1][1] and kdtstudio.tree_digest(bundle[0]) == bundle[1]


def test_cli_changed_copy_rejects_otherwise_valid_report(bundle, monkeypatch):
    cli_help(monkeypatch)
    def fake_run(prov, prompt, cwd, **kwargs):
        (cwd / "evidence/log.txt").write_text("tampered evidence")
        kwargs["session_out"]["returncode"] = 0
        yield json.dumps(report())
    monkeypatch.setattr(providers, "run", fake_run)
    result = review.review("contract_runtime", *bundle, provider="cli:claude",
                          stop_event=threading.Event(), emit=lambda _: None)
    assert result["status"] == "failed" and "context changed" in result["error"]
    assert Path(result["scratch_root"]).exists() and kdtstudio.tree_digest(bundle[0]) == bundle[1]


def test_cli_cancel_terminates_active_process_and_keeps_partial(bundle, monkeypatch):
    cli_help(monkeypatch)
    stop, killed = threading.Event(), threading.Event()
    process = object()
    monkeypatch.setattr(execution := review.execution, "terminate_tree", lambda item: killed.set() if item is process else None)
    def fake_run(prov, prompt, cwd, **kwargs):
        kwargs["runtime_events"]["_process_handle"] = process
        yield "partial review"
        stop.set()
        assert killed.wait(2)
        kwargs["session_out"]["returncode"] = 0
    monkeypatch.setattr(providers, "run", fake_run)
    result = review.review("contract_runtime", *bundle, provider="cli:codex", stop_event=stop, emit=lambda _: None)
    assert result["status"] == "cancelled" and result["raw_response"] == "partial review"


def test_capability_fails_closed_for_missing_native_flags(monkeypatch):
    monkeypatch.setattr(review, "_cli_help", lambda _: "old CLI help")
    assert not review.capability("cli:claude")["supported"]
    assert not review.capability("cli:codex")["supported"]
    assert not review.capability("deepseek")["supported"]


@pytest.fixture
def draft(tmp_path, monkeypatch, bundle):
    root = tmp_path / "repair-job"
    candidate = root / "candidate"
    candidate.mkdir(parents=True)
    for name in ("runs", "probe", "evidence"):
        (root / name).mkdir()
    (candidate / "SKILL.md").write_text("exact materialized project KI")
    active = tmp_path / "active-ki"
    active.mkdir()
    (active / "SKILL.md").write_text("exact materialized project KI")
    ki_guard.enroll(active)
    engine = tmp_path / "kdt-engine"
    engine.mkdir()
    (engine / "README.md").write_text("KDT contract")
    monkeypatch.setattr(kdtstudio, "engine_root", lambda: engine)
    monkeypatch.setattr(kdtstudio, "job", lambda _: {"root": str(root), "candidate": str(candidate)})
    states = []
    def probe(_job, _emit, *, preserve_candidate=False):
        assert preserve_candidate
        states.append("probe")
        (root / "probe/probe_report.json").write_text("{}")
        (root / "probe/io_graph.json").write_text("{}")
    monkeypatch.setattr(kdtstudio, "run_probe", probe)
    monkeypatch.setattr(kdtstudio, "build_prompt", lambda _: "Generic KDT reference: author a portable KI.")
    monkeypatch.setattr(kdtstudio, "mark_building", lambda *a, **k: states.append("building"))
    monkeypatch.setattr(kdtstudio, "mark_build_finished", lambda *a, **k: states.append("failed" if k.get("failed") else "built"))
    return root, candidate, active, states


def author_report(status="completed"):
    return json.dumps({"status": status, "summary": "Minimal repair draft prepared" if status == "completed" else "Dependency unresolved",
        "changes": ["One repair"], "tests_not_run": ["KDT verification and native execution"],
        "remaining_issues": []})


def test_api_author_edits_only_draft_and_does_not_verify_or_adopt(draft, monkeypatch):
    root, candidate, active, states = draft
    observed = []
    def turn(_prov, _model, system, messages, tools, _key, **_kwargs):
        observed.append(deepcopy(messages))
        assert {t["name"] for t in tools} == review._AUTHOR_READ_TOOLS | review._AUTHOR_WRITE_TOOLS
        assert "preserve materialized project bindings" in system
        if len(observed) == 1:
            assert "not a new portable KI" in messages[0]["content"]
            assert "Do not replace paths" in messages[0]["content"]
            assert "ONE cohesive minimal repair" in messages[0]["content"]
            return "", [
                ("ok", "write_work_file", {"path": "candidate/tools/fix.py", "content": "# reviewed repair draft\n"}),
                ("outside", "write_work_file", {"path": "evidence/fake.txt", "content": "false evidence"}),
                ("command", "run_setup_command", {"command": ["model.exe"]}),
            ], {"role": "assistant", "content": ""}
        return author_report(), [], {"role": "assistant", "content": author_report()}
    monkeypatch.setattr(api, "_openai_turn", turn)
    result = review.author_draft("fixture", provider="api:deepseek", task_extra="Fix the reader only.",
        stop_event=threading.Event(), emit=lambda _: None, managed_roots=[active])
    assert result["status"] == "completed" and result["draft_ready"]
    assert result["verified"] is False and result["native_execution_verified"] is False
    assert (candidate / "tools/fix.py").read_text() == "# reviewed repair draft\n"
    assert not (root / "evidence/fake.txt").exists()
    assert "ERROR:" in observed[1][-1]["content"]
    assert states == ["probe", "building", "built"]
    ki_guard.require_intact(active)


@pytest.mark.parametrize("name", ["claude", "codex"])
def test_cli_author_write_root_is_candidate_only_and_session_is_fresh(draft, monkeypatch, name):
    root, candidate, active, states = draft
    cli_help(monkeypatch)
    def fake_run(prov, prompt, cwd, **kwargs):
        assert cwd == candidate and not prov.resume_argv
        grants = kwargs["pol"].all_grants()
        assert [Path(g.path) for g in grants if g.kind == "write"] == [candidate]
        assert "Preserve their resolved path" in prompt
        if name == "codex":
            assert kwargs["flow_policy"].planning_worktree
            assert kwargs["flow_policy"].argv_delta == ["--sandbox", "workspace-write"]
        else:
            assert "Bash" not in prov.argv[prov.argv.index("--tools") + 1]
        (candidate / "repair.txt").write_text("proposed change")
        kwargs["session_out"]["returncode"] = 0
        yield author_report()
    monkeypatch.setattr(providers, "run", fake_run)
    result = review.author_draft("fixture", provider="cli:" + name, task_extra="Repair candidate only.",
        stop_event=threading.Event(), emit=lambda _: None, managed_roots=[active])
    assert result["status"] == "completed" and not result["verified"]
    assert states[-1] == "built"
    ki_guard.require_intact(active)


def test_author_provider_error_retains_partial_draft_as_failed(draft, monkeypatch):
    root, candidate, active, states = draft
    def fail(*_args, **_kwargs):
        (candidate / "partial.txt").write_text("partial proposed patch")
        raise api.ToolError("provider disconnected")
    monkeypatch.setattr(api, "_openai_turn", fail)
    result = review.author_draft("fixture", provider="api:deepseek", stop_event=threading.Event(),
                                 emit=lambda _: None, managed_roots=[active])
    assert result["status"] == "failed" and states[-1] == "failed"
    assert (candidate / "partial.txt").exists() and not result["verified"]
    ki_guard.require_intact(active)


def test_author_active_mutation_cannot_finish_draft_successfully(draft, monkeypatch):
    root, candidate, active, states = draft
    def fail(*_args, **_kwargs):
        (active / "SKILL.md").write_text("forbidden active edit")
        return author_report(), [], {"role": "assistant", "content": author_report()}
    monkeypatch.setattr(api, "_openai_turn", fail)
    result = review.author_draft("fixture", provider="api:deepseek", stop_event=threading.Event(),
                                 emit=lambda _: None, managed_roots=[active])
    assert result["status"] == "failed" and states[-1] == "failed"
    assert "active KI changed" in result["error"]


@pytest.mark.parametrize("final", ["completed", "incomplete", "prose_failure", "tool_call"])
def test_author_budget_warns_then_requires_tool_free_final_report(draft, monkeypatch, final):
    root, candidate, active, states = draft
    monkeypatch.setattr(review, "MAX_ROUNDS", 6)
    turns = []
    def turn(_prov, _model, _system, messages, tools, _key, **_kwargs):
        turns.append((deepcopy(messages), deepcopy(tools)))
        if len(turns) < 6:
            return "Checking draft", [(str(len(turns)), "list_work_files", {"subdir": "candidate"})], {"role": "assistant", "content": "Checking draft"}
        if final == "tool_call":
            return "", [("forbidden", "write_work_file", {"path": "candidate/budget-escape.txt", "content": "not allowed"})], {"role": "assistant", "content": ""}
        report = "I cannot complete this repair." if final == "prose_failure" else author_report(final)
        return report, [], {"role": "assistant", "content": report}
    monkeypatch.setattr(api, "_openai_turn", turn)
    result = review.author_draft("fixture", provider="api:deepseek", stop_event=threading.Event(),
                                emit=lambda _: None, managed_roots=[active])
    assert len(turns) == result["rounds"] == 6
    assert turns[-1][1] == [] and all(item[1] for item in turns[:-1])
    assert "budget is almost exhausted" in turns[2][0][-1]["content"]
    assert "final report-only turn" in turns[-1][0][-1]["content"]
    assert (result["status"] == "completed") is (final == "completed")
    assert states[-1] == ("built" if final == "completed" else "failed")
    assert not (candidate / "budget-escape.txt").exists()
    assert not result["verified"]


def test_author_rejects_candidate_drift_during_probe_before_provider(draft, monkeypatch):
    root, candidate, active, states = draft
    def broken_probe(*_args, **_kwargs):
        (candidate / "SKILL.md").write_text("unexpected overwritten scaffold")
    monkeypatch.setattr(kdtstudio, "run_probe", broken_probe)
    monkeypatch.setattr(api, "_openai_turn", lambda *_args, **_kwargs: pytest.fail("provider must not see corrupted seed"))
    result = review.author_draft("fixture", provider="api:deepseek", stop_event=threading.Event(),
                                emit=lambda _: None, managed_roots=[active])
    assert result["status"] == "failed" and "changed the seeded repair candidate" in result["error"]
    assert "building" not in states
