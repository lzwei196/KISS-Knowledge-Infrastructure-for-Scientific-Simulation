"""Maintenance route selects host evidence; caller JSON never provides it."""
from types import SimpleNamespace

from kiss_cli import gui, ki_investigation as inv
from .test_gui_investigation import case
from .test_ki_investigation import reviewer
from .test_investigation_maintenance import maintenance


def test_gui_draft_chooses_mode_without_accepting_caller_evidence(case, maintenance):
    job = inv.create(case.project, case.session, {"M": case.root}, "api:deepseek", issue="Fix inventory")
    inv.run_reviews(case.project, job["id"], reviewer)
    body, status = case.handler._project_investigation(case.session["id"], action="draft", job_id=job["id"], req={
        "ki_name": "M", "repair_mode": "maintenance", "maintenance_recipe": "tool_inventory",
        "maintenance_source": {"ok": True, "scope": "official_published_package"},
        "report": {"ok": True, "state": "MaintenanceVerified"}})
    assert status == 200, body
    assert body["job"]["repair"]["repair_mode"] == "maintenance"
    stored = inv._load(case.project, job["id"])
    assert stored["draft"]["maintenance_source"]["fixture"] is True
    assert stored["verification"] is None and body["job"]["can_apply"] is False


def test_rejected_start_uses_server_resolved_source_and_never_legacy_catalogue(case, monkeypatch):
    observed = {}
    opaque = "a" * 64
    resolved = {"id": opaque, "name":"M", "root":str(case.root), "report":{"host_fixture":True}}
    def resolve(identity, names):
        assert identity == opaque and names == ["M"]
        return resolved
    def create(project, session, roots, provider, model, issue, *, publication_sources):
        observed.update(roots=roots, evidence=publication_sources)
        return {"id":"b"*16, "status":"created", "ki_roots":{"M":str(case.root)}}
    class HeldThread:
        def __init__(self, **kwargs):pass
        def start(self):pass
    monkeypatch.setattr(inv, "resolve_rejected_update_source", resolve)
    monkeypatch.setattr(inv, "create", create)
    monkeypatch.setattr(gui, "threading", SimpleNamespace(Thread=HeldThread))
    case.handler._investigation_roots=lambda *args: (_ for _ in ()).throw(AssertionError("Do not resolve broken legacy KI"))
    body,status=case.handler._project_investigation(case.session["id"],action="start",req={
        "source_id":opaque,"provider":"api:deepseek","issue":"Check inactive update",
        "root":"attacker/path","publication_sources":{"M":{"fake":True}}})
    assert status == 202,body
    assert observed == {"roots":{"M":case.root},"evidence":{"M":{"host_fixture":True}}}

