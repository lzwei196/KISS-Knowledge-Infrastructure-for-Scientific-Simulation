"""Host-owned KDT maintenance for one exact installation workspace.

Provider requests carry an issue, never an adoption path or verification claim.
The caller owns the setup lease and drains provider workers before invoking run.
Original outputs and portable projection records are preserved. A completed
maintenance transaction is not software readiness: normal preflight is required.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import shutil
import sys
import threading
import time
import uuid

from . import (helper_identity, implementation_identity, install_locations,
               ki_adaptations, ki_guard, ki_investigation as investigation,
               ki_verification, setup, software_verification)
from .manifest import document as manifest_document

POLICY = "setup-ki-maintenance-v1"


def recipe_for(ki_name):
    # Capability discovery is explicit; it never guesses a recipe from failure
    # text or claims that every KI has a supported bounded repair yet.
    return "epanet_runtime_paths" if ki_name == "EPANET" else None


def _identity():
    return implementation_identity.module_digest(sys.modules[__name__])


def _hash_file(path):
    return investigation._hash(Path(path))


def _root(root):
    root = Path(root).absolute()
    if root != root.resolve() or not root.is_dir():
        raise ValueError("Setup repair requires the exact unaliased installation workspace")
    return root


def _pointer(root):
    return investigation._base(_root(root)) / "setup-adoption.json"


def _auth(binding):
    receipts = investigation.flowgate.load().receipts
    if (not isinstance(binding, dict) or not receipts.verify(investigation._home(), binding)
            or binding.get("policy") != POLICY or binding.get("implementation") != _identity()):
        raise ValueError("Setup repair binding is missing, unauthenticated or stale")
    return binding


def require_binding(binding, *, live_digest=None):
    """Check source/runtime authority; never refresh the old projection."""
    _auth(binding)
    root = _root(binding["root"])
    active = root / "ki"
    if str(active) != binding.get("active_root"):
        raise ValueError("Setup repair target differs from its installation workspace")
    if _hash_file(root / "kiss.toml") != binding["config_sha256"]:
        raise ValueError("Setup configuration changed after the repair review")
    cfg = setup.load_runtime_config(root)
    if software_verification.runtime_identity(cfg) != binding["runtime_identity"]:
        raise ValueError("Setup runtime binding changed after the repair review")
    origin = ki_adaptations._auth(binding["projection"])
    if ki_adaptations._read(ki_adaptations._location(active)) != origin:
        raise ValueError("Original setup projection changed after the repair review")
    if (origin.get("live_root") != str(active)
            or origin.get("projected_digest") != binding["baseline_digest"]
            or origin.get("runtime_identity") != binding["runtime_identity"]):
        raise ValueError("Setup repair does not match its original projection")
    ki_adaptations._retained(origin["upstream_root"], origin["upstream_digest"])
    ki_adaptations._retained(origin["portable_root"], origin["portable_digest"])
    ki_adaptations.require_path_binding(origin, cfg)
    if origin.get("path_projection") is not None:
        # This tracer supports ordinary/declared role projections. A legacy
        # runtime fingerprint overlay needs its own retained-proof composition.
        raise ValueError("This setup repair requires a supported original path projection")
    if origin.get("portable_report"):
        ki_verification.require_current(Path(origin["portable_root"]), origin["portable_report"])
    source, library = Path(binding["source_root"]), Path(binding["library_root"])
    context = ki_adaptations._context(source, cfg, model=binding["ki_name"],
        library_root=library, manifest=binding["effective_manifest"])
    if context != origin["context"] or context != binding["context"]:
        raise ValueError("Selected KI source, recipe or shared helpers changed after repair review")
    helper = Path(cfg.roles["ki_tools_common"])
    if helper_identity.package_files(helper) != binding["helper_files"]:
        raise ValueError("Prepared shared helper bytes changed after repair review")
    expected = live_digest or binding["baseline_digest"]
    if ki_guard.require_intact(active)["digest"] != expected:
        raise ValueError("Active setup KI differs from the reviewed maintenance revision")
    return cfg


def capture(root, *, ki_name, source_root, library_root, manifest, issue):
    root = _root(root)
    if not isinstance(ki_name, str) or not ki_name or any(x in ki_name for x in ("/", "\\", "\0")):
        raise ValueError("Setup repair requires one model identity")
    cfg = setup.load_runtime_config(root)
    active = root / "ki"
    baseline = ki_guard.require_intact(active)
    origin = ki_adaptations.projection(active, cfg)
    if origin is None:
        raise ValueError("Setup repair requires its host-prepared source projection")
    recipe = manifest_document(manifest) if not isinstance(manifest, dict) else manifest
    if not isinstance(recipe, dict) or recipe.get("model") != ki_name:
        raise ValueError("Setup repair recipe belongs to another model")
    source, library = Path(source_root).resolve(), Path(library_root).resolve()
    context = ki_adaptations._context(source, cfg, model=ki_name, library_root=library, manifest=recipe)
    if context != origin["context"]:
        raise ValueError("Selected setup source differs from its exact working projection")
    ident = uuid.uuid4().hex
    evidence = investigation._base(root) / "setup-evidence" / ident
    evidence.mkdir(parents=True)
    # Stable, bounded diagnostic snapshot: never traverse software/build trees
    # or bind a review to the continually appended agent log/status file.
    diagnostics = {"issue": investigation.redact(str(issue))[:12000],
                   "scope": "Installation KI maintenance; retained outputs are not new scientific validation."}
    for filename in ("status.json", "installation-test.json", "setup-agent.log"):
        path = root / filename
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                size = path.stat().st_size
                stream.seek(max(0, size - 48000))
                diagnostics[filename] = investigation.redact(stream.read(48000).decode("utf-8", "replace"))
    investigation._json(evidence / "diagnostics.json", diagnostics)
    (evidence / "kiss.toml").write_text(investigation.redact((root / "kiss.toml").read_text(encoding="utf-8")), encoding="utf-8")
    binding = investigation._signed(evidence.parent / f"{ident}.json", {
        "policy": POLICY, "implementation": _identity(), "root": str(root), "active_root": str(active),
        "ki_name": ki_name, "source_root": str(source), "library_root": str(library),
        "config_sha256": _hash_file(root / "kiss.toml"), "runtime_identity": software_verification.runtime_identity(cfg),
        "baseline_digest": baseline["digest"], "projection": origin, "context": context,
        "effective_manifest": recipe, "helper_files": helper_identity.package_files(Path(cfg.roles["ki_tools_common"])),
        "evidence_root": str(evidence), "created_at": time.time()})
    require_binding(binding)
    return binding


def sources(binding):
    cfg = require_binding(binding)
    return {"setup": Path(binding["evidence_root"]),
            f"kis/{binding['ki_name']}": Path(binding["active_root"]),
            f"helpers/{binding['ki_name']}": Path(cfg.roles["ki_tools_common"]),
            f"upstream_kis/{binding['ki_name']}": Path(binding["source_root"])}


def _check(stop, check_binding):
    if stop is not None and stop():
        raise ValueError("Setup KI repair was cancelled; no new readiness was granted")
    if check_binding is not None:
        check_binding()


def apply(root, job_id, verification_id, *, stop=None, check_binding=None):
    """Adopt only the reviewed setup candidate, with pending preflight first."""
    root = _root(root)
    with investigation._LOCK, ExitStack() as stack:
        _check(stop, check_binding)
        doc = investigation._load(root, job_id)
        binding = doc.get("setup_binding")
        if (doc.get("status") != "verified" or not doc.get("verification", {}).get("ok")
                or doc["verification"]["id"] != verification_id or not binding):
            raise ValueError("Setup adoption requires the exact completed KDT verification")
        cfg = require_binding(binding)
        active = root / "ki"
        if (binding["root"] != str(root) or not doc["draft"].get("setup_local")
                or doc["draft"]["active_root"] != str(active)
                or doc["draft"].get("repair_mode") != "maintenance"):
            raise ValueError("Setup adoption requires its exact maintenance target")
        stack.enter_context(ki_guard.operation(active))
        ki_guard._no_workers(active)
        investigation._assert_current(doc)
        candidate = investigation._require_verified_candidates(doc)
        report = doc["verification"]["report"]
        transaction = {"policy": POLICY, "status": "prepared", "root": str(root),
            "active_root": str(active), "job_id": job_id, "verification_id": verification_id,
            "old_digest": binding["baseline_digest"], "adopted_digest": report["candidate_digest"],
            "binding": binding, "pending_preflight": True, "native_verified": False,
            "created_at": time.time()}
        # Persist fail-closed pending evidence before revoking old status or
        # replacing anything. A crash never transfers old software readiness.
        investigation._signed(_pointer(root), dict(transaction))
        doc.update(status="applying", apply={**transaction, "status": "prepared"})
        investigation._save(root, doc)
        history = investigation._root(root, job_id) / "prior-setup-state"
        history.mkdir(exist_ok=True)
        try:
            install_locations.invalidate_verification(root)
            for name in ("status.json", "installation-test.json"):
                path = root / name
                if path.is_file():
                    if path.is_symlink():
                        raise ValueError("Setup status cannot be a linked file")
                    shutil.copy2(path, history / name)
                    path.unlink()
            _check(stop, check_binding)
            require_binding(binding)
            adopted = ki_guard.activate_maintenance(active, candidate, report,
                source=doc["draft"]["maintenance_source"], quiescent=True)
            transaction.update(status="complete", adopted_digest=adopted["digest"], applied_at=time.time())
            doc.update(status="applied", apply=transaction)
            investigation._save(root, doc)
            investigation._signed(_pointer(root), dict(transaction))
        except Exception as exc:
            transaction.update(status="needs_recovery", error=investigation.redact(str(exc)))
            doc.update(status="apply_failed", apply=transaction)
            investigation._save(root, doc)
            investigation._signed(_pointer(root), dict(transaction))
            raise
    return investigation.get(root, job_id)


def require_adoption(root, *, source_root, library_root, manifest, cfg=None):
    """Read exact retained setup maintenance; absence alone returns None."""
    root = _root(root)
    path = _pointer(root)
    if not path.exists():
        return None
    record = investigation._read_signed(path)
    if (record.get("policy") != POLICY or record.get("status") != "complete"
            or record.get("root") != str(root) or record.get("active_root") != str(root / "ki")):
        raise ValueError("Setup repair is incomplete or needs recovery; readiness remains blocked")
    binding = record["binding"]
    recipe = manifest_document(manifest) if not isinstance(manifest, dict) else manifest
    if (str(Path(source_root).resolve()) != binding["source_root"]
            or str(Path(library_root).resolve()) != binding["library_root"]
            or recipe != binding["effective_manifest"]):
        raise ValueError("Selected source or effective recipe changed after setup maintenance")
    current = require_binding(binding, live_digest=record["adopted_digest"])
    if cfg is not None and software_verification.runtime_identity(cfg) != software_verification.runtime_identity(current):
        raise ValueError("Caller runtime differs from the maintained setup binding")
    doc = investigation._load(root, record["job_id"])
    unsigned_record = {key: value for key, value in record.items() if key != "signature"}
    if (doc.get("status") != "applied" or doc.get("apply") != unsigned_record
            or doc.get("setup_binding") != binding
            or doc.get("verification", {}).get("id") != record["verification_id"]
            or doc.get("verification", {}).get("ok") is not True):
        raise ValueError("Setup repair adoption journal is incomplete or inconsistent")
    candidate = investigation._require_verified_candidates(doc)
    if ki_verification.content_digest(candidate) != record["adopted_digest"]:
        raise ValueError("Maintained setup candidate changed after adoption")
    return record


def finish_preflight(root, *, passed, source_root, library_root, manifest, cfg=None):
    """Record the host's fresh check, never accept a provider success boolean."""
    from . import install
    root = _root(root)
    with investigation._LOCK:
        record = require_adoption(root, source_root=source_root, library_root=library_root,
                                  manifest=manifest, cfg=cfg)
        if record is None:
            return None
        accepted = False
        proof = {}
        if passed is True:
            status_path = root / "status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            rows = [row for row in status.get("steps", []) if isinstance(row, dict) and row.get("name") == "preflight"]
            if (status.get("ok") is not True or status.get("model") != record["binding"]["ki_name"]
                    or status.get("ki_content_digest") != record["adopted_digest"]
                    or status.get("runtime_identity") != record["binding"]["runtime_identity"]
                    or not isinstance(status.get("checked_at"), (int, float))
                    or status["checked_at"] < record["applied_at"]
                    or len(rows) != 1 or rows[0].get("ok") is not True):
                raise ValueError("Fresh exact setup preflight status is required after maintenance")
            evidence = rows[0].get("evidence") or {}
            if (evidence.get("policy") != install.PREFLIGHT_POLICY or evidence.get("ok") is not True
                    or evidence.get("state") != "completed" or evidence.get("returncode") != 0
                    or evidence.get("source_intact") is not True or evidence.get("launch_attempted") is not True
                    or evidence.get("source_root") != str(root / "ki")
                    or evidence.get("workspace_root") != str(root)
                    or evidence.get("source_digest") != record["adopted_digest"]
                    or evidence.get("execution_digest") != record["adopted_digest"]
                    or evidence.get("runtime_identity") != record["binding"]["runtime_identity"]):
                raise ValueError("Fresh preflight execution evidence is required after maintenance")
            execution_path = Path(evidence.get("record_path") or "")
            if (not execution_path.is_absolute() or not execution_path.is_file()
                    or execution_path.is_symlink() or execution_path.stat().st_size > 256000
                    or json.loads(execution_path.read_text(encoding="utf-8")) != evidence):
                raise ValueError("Retained preflight execution record is missing or changed")
            accepted = True
            proof = {"status_sha256": _hash_file(status_path),
                     "execution_record_sha256": _hash_file(execution_path),
                     "checked_at": status["checked_at"]}
        updated = {key: value for key, value in record.items() if key != "signature"}
        updated.update(pending_preflight=not accepted, preflight_passed=accepted, preflight=proof)
        doc = investigation._load(root, record["job_id"])
        doc["apply"] = updated
        investigation._save(root, doc)
        return investigation._signed(_pointer(root), dict(updated))


