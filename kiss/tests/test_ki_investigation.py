"""Offline investigation lifecycle tests: no provider or native model calls."""
from pathlib import Path
import json
import threading

import pytest

from kiss_cli import doctor, flowgate, kdtstudio, ki_guard, ki_investigation as inv, ki_verification as gate, paths


@pytest.fixture
def case(tmp_path, monkeypatch):
    for name, sub in (("GEOFORGE_KI_INVESTIGATION_HOME", "investigations"),
                      ("GEOFORGE_KI_GUARD_HOME", "guard"),
                      ("GEOFORGE_KI_VERIFICATION_HOME", "verification"),
                      ("GEOFORGE_FLOW_KEYS", "keys"),
                      ("GEOFORGE_FLOW_REGISTRY", "registry"),
                      ("GEOFORGE_KDT_HOME", "studio")):
        monkeypatch.setenv(name, str(tmp_path / sub))
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    monkeypatch.setattr(kdtstudio, "engine_source_digest", lambda *args: "e" * 64)
    project = tmp_path / "project"
    root = project / "models" / "M" / "ki"
    (root / "tools").mkdir(parents=True)
    (root / "SKILL.md").write_text("Original KI instructions\n", encoding="utf-8")
    (root / "tools" / "reader.py").write_text("def read(): return 1\n", encoding="utf-8")
    ki_guard.enroll(root)
    (project / "memory").mkdir()
    (project / "memory" / "transcript.jsonl").write_text("old message\n" * 25, encoding="utf-8")
    (project / "inputs").mkdir()
    (project / "inputs" / "data.csv").write_text("day,q\n1,2\n")
    (project / "runs").mkdir()
    (project / "runs" / "plan.json").write_text(json.dumps({"selected_kis": ["M"],
        "steps": [{"id": "read", "ki": "M", "tool": str(root / "tools" / "reader.py")}]}))
    (project / "runs" / "data-inventory.json").write_text('{"items": []}')
    flow = flowgate.load()
    flow.approval.approve(project)
    ctx = flow.states.FlowContext(project=project)
    ctx.state = flow.states.State.FAILED
    ctx.selected_kis = ["M"]
    ctx.save()
    yield project, root
    inv._STOPS.clear()
    inv._RUNNING.clear()


def new(case):
    project, root = case
    return inv.create(project, {"id": "abc", "goal": "Check this failed reader"}, {"M": root}, "deepseek")


def reviewer(role, context, digest, stop, emit):
    return {"status": "completed", "summary": "Read the pinned reader.", "context_digest": digest,
            "findings": [{"category": "reader", "severity": "medium", "claim": "Review the conversion",
                          "evidence": ["kis/M/tools/reader.py"], "recommendation": "Add a regression."}],
            "tests_not_run": ["Native model and reader regression"], "uncertainties": []}


def draft(case):
    project, _ = case
    job = new(case)
    inv.run_reviews(project, job["id"], reviewer)
    return inv.create_draft(project, job["id"], "M")


def accepted(monkeypatch):
    # Test-only deterministic gate fixture; production always calls real KDT.
    def verify(root, *, kind, desktop, name):
        return gate._seal(root, {"ok": True, "gate_policy": gate.GATE_POLICY,
            "kind": kind, "desktop_requested": desktop,
            "doctor_policy": doctor.VALIDATION_POLICY_VERSION,
            "engine_policy": kdtstudio.REVIEWED_COMMIT,
            "engine_source_digest": "e" * 64, "engine_override": False,
            "candidate_digest": gate.content_digest(root)})
    monkeypatch.setattr(gate, "verify_candidate", verify)


def verified(case, monkeypatch):
    accepted(monkeypatch)
    job = draft(case)
    (Path(job["draft"]["path"]) / "tools/reader.py").write_text("def read(): return 2\n")
    return inv.verify_draft(case[0], job["id"])


