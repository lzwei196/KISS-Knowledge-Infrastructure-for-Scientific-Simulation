"""Repair drafts get their own tests run and failures returned automatically."""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from kiss_cli import ki_candidate_checks, ki_investigation, paths


def candidate(tmp_path, body=None):
    root = tmp_path / "candidate"
    (root / "tests").mkdir(parents=True)
    (root / "SKILL.md").write_text("# KI\n", encoding="utf-8")
    if body is not None:
        (root / "tests" / "test_reader.py").write_text(body, encoding="utf-8")
    return root


PASSING = """import unittest
class Reader(unittest.TestCase):
    def test_reads(self):
        self.assertEqual(1 + 1, 2)
"""
FAILING = """import unittest
class Reader(unittest.TestCase):
    def test_valid_range(self):
        self.assertEqual("valid_range refused", "accepted")
"""


@pytest.fixture
def cfg(tmp_path):
    cfg = paths.KissConfig.default(tmp_path / "runtime")
    cfg.python = sys.executable
    return cfg


def test_passing_draft_tests_are_reported_as_feedback(tmp_path, cfg):
    result = ki_candidate_checks.run(candidate(tmp_path, PASSING), cfg)
    assert result["ran"] and result["ok"] is True and result["tests_run"] == 1
    assert result["assurance"] == "feedback_only_not_acceptance"


def test_failing_draft_tests_return_their_output(tmp_path, cfg):
    root = candidate(tmp_path, FAILING)
    before = (root / "tests" / "test_reader.py").read_bytes()
    result = ki_candidate_checks.run(root, cfg)
    assert result["ran"] and result["ok"] is False and result["failed"] == 1
    assert "valid_range refused" in result["output_tail"]
    # Tests run on an isolated copy; the draft itself is untouched.
    assert (root / "tests" / "test_reader.py").read_bytes() == before
    assert not list(root.rglob("__pycache__"))


def test_no_tests_is_not_a_pass_or_a_failure(tmp_path, cfg):
    result = ki_candidate_checks.run(candidate(tmp_path), cfg)
    assert result["ran"] is False and result["ok"] is None


