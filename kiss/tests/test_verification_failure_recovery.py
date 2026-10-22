"""Real portable-registration failures through GUI workers; KDT is a sealed fixture."""
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from kiss_cli import flowgate, gui, ki_investigation as inv, ki_verification as gate
from .test_ki_investigation import case, portable_case, draft, accepted
from .test_investigation_ui import evaluate


RECIPE_ERROR = "Reusable repair changes the effective installation recipe"


@pytest.fixture
def web_case(portable_case, monkeypatch):
    pair, library, cfg = portable_case
    project, live = pair
    accepted(monkeypatch)
    job = draft(pair)
    candidate = Path(job["draft"]["path"])
    # Invoke real prepare_registration/_same_recipe after sealed KDT fixture
    # checks; this is an actual unsupported installation change, not a run.
    (candidate / "kiss.yaml").write_text(
        "kiss_manifest_version: 1\nmodel: M\npython_deps: ['new-package']\n", encoding="utf-8")
    session = {"id": "123456abcdef", "models": ["M"], "provider": "api:deepseek"}
    handler = object.__new__(gui.Handler)
    handler.workroot = project.parent
    handler._json = lambda body, code=200: (body, code)
    monkeypatch.setattr(gui.sessions, "load", lambda *_: session)
    monkeypatch.setattr(gui.sessions, "project_path", lambda *_: project)
    monkeypatch.setattr(gui, "_PROJECT_OPERATIONS", {})
    monkeypatch.setattr(gui, "_agent_run_snapshot", lambda *_: {})
    monkeypatch.setattr(gui.project_status, "snapshot", lambda *_: {"progress": {}})
    monkeypatch.setattr(gui.ki_review_agents, "capability", lambda *_: {"supported": True})
    monkeypatch.setattr(inv, "rejected_update_sources", lambda *_: [])
    threads = []
    class HeldThread:
        def __init__(self, *, target, **kwargs): threads.append(target)
        def start(self): pass
    monkeypatch.setattr(gui, "threading", SimpleNamespace(Thread=HeldThread))
    return SimpleNamespace(project=project, live=live, candidate=candidate, job=job,
        handler=handler, session=session, threads=threads)


def action(c, verb):
    return c.handler._project_investigation(c.session["id"], action=verb,
        job_id=c.job["id"], req={})


def fail_verification(c):
    response, code = action(c, "verify")
    assert code == 202, response
    assert response["busy"] and c.session["id"] in gui._PROJECT_OPERATIONS
    c.threads.pop(0)()
    saved = inv.get(c.project, c.job["id"])
    assert saved["status"] == "verification_failed" and RECIPE_ERROR in saved["error"]
    assert saved["verification"]["ok"] is False and not saved["can_apply"]
    assert saved["verification"]["error"] == saved["error"]
    assert not inv._RUNNING and c.session["id"] not in gui._PROJECT_OPERATIONS
    return saved


def legacy_failure(c):
    fail_verification(c)
    doc = inv._load(c.project, c.job["id"])
    doc.update(status="failed", verification=None)
    inv._save(c.project, doc)
    return inv.get(c.project, c.job["id"])


def test_real_registration_failure_remains_visible_and_unlocked(web_case):
    c = web_case
    before = gate.content_digest(c.live)
    saved = fail_verification(c)
    body, code = c.handler._project_investigation(c.session["id"])
    assert code == 200 and not body["busy"] and body["available"]
    repair = body["job"]["repair"]
    assert repair["can_verify"] and repair["retryable"] and not repair["can_apply"]
    assert repair["failure_phase"] == "verification"
    assert RECIPE_ERROR in repair["blocked_reason"]
    assert gate.content_digest(c.live) == before
    assert flowgate.load().approval.check(c.project) == "OK"
    with pytest.raises(ValueError, match="exact current verification"):
        inv.apply(c.project, c.job["id"], saved["verification"]["id"])


@pytest.mark.parametrize("legacy", [False, True])
def test_new_attempt_rechecks_candidate_then_only_offers_guarded_apply(web_case, legacy):
    c = web_case
    failed = legacy_failure(c) if legacy else fail_verification(c)
    if legacy:
        assert failed["can_recover_failed_draft"] and failed["verification"] is None
    # The unchanged bad candidate still fails a completely new attempt.
    again = fail_verification(c)
    if failed.get("verification"):
        assert again["verification"]["id"] != failed["verification"]["id"]
    # Removing the unsupported test-only addition permits a fresh full check.
    (c.candidate / "kiss.yaml").unlink()
    response, code = action(c, "verify")
    assert code == 202 and response["job"]["status"] == "verifying"
    assert not response["job"]["repair"]["can_apply"]
    c.threads.pop(0)()
    saved = inv.get(c.project, c.job["id"])
    assert saved["status"] == "verified" and saved["verification"]["ok"]
    assert saved["verification"]["id"] != again["verification"]["id"]
    assert "error" not in saved and saved["can_apply"]
    assert not saved["apply"] and flowgate.load().approval.check(c.project) == "OK"