def test_packet_has_full_history_and_explicit_binary_large_omissions(case, monkeypatch):
    project, _ = case
    (project / "inputs/raw.bin").write_bytes(b"\0\xff")
    (project / "inputs/large.dat").write_bytes(b"x" * 100)
    monkeypatch.setattr(inv, "MAX_TEXT_BYTES", 90)
    job = new(case)
    packet = Path(job["context"]["root"])
    manifest = json.loads((packet / "manifest.json").read_text())
    rows = {r["path"]: r for r in manifest["files"]}
    assert rows["project/inputs/raw.bin"]["omitted"] == "binary_inventory_only"
    assert rows["project/inputs/large.dat"]["omitted"] == "large_file_inventory_only"
    assert rows["project/memory/transcript.jsonl"]["omitted"] == "large_file_inventory_only"
    assert job["context"]["omission_count"] >= 3
    assert kdtstudio.tree_digest(packet) == job["context"]["digest"]


def test_normal_packet_does_not_truncate_full_transcript(case):
    job = new(case)
    assert (Path(job["context"]["root"]) / "project/memory/transcript.jsonl").read_text().count("old message") == 25


def test_credentials_redacted_before_packet_or_public_result(case, monkeypatch):
    project, _ = case
    token = "gfd_" + "A" * 35
    secret = "private-env-value-12345"
    monkeypatch.setenv("CUSTOM_API_KEY", secret)
    (project / "memory/transcript.jsonl").write_text(f"token: {token}\nBearer ABCD00000000000\n{secret}\nAuthorization: Basic dont-send-this\n")
    (project / ".env").write_text("PASSWORD=never-copy-this")
    job = inv.create(project, {"id": "abc", "api_key": secret, "token": "unprefixed-secret"},
                     {"M": case[1]}, "deepseek", issue=token)
    combined = "\n".join(p.read_text() for p in Path(job["context"]["root"]).rglob("*") if p.is_file())
    assert all(value not in combined for value in (token, secret, "ABCD00000000000", "never-copy-this",
                                                   "dont-send-this", "unprefixed-secret"))
    assert token not in json.dumps(job)
    assert "[redacted]" in combined


def test_packet_redacts_complete_quoted_credentials_and_json_headers(case):
    project, _ = case
    json_secrets = {
        "password": 'two words and an escaped "quote"',
        "headers": {"cookie": "session=example-cookie; other=another-cookie",
                    "Set-Cookie": "sid=private-cookie; HttpOnly",
                    "Authorization": "Basic example-auth-value",
                    "X-CSRF-Token": "example-csrf-value"},
        "nested": [{"token": "unprefixed multiline\nsecond secret line"}],
    }
    (project / "inputs/config.json").write_text(json.dumps(json_secrets), encoding="utf-8")
    (project / "runs/quoted.log").write_text(
        'password = "complete phrase with spaces"\n'
        '{"cookie": "log-cookie-private"}\n'
        "password = 'single quoted phrase'\n", encoding="utf-8")
    job = new(case)
    packet = Path(job["context"]["root"])
    config = json.loads((packet / "project/inputs/config.json").read_text(encoding="utf-8"))
    assert config["password"] == "[redacted]"
    assert set(config["headers"].values()) == {"[redacted]"}
    assert config["nested"][0]["token"] == "[redacted]"
    log = (packet / "project/runs/quoted.log").read_text(encoding="utf-8")
    assert "phrase" not in log and "log-cookie-private" not in log
    for row in json.loads((packet / "manifest.json").read_text())["files"]:
        if row["path"] in {"project/inputs/config.json", "project/runs/quoted.log"}:
            assert row["redacted"]


def test_three_independent_invocations_same_frozen_context(case):
    job = new(case)
    barrier = threading.Barrier(3)
    calls = []
    def run(role, context, digest, stop, emit):
        calls.append((role, context, digest))
        barrier.wait(timeout=4)
        return reviewer(role, context, digest, stop, emit)
    result = inv.run_reviews(case[0], job["id"], run)
    assert result["status"] == "reviewed"
    assert {c[0] for c in calls} == set(inv.ROLES)
    assert len({(c[1], c[2]) for c in calls}) == 1
    assert result["combined_report"]["native_verified"] is False
    assert len(result["combined_report"]["findings"]) == 3
    for name in ("capture.json", "before-reviews.json", "after-reviews.json"):
        assert inv._read_signed(inv._root(case[0], job["id"]) / name)