def run(root, *, ki_name, source_root, library_root, manifest, provider, model="", issue,
        recipe, reviewer, stop=None, check_binding=None, emit=None):
    """Run the existing three-review and exact maintenance gates under a lease."""
    root = _root(root)
    _check(stop, check_binding)
    binding = capture(root, ki_name=ki_name, source_root=source_root, library_root=library_root,
                      manifest=manifest, issue=issue)
    job = investigation.create(root, {"id": "", "scope": "setup"},
        {ki_name: root / "ki"}, provider, model, issue, setup_binding=binding)
    job_id = job["id"]
    finished = threading.Event()

    def monitor():
        while not finished.wait(0.1):
            if stop is not None and stop():
                investigation.cancel(root, job_id)
                return

    watcher = threading.Thread(target=monitor, name="setup-ki-repair-cancel", daemon=True)
    watcher.start()
    try:
        if emit:
            emit("Reviewing this setup KI with three independent agents.\n")
        job = investigation.run_reviews(root, job_id, reviewer)
        _check(stop, check_binding)
        if job["status"] != "reviewed":
            return job
        job = investigation.create_draft(root, job_id, ki_name, repair_mode="maintenance", maintenance_recipe=recipe)
        _check(stop, check_binding)
        if emit:
            emit("Checking the exact maintenance draft through KDT.\n")
        job = investigation.verify_draft(root, job_id)
        _check(stop, check_binding)
        if not job.get("verification", {}).get("ok"):
            return job
    finally:
        finished.set()
        watcher.join()
    _check(stop, check_binding)
    result = apply(root, job_id, job["verification"]["id"], stop=stop, check_binding=check_binding)
    if emit:
        emit("Verified KI maintenance adopted locally; fresh software preflight is still required.\n")
    return result