@pytest.mark.parametrize("legacy", [False, True])
def test_build_preserves_actual_error_as_context_but_clears_old_authority(web_case, monkeypatch, legacy):
    c = web_case
    failed = (legacy_failure if legacy else fail_verification)(c)
    old = (failed.get("verification") or {}).get("id")
    seen = []
    monkeypatch.setattr(gui.ki_review_agents, "author_draft", lambda *args, **kw:
        seen.append(kw) or {"status": "completed", "raw_response": "Draft edited; checks pending."})
    body, code = action(c, "build")
    assert code == 202 and body["job"]["status"] == "authoring"
    assert not body["job"]["repair"]["can_apply"]
    c.threads.pop(0)()
    assert RECIPE_ERROR in seen[0]["task_extra"]
    saved = inv.get(c.project, c.job["id"])
    # A build runs the host's automatic repair rounds. The unchanged bad
    # candidate fails fresh checks; the earlier verification never carries over.
    assert saved["status"] == "verification_failed" and not saved["can_apply"]
    assert saved["verification"] and saved["verification"]["id"] != old
    assert len(saved["auto_repair"]["rounds"]) == inv.AUTO_REPAIR_ROUNDS


@pytest.mark.parametrize("verb", ["build", "verify"])
@pytest.mark.parametrize("damage", ["source", "context", "candidate", "review", "studio", "signature"])
def test_legacy_failed_recovery_cannot_bypass_current_source_or_draft_identity(web_case, verb, damage):
    c = web_case
    legacy_failure(c)
    doc = inv._load(c.project, c.job["id"])
    if damage == "source":
        (c.live / "tools/reader.py").write_text("changed live source", encoding="utf-8")
    elif damage == "context":
        (Path(doc["context"]["root"]) / "manifest.json").write_text("changed context", encoding="utf-8")
    elif damage == "candidate":
        (c.candidate / "tools/reader.py").unlink()
        # An existing foreign tree still must not replace the Studio candidate.
        doc["draft"]["path"] = str(c.live)
        inv._save(c.project, doc)
    elif damage == "review":
        doc["reviewers"][0]["report"]["context_digest"] = "another-context"
        inv._save(c.project, doc)
    elif damage == "studio":
        doc["draft"]["studio_job_id"] = "a" * 12
        inv._save(c.project, doc)
    else:
        path = inv._root(c.project, c.job["id"]) / "job.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["error"] = "unauthenticated edit"
        path.write_text(json.dumps(raw), encoding="utf-8")
    body, code = action(c, verb)
    assert code == 409 and body.get("error")
    assert not c.threads and not inv._RUNNING and not gui._PROJECT_OPERATIONS
    assert flowgate.load().approval.check(c.project) == ("DRIFT" if damage == "source" else "OK")


@pytest.mark.parametrize("state", ["cancelled", "apply_failed", "applied", "applying"])
def test_unrelated_terminal_states_never_gain_recovery(web_case, state):
    c = web_case
    doc = inv._load(c.project, c.job["id"])
    doc["status"] = state
    inv._save(c.project, doc)
    inv.fail(c.project, c.job["id"], "worker cleanup")
    saved = inv.get(c.project, c.job["id"])
    assert not saved["can_recover_failed_draft"] and not saved["can_apply"]
    assert action(c, "verify")[1] == 409
    assert action(c, "build")[1] == 409


@pytest.mark.parametrize("zh", [False, True])
def test_gui_polls_until_failed_worker_releases_lease_then_enables_new_check(web_case, zh):
    c = web_case
    saved = fail_verification(c)
    view = gui._investigation_view(saved)
    result = evaluate(zh=zh, reads=[{"job": view, "busy": True, "available": False,
        "reason": "KI investigation is running"}, {"job": view, "busy": False,
        "available": True, "reason": ""}], pollTicks=1)
    nodes = result["nodes"]
    assert not nodes["#investigation-build"]["disabled"]
    assert not nodes["#investigation-verify"]["disabled"]
    assert nodes["#investigation-apply"]["disabled"] and result["timers"] == 0
    assert RECIPE_ERROR in nodes["#investigation-report"]["html"]
    assert ("验证失败" if zh else "Verification failed") in nodes["#investigation-report"]["html"]
    assert not result["resumes"] and not [r for r in result["requests"] if r["method"] == "POST"]