@pytest.mark.parametrize("status", ["failed", "cancelled", "unsupported"])
def test_incomplete_review_is_not_success_or_draft_eligible(case, status):
    job = new(case)
    def run(role, *args):
        return {"status": status, "error": "no provider"} if role == inv.ROLES[0] else reviewer(role, *args)
    result = inv.run_reviews(case[0], job["id"], run)
    assert result["status"] == "review_failed"
    with pytest.raises(inv.InvestigationError, match="three reviews"):
        inv.create_draft(case[0], job["id"], "M")


def test_report_cannot_cite_live_project_or_claim_native_authority(case):
    job = new(case)
    def run(role, *args):
        result = reviewer(role, *args)
        result["findings"][0]["evidence"] = [str(case[1] / "SKILL.md")]
        return result
    assert inv.run_reviews(case[0], job["id"], run)["status"] == "review_failed"


def test_model_claim_cannot_manufacture_native_verification(case):
    job = new(case)
    def run(role, *args):
        result = reviewer(role, *args)
        result.update(native_verified=True, native_execution_verified=True)
        return result
    result = inv.run_reviews(case[0], job["id"], run)
    assert all(not row["report"]["native_verified"] and
               not row["report"]["native_execution_verified"] for row in result["reviewers"])


def test_uncited_findings_do_not_pass_host_report_validation(case):
    job = new(case)
    def run(role, *args):
        result = reviewer(role, *args)
        result["findings"][0]["evidence"] = []
        return result
    assert inv.run_reviews(case[0], job["id"], run)["status"] == "review_failed"


def test_review_context_mutation_fails_closed(case):
    job = new(case)
    def run(role, context, *args):
        if role == inv.ROLES[0]:
            (context / "kis/M/tools/reader.py").write_text("altered context")
        return reviewer(role, context, *args)
    assert inv.run_reviews(case[0], job["id"], run)["status"] == "stale"


def test_live_project_change_during_reviews_is_stale(case):
    job = new(case)
    def run(role, *args):
        if role == inv.ROLES[0]:
            (case[0] / "inputs/data.csv").write_text("changed")
        return reviewer(role, *args)
    assert inv.run_reviews(case[0], job["id"], run)["status"] == "stale"


def test_cancel_is_observed_by_all_reviewers(case):
    job = new(case)
    barrier = threading.Barrier(3)
    def run(role, context, digest, stop, emit):
        barrier.wait(timeout=4)
        if role == inv.ROLES[0]:
            inv.cancel(case[0], job["id"])
        assert stop.wait(4)
        return {"status": "cancelled"}
    assert inv.run_reviews(case[0], job["id"], run)["status"] == "cancelled"


def test_signed_job_edit_and_wrong_project_are_refused(case, tmp_path):
    job = new(case)
    other = tmp_path / "another"
    other.mkdir()
    with pytest.raises(inv.InvestigationError):
        inv.get(other, job["id"])
    path = inv._root(case[0], job["id"]) / "job.json"
    doc = json.loads(path.read_text())
    doc["status"] = "verified"
    path.write_text(json.dumps(doc))
    with pytest.raises(inv.InvestigationError, match="unauthenticated"):
        inv.get(case[0], job["id"])


def test_draft_is_exact_separate_ki_with_review_evidence(case):
    job = draft(case)
    root = Path(job["draft"]["path"])
    assert root != case[1] and gate.content_digest(root) == gate.content_digest(case[1])
    assert (root.parent / "evidence/combined-review.json").is_file()
    assert (root.parent / "evidence/investigation/manifest.json").is_file()
    studio = kdtstudio.job(job["draft"]["studio_job_id"])
    assert Path(studio["source"]).is_relative_to(Path(job["context"]["root"]))


def test_authoring_invalidates_old_gate_and_supports_cancellation(case, monkeypatch):
    job = verified(case, monkeypatch)
    started = inv.mark_authoring(case[0], job["id"])
    assert started["status"] == "authoring" and started["verification"] is None
    stop = inv.stop_event(case[0], job["id"])
    inv.cancel(case[0], job["id"])
    assert stop.is_set()
    assert inv.mark_authored(case[0], job["id"])["status"] == "cancelled"


def test_failed_kdt_never_enables_apply(case, monkeypatch):
    job = draft(case)
    monkeypatch.setattr(gate, "verify_candidate", lambda *a, **k: {"ok": False, "failures": ["missing contract"]})
    result = inv.verify_draft(case[0], job["id"])
    assert result["status"] == "verification_failed" and not result["can_apply"]