def test_credentials_do_not_reach_draft_tests(tmp_path, cfg, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-not-for-tests")
    body = ("import os, unittest\nclass Env(unittest.TestCase):\n"
            "    def test_env(self):\n        self.assertNotIn('DEEPSEEK_API_KEY', os.environ)\n")
    assert ki_candidate_checks.run(candidate(tmp_path, body), cfg)["ok"] is True


def test_feedback_carries_test_output_and_kdt_failures():
    text = ki_investigation.auto_repair_feedback(
        1, {"status": "author_failed", "error": "Repair author reported incomplete: inventory unfinished"},
        {"ran": True, "runner": "unittest", "command": "-m unittest", "status": "failed", "tests_run": 3,
         "failed": 1, "errors": 0, "output_tail": "AssertionError: valid_range refused"},
        {"ok": False, "report": {"failures": ["tool count 19 != 21"], "warnings": []}})
    assert "pass 1 of" in text and "inventory unfinished" in text
    assert "valid_range refused" in text and "tool count 19 != 21" in text
    # Existing KI tests are protected; a test written in this draft may be corrected.
    assert "already exist in the KI must keep passing unchanged: never weaken or delete them" in text
    assert "A test you added in this draft may be corrected" in text


def test_feedback_carries_blocking_desktop_findings():
    # KDT itself passed; the desktop doctor alone refused the candidate.
    report = {"ok": False, "failures": [], "warnings": [], "kdt": {"ok": True}, "desktop": {"ok": False, "findings": [
        {"severity": "WARN", "check": "no-manifest", "detail": "no kiss.yaml"},
        {"severity": "BLOCK", "check": "possible-secret",
         "detail": "credential-shaped string in tests/test_install_contract.py"}]}}
    text = ki_investigation.auto_repair_feedback(3, {"status": "draft"}, {"ran": True, "ok": True},
                                                 {"ok": False, "report": report})
    assert "KDT verification failed" in text
    assert "possible-secret" in text and "tests/test_install_contract.py" in text
    assert "no kiss.yaml" not in text


def test_feedback_never_drops_an_unexplained_kdt_refusal():
    text = ki_investigation.auto_repair_feedback(1, {"status": "draft"}, {"ran": True, "ok": True},
                                                 {"ok": False, "report": {"failures": [], "warnings": []}})
    assert "KDT verification did not pass" in text


def test_checks_block_uses_the_portable_digest():
    doc = {"draft": {"repair_mode": "authoring"},
           "candidate_checks": {"ran": True, "ok": False, "candidate_digest": "portable"},
           "verification": {"candidate_digest": "runtime", "portable_digest": "portable"}}
    assert "own tests failed" in ki_investigation._candidate_checks_block(doc)
    doc["candidate_checks"]["ok"] = True
    assert ki_investigation._candidate_checks_block(doc) == ""
    doc["draft"]["repair_mode"] = "maintenance"
    doc["candidate_checks"]["ok"] = False
    assert ki_investigation._candidate_checks_block(doc) == ""


class FakeJob:
    """Drive automatic_repair through scripted author, test and KDT outcomes."""

    def __init__(self, monkeypatch, rounds):
        self.rounds, self.calls, self.feedback, self.state = list(rounds), [], [], {"status": "authoring"}
        self.auto = {}
        m = ki_investigation
        monkeypatch.setattr(m, "mark_authoring", lambda *_a: self.calls.append("mark_authoring"))
        monkeypatch.setattr(m, "is_cancelled", lambda *_a: self.state["status"] == "cancelled")
        monkeypatch.setattr(m, "record_auto_repair", self.record)
        monkeypatch.setattr(m, "run_candidate_checks", self.checks)
        monkeypatch.setattr(m, "refresh_projections", self.project)
        monkeypatch.setattr(m, "mark_verifying", lambda *_a: self.calls.append("mark_verifying"))
        monkeypatch.setattr(m, "verify_draft", self.verify)
        monkeypatch.setattr(m, "get", lambda *_a: dict(self.state))
        monkeypatch.setattr(m, "_project", lambda project: Path(project))

    def record(self, *_a, round_entry=None, **state):
        if round_entry:
            self.auto.setdefault("rounds", []).append(round_entry)
        self.auto.update(state)

    def author(self, feedback):
        self.feedback.append(feedback)
        self.current = self.rounds.pop(0)
        if self.current.get("cancel"):
            self.state["status"] = "cancelled"
        else:
            self.state["status"] = "draft" if self.current["author"] else "author_failed"
        return dict(self.state, error="" if self.current["author"] else "reported incomplete")

    def project(self, *_a, **_k):
        regenerated = self.current.get("projected", [])
        return {"ran": True, "errors": [], "regenerated": [
            {"file": name, "reason": "it was edited by hand in this draft", "sources": "dag.yaml",
             "carried_from_baseline": []} for name in regenerated]}

    def checks(self, *_a, **_k):
        self.calls.append("checks")
        ok = self.current["tests"]
        return {"ran": True, "ok": ok, "tests_run": 2, "failed": 0 if ok else 1, "runner": "unittest",
                "output_tail": "" if ok else "FAIL: test_valid_range"}

    def verify(self, *_a):
        self.calls.append("verify")
        self.state["status"] = "verified" if self.current["kdt"] else "verification_failed"
        if self.current.get("job_error"):
            # A refused verification (the portability gate) leaves an empty report and a job error.
            self.state["verification"] = {"ok": False, "report": {"failures": []}}
            self.state["error"] = self.current["job_error"]
        else:
            self.state["verification"] = {"ok": self.current["kdt"],
                                          "report": {"failures": [] if self.current["kdt"] else ["count"]}}
        return dict(self.state)


def test_loop_returns_failures_until_tests_and_kdt_pass(monkeypatch, tmp_path):
    job = FakeJob(monkeypatch, [{"author": False, "tests": False, "kdt": False},
                                {"author": True, "tests": True, "kdt": True}])
    result = ki_investigation.automatic_repair(tmp_path, "job", job.author)
    assert result["status"] == "verified" and job.auto["outcome"] == "verified"
    assert job.feedback[0] == "" and "FAIL: test_valid_range" in job.feedback[1]
    assert "reported incomplete" in job.feedback[1]
    # An incomplete pass is tested but never sent to KDT verification.
    assert job.calls == ["checks", "mark_authoring", "checks", "mark_verifying", "verify"]
    assert [r["author"] for r in job.auto["rounds"]] == ["incomplete", "completed"]


def test_verified_draft_with_failing_tests_is_sent_back(monkeypatch, tmp_path):
    job = FakeJob(monkeypatch, [{"author": True, "tests": False, "kdt": True},
                                {"author": True, "tests": True, "kdt": True}])
    ki_investigation.automatic_repair(tmp_path, "job", job.author)
    assert len(job.feedback) == 2 and "KDT structural verification passed" in job.feedback[1]


def test_loop_stops_after_the_round_limit(monkeypatch, tmp_path):
    rounds = [{"author": True, "tests": False, "kdt": False}] * ki_investigation.AUTO_REPAIR_ROUNDS
    job = FakeJob(monkeypatch, rounds)
    result = ki_investigation.automatic_repair(tmp_path, "job", job.author)
    assert result["status"] == "verification_failed" and job.auto["outcome"] == "rounds_exhausted"
    assert len(job.feedback) == ki_investigation.AUTO_REPAIR_ROUNDS


def test_cancel_stops_the_loop(monkeypatch, tmp_path):
    job = FakeJob(monkeypatch, [{"author": True, "tests": True, "kdt": True, "cancel": True}])
    result = ki_investigation.automatic_repair(tmp_path, "job", job.author)
    assert result["status"] == "cancelled" and job.calls == []


def test_host_unable_to_run_tests_does_not_spin_the_author(monkeypatch, tmp_path):
    job = FakeJob(monkeypatch, [{"author": True, "tests": True, "kdt": True},
                                {"author": True, "tests": True, "kdt": True}])
    def unavailable(*_a, **_k):
        raise RuntimeError("project runtime config missing")
    monkeypatch.setattr(ki_investigation, "run_candidate_checks", unavailable)
    result = ki_investigation.automatic_repair(tmp_path, "job", job.author)
    assert result["status"] == "verified" and len(job.feedback) == 1
    assert job.auto["rounds"][0]["tests_ok"] is None


def test_regenerated_projections_are_reported_to_the_next_pass(monkeypatch, tmp_path):
    job = FakeJob(monkeypatch, [{"author": True, "tests": True, "kdt": False,
                                 "projected": ["docs/format_spec.yaml"]},
                                {"author": True, "tests": True, "kdt": True}])
    ki_investigation.automatic_repair(tmp_path, "job", job.author)
    assert "regenerated docs/format_spec.yaml because it was edited by hand" in job.feedback[1]
    assert "not docs/format_spec.yaml, knowledge_infrastructure.yaml or SKILL.md's generated tool index" in job.feedback[1]
    assert job.auto["rounds"][0]["projected"] == ["docs/format_spec.yaml"]
    assert job.auto["rounds"][1]["projected"] == []


def test_a_refused_verification_reaches_the_author(monkeypatch, tmp_path):
    gate = "Portable repair introduces a machine path in SKILL.md: '/opt/x'; use KI path roles"
    job = FakeJob(monkeypatch, [{"author": True, "tests": True, "kdt": False, "job_error": gate},
                                {"author": True, "tests": True, "kdt": True}])
    ki_investigation.automatic_repair(tmp_path, "job", job.author)
    assert "KDT verification failed" in job.feedback[1] and "'/opt/x'" in job.feedback[1]


def test_a_host_projection_failure_never_counts_as_a_pass(monkeypatch, tmp_path):
    job = FakeJob(monkeypatch, [{"author": True, "tests": True, "kdt": True}])
    def broken(*_a, **_k):
        raise RuntimeError("helper tree missing")
    monkeypatch.setattr(ki_investigation, "refresh_projections", broken)
    result = ki_investigation.automatic_repair(tmp_path, "job", job.author)
    # The draft is still judged by its own tests and KDT; reprojection is feedback only.
    assert result["status"] == "verified" and job.calls[-1] == "verify"