def test_engine_failure_clears_old_acceptance(case, monkeypatch):
    job = verified(case, monkeypatch)
    def broken(*a, **k):
        raise RuntimeError("Install the reviewed KDT engine")
    monkeypatch.setattr(gate, "verify_candidate", broken)
    with pytest.raises(RuntimeError, match="reviewed KDT"):
        inv.verify_draft(case[0], job["id"])
    assert not inv.get(case[0], job["id"])["can_apply"]


def test_async_verification_status_and_single_dispatch(case, monkeypatch):
    accepted(monkeypatch)
    job = draft(case)
    started = inv.mark_verifying(case[0], job["id"])
    assert started["status"] == "verifying"
    result = inv.verify_draft(case[0], job["id"])
    assert result["verification"]["id"] == started["verification"]["id"]


@pytest.mark.parametrize("operation", ["authoring", "verifying"])
def test_abandoned_edit_or_verify_preserves_draft_and_can_explicitly_retry(case, monkeypatch, operation):
    accepted(monkeypatch)
    job = draft(case)
    start = inv.mark_authoring if operation == "authoring" else inv.mark_verifying
    start(case[0], job["id"])
    inv._RUNNING.clear()  # Model a fresh host process, not a user cancellation.
    inv._STOPS.clear()
    interrupted = inv.get(case[0], job["id"])
    assert interrupted["status"] == "interrupted" and interrupted["retryable"]
    assert interrupted["interrupted_operation"] == operation
    assert Path(interrupted["draft"]["path"]).is_dir()
    resumed = start(case[0], job["id"])
    assert resumed["status"] == operation and not resumed.get("interrupted")
    if operation == "authoring":
        assert inv.mark_authored(case[0], job["id"])["status"] == "draft"
    else:
        assert inv.verify_draft(case[0], job["id"])["status"] == "verified"


def test_abandoned_apply_requires_recovery_and_cannot_retry(case, monkeypatch):
    job = verified(case, monkeypatch)
    doc = inv._load(case[0], job["id"])
    doc.update(status="applying", apply={"status": "adopted"})
    inv._save(case[0], doc)
    result = inv.get(case[0], job["id"])
    assert result["status"] == "recovery_required" and not result["retryable"]
    assert not result["can_apply"]
    with pytest.raises(inv.InvestigationError, match="exact current"):
        inv.apply(case[0], job["id"], job["verification"]["id"])


def test_transient_source_read_failure_does_not_revoke_approval(case, monkeypatch):
    job = verified(case, monkeypatch)
    def unreadable(*args):
        raise PermissionError("file temporarily unavailable")
    monkeypatch.setattr(inv, "_source_state", unreadable)
    with pytest.raises(inv.InvestigationError, match="Cannot recheck"):
        inv.apply(case[0], job["id"], job["verification"]["id"])
    assert flowgate.load().approval.check(case[0]) == "OK"


@pytest.mark.parametrize("change", ["project", "draft", "engine"])
def test_stale_repair_refused_before_revoking_approval(case, monkeypatch, change):
    job = verified(case, monkeypatch)
    if change == "project":
        (case[0] / "inputs/data.csv").write_text("new input")
    elif change == "draft":
        (Path(job["draft"]["path"]) / "SKILL.md").write_text("edited after verify")
    else:
        monkeypatch.setattr(kdtstudio, "engine_source_digest", lambda: "f" * 64)
    with pytest.raises(ValueError):
        inv.apply(case[0], job["id"], job["verification"]["id"])
    assert flowgate.load().approval.check(case[0]) == "OK"


def test_wrong_verification_id_and_active_worker_cannot_apply(case, monkeypatch):
    job = verified(case, monkeypatch)
    with pytest.raises(inv.InvestigationError, match="exact current"):
        inv.apply(case[0], job["id"], "old-report")
    with ki_guard.worker(case[1]), pytest.raises(ki_guard.KIIntegrityError, match="worker"):
        inv.apply(case[0], job["id"], job["verification"]["id"])
    assert flowgate.load().approval.check(case[0]) == "OK"


def test_apply_preserves_history_revokes_approval_and_demands_fresh_project_preflight(case, monkeypatch):
    project, root = case
    (project / "runs/old-failed.json").write_text('{"historical": true}')
    job = verified(case, monkeypatch)
    before = (root / "tools/reader.py").read_text()
    result = inv.apply(project, job["id"], job["verification"]["id"])
    assert result["status"] == "applied" and result["apply"]["requires_plan_review"]
    assert flowgate.load().approval.check(project) == "MISSING"
    assert flowgate.load().states.FlowContext.load(project).state.value == "REPLAN_REQUIRED"
    assert (root / "tools/reader.py").read_text() == "def read(): return 2\n"
    assert any((p / "tools/reader.py").read_text() == before for p in root.parent.glob("ki-previous-*"))
    assert (project / "runs/old-failed.json").read_text() == '{"historical": true}'
    pending = inv.pending_preflight(project)
    assert pending["pending"] and not pending["kis"]["M"]["passed"]
    with pytest.raises(inv.InvestigationError, match="revision"):
        inv.record_preflight(project, "M", "old-digest", True)
    assert inv.record_preflight(project, "M", gate.content_digest(root), False)["pending"]
    assert not inv.record_preflight(project, "M", gate.content_digest(root), True)["pending"]


def test_dirty_recorded_source_preserved_only_on_explicit_apply(case, monkeypatch):
    project, root = case
    (root / "SKILL.md").write_text("unverified edit kept for review")
    # The edited KI does not touch the approved executable, so original plan
    # approval remains authentic until explicit apply revokes it.
    job = verified(case, monkeypatch)
    assert (root / "SKILL.md").read_text() == "unverified edit kept for review"
    result = inv.apply(project, job["id"], job["verification"]["id"])
    recovered = Path(result["apply"]["recovered_draft"])
    assert (recovered / "SKILL.md").read_text() == "unverified edit kept for review"
    ki_guard.require_intact(root)


def test_global_catalogue_candidate_cannot_be_applied(case, monkeypatch, tmp_path):
    project, _ = case
    global_root = tmp_path / "catalogue" / "M"
    global_root.mkdir(parents=True)
    (global_root / "SKILL.md").write_text("global")
    (global_root / "tools").mkdir()
    (global_root / "tools/reader.py").write_text("global reader")
    ki_guard.enroll(global_root)
    job = inv.create(project, {"id": "abc"}, {"M": global_root}, "deepseek")
    inv.run_reviews(project, job["id"], reviewer)
    inv.create_draft(project, job["id"], "M")
    accepted(monkeypatch)
    job = inv.verify_draft(project, job["id"])
    assert not job["can_apply"]
    with pytest.raises(inv.InvestigationError, match="project-local"):
        inv.apply(project, job["id"], job["verification"]["id"])
    assert (global_root / "SKILL.md").read_text() == "global"


def test_adoption_failure_has_recovery_journal_no_old_approval_replay(case, monkeypatch):
    job = verified(case, monkeypatch)
    def broken(*a, **k):
        assert inv.pending_preflight(case[0])["pending"]
        live = inv.get(case[0], job["id"])
        assert live["status"] == "applying" and not live.get("interrupted")
        raise OSError("simulated locked destination")
    monkeypatch.setattr(ki_guard, "activate", broken)
    with pytest.raises(inv.InvestigationError, match="old approval remains revoked"):
        inv.apply(case[0], job["id"], job["verification"]["id"])
    result = inv.get(case[0], job["id"])
    assert result["status"] == "apply_failed"
    assert result["apply"]["status"] == "needs_recovery"
    assert flowgate.load().approval.check(case[0]) == "MISSING"
    assert (case[1] / "tools/reader.py").read_text() == "def read(): return 1\n"


def test_latest_applied_survives_newer_review_without_rehashing_live_data(case, monkeypatch):
    assert inv.latest_applied(case[0]) is None
    job = verified(case, monkeypatch)
    applied = inv.apply(case[0], job["id"], job["verification"]["id"])
    newer = new(case)
    assert inv.get(case[0])["id"] == newer["id"]
    def forbidden(*args, **kwargs):
        raise AssertionError("Recovery lookup must not scan data or candidate bytes")
    monkeypatch.setattr(inv, "_source_state", forbidden)
    monkeypatch.setattr(gate, "content_digest", forbidden)
    recovered = inv.latest_applied(case[0])
    assert recovered["id"] == applied["id"]
    assert recovered["apply"]["generation"] == applied["apply"]["generation"]
    assert recovered["apply"]["applied_at"] > 0
    assert Path(recovered["report_path"]).is_file()


def test_latest_applied_rejects_forged_success_record(case):
    job = new(case)
    path = inv._root(case[0], job["id"]) / "job.json"
    doc = json.loads(path.read_text())
    doc.update(status="applied", apply={"status": "complete", "generation": "forged"})
    path.write_text(json.dumps(doc))
    with pytest.raises(inv.InvestigationError, match="unauthenticated"):
        inv.latest_applied(case[0])


def test_author_report_is_redacted_bounded_plain_text(case, monkeypatch):
    job = draft(case)
    inv.mark_authoring(case[0], job["id"])
    token = "gfd_" + "s" * 30
    text = '<script>alert("example")</script>\n' + token + "\0\n" + "x" * 20_000
    result = inv.mark_authored(case[0], job["id"], author_report=text)
    assert token not in result["author_report"] and "\0" not in result["author_report"]
    assert result["author_report"].startswith('<script>alert("example")</script>')
    assert result["author_report_meta"]["format"] == "plain_text"
    assert result["author_report_meta"]["truncated"]
    assert result["author_report_meta"]["original_chars"] > inv.MAX_AUTHOR_REPORT_CHARS
    assert len(result["author_report"]) <= inv.MAX_AUTHOR_REPORT_CHARS
    assert result["author_report_meta"]["candidate_digest"] == result["draft"]["current_digest"]
    assert result["verification"] is None and not result["can_apply"]
    persisted = inv._load(case[0], job["id"])
    assert persisted["author_report"] == result["author_report"]


def test_verified_diff_is_host_computed_added_modified_removed(case, monkeypatch):
    (case[1] / "tools/obsolete.py").write_text("obsolete original")
    job = draft(case)
    candidate = Path(job["draft"]["path"])
    (candidate / "tools/obsolete.py").unlink()
    (candidate / "tools/reader.py").write_text("different bytes")
    (candidate / "tools/new.py").write_text("new helper")
    accepted(monkeypatch)
    result = inv.verify_draft(case[0], job["id"])
    changes = result["verification"]["changes"]
    assert changes["added"] == ["tools/new.py"]
    assert changes["modified"] == ["tools/reader.py"]
    assert changes["removed"] == ["tools/obsolete.py"]
    assert changes["counts"] == {"added": 1, "modified": 1, "removed": 1}
    assert changes["candidate_digest"] == result["verification"]["candidate_digest"]
    assert changes["baseline_digest"] == job["draft"]["base_digest"]
    assert changes["complete"] and not changes["truncated"]
    assert "changes" not in result["verification"]["report"]  # shared KDT signature untouched
    gate.require_current(candidate, result["verification"]["report"])


def test_change_inventory_has_explicit_truncation_and_uncompared_cache_paths(case, monkeypatch):
    (case[1] / "__pycache__").mkdir()
    (case[1] / "__pycache__/old.pyc").write_bytes(b"old")
    job = draft(case)
    candidate = Path(job["draft"]["path"])
    for name in ("a", "b", "c"):
        (candidate / (name + ".txt")).write_text(name)
    accepted(monkeypatch)
    monkeypatch.setattr(inv, "MAX_CHANGE_FILES", 1)
    changes = inv.verify_draft(case[0], job["id"])["verification"]["changes"]
    assert changes["counts"]["added"] == 3 and len(changes["added"]) == 1
    assert changes["truncated"] and changes["limit_per_list"] == 1
    assert not changes["complete"] and changes["uncompared_baseline_paths"] == ["__pycache__"]


def test_candidate_mutation_during_diff_does_not_publish_verified_changes(case, monkeypatch):
    job = draft(case)
    accepted(monkeypatch)
    original = inv._candidate_changes
    def mutate(doc, candidate, digest):
        changes = original(doc, candidate, digest)
        (candidate / "tools/reader.py").write_text("changed after comparison")
        return changes
    monkeypatch.setattr(inv, "_candidate_changes", mutate)
    with pytest.raises(inv.InvestigationError, match="repair diff"):
        inv.verify_draft(case[0], job["id"])
    result = inv.get(case[0], job["id"])
    assert result["status"] == "verification_failed" and not result["can_apply"]
