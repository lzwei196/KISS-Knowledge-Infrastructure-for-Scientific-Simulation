"""Host receipts for the exact materialized KI and runtime used by a project.

Only ``verify`` runs KI preflight. ``status`` reads saved evidence; dispatch's
``require_current`` also inspects native dependency and executable identities
for supported profiles, writing bounded host evidence scratch. Opening/planning
a project never executes its preflight. This proves neither a scientific result
nor derivation from an upstream installation.
"""
from __future__ import annotations

from dataclasses import asdict
from .manifest import document as manifest_document
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import tomllib
import uuid

from . import install, ki_guard, ki_verification, paths, project_paths, software_verification
from .catalog import KI
from .manifest import Manifest

POLICY = "project-runtime-preflight-v3-declared-runtime"
_STATES = {"pending", "verified", "failed", "cancelled"}
_MAX_RECEIPT_BYTES = 1024 * 1024
_MAX_HISTORY_FILES = 256
_MAX_HISTORY_BYTES = 16 * 1024 * 1024


def _receipts():
    from . import flowgate
    return flowgate.load().receipts


def _hash(doc) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode("utf-8")).hexdigest()


def _target(project, ki):
    project = Path(project).expanduser().resolve()
    home = project_paths._model_home(project, ki.name)
    expected = home / "ki"
    candidate = Path(ki.root).expanduser()
    if not candidate.is_absolute():
        candidate = project / candidate
    candidate = Path(os.path.abspath(candidate))
    if candidate != expected or candidate.resolve() != expected:
        raise ValueError("Verification requires this project's exact models/<KI>/ki directory")
    return project, home, KI(ki.name, expected)


def _receipt_path(project: Path, model: str) -> Path:
    # Hashed filenames prevent platform-specific model names becoming paths.
    path = project / ".geoforge" / "project-verification" / (_hash(model)[:24] + ".json")
    for candidate in (path.parent.parent, path.parent, path):
        if candidate.resolve() != candidate:
            raise ValueError("Project verification receipt location is aliased")
    return path


def _read(path: Path):
    path = ki_guard._io(path)
    if not path.is_file():
        return None
    # A receipt is small even when the preflight emitted a long diagnostic.
    if path.stat().st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("Project verification receipt is too large")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("Project verification receipt is not an object")
    return doc


def _history_dir(project: Path, model: str) -> Path:
    current = _receipt_path(project, model)
    directory = current.parent / "history" / current.stem
    for candidate in (directory.parent, directory):
        if candidate.resolve() != candidate:
            raise ValueError("Project verification history location is aliased")
    return directory


def _receipt_bytes(path: Path) -> bytes:
    """Bounded ordinary bytes; never follow a receipt link or create a key."""
    path = ki_guard._io(path)
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or getattr(before, "st_file_attributes", 0) & 0x400):
        raise ValueError("Project verification receipt must be an ordinary unlinked file")
    if before.st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("Project verification receipt is too large")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        payload = stream.read(_MAX_RECEIPT_BYTES + 1)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (len(payload) > _MAX_RECEIPT_BYTES or any(getattr(before, key) != getattr(opened, key)
            or getattr(opened, key) != getattr(after, key) for key in fields)):
        raise ValueError("Project verification receipt changed while being read")
    return payload


def _authenticated(project: Path, model: str, payload: bytes):
    doc = json.loads(payload.decode("utf-8"))
    if not isinstance(doc, dict) or not _receipts().verify(project, doc):
        raise ValueError("Project verification history record is unauthenticated")
    if (doc.get("project") != str(project) or doc.get("model") != model
            or doc.get("ki_root") != str(project / "models" / model / "ki")):
        raise ValueError("Project verification history record has a different project or model")
    return doc


def _archive_current(project: Path, model: str, current: Path) -> None:
    """Retain an authenticated observation, without claiming continued readiness."""
    try:
        payload = _receipt_bytes(current)
    except FileNotFoundError:
        return
    try:
        _authenticated(project, model, payload)
    except (ValueError, TypeError):
        # Reverification may replace an unauthenticated old receipt; it must
        # never turn those bytes into authenticated historical evidence.
        return
    directory = _history_dir(project, model)
    destination = ki_guard._io(directory / (hashlib.sha256(payload).hexdigest() + ".json"))
    try:
        existing = _receipt_bytes(destination)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if existing != payload:
            raise ValueError("Retained project verification history was modified")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation never replaces an existing observation. Publication
    # failures leave the current receipt untouched; a partial archive fails
    # closed on retry instead of silently erasing the old check.
    try:
        with destination.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        pass
    if _receipt_bytes(destination) != payload:
        raise ValueError("Retained project verification history differs from its source")


def history(project, model: str, limit: int = 8) -> dict:
    """Read retained signed observations only; neither freshness nor completeness.

    No config, model, runtime or preflight is inspected. Missing context in an
    old authenticated record remains unknown, never today's build. A present
    but malformed context is not silently treated as a legacy observation.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 32:
        raise ValueError("Project verification history limit must be between 1 and 32")
    from . import runtime_provenance
    project = Path(project).expanduser().resolve()
    project_paths._model_home(project, model)  # model-name validation only
    result = {"scope": "project_preflight", "historical": True,
              "readiness_rechecked": False, "complete_history": False,
              "records": [], "invalid_count": 0, "truncated": False}
    try:
        current = _receipt_path(project, model)
        directory = _history_dir(project, model)
        candidates = [(current, "current")]
        try:
            with os.scandir(ki_guard._io(directory)) as entries:
                for index, entry in enumerate(entries):
                    if index >= _MAX_HISTORY_FILES:
                        result["truncated"] = True
                        break
                    if not re.fullmatch(r"[a-f0-9]{64}\.json", entry.name):
                        result["invalid_count"] += 1
                        continue
                    candidates.append((directory / entry.name, "history"))
        except FileNotFoundError:
            pass
    except (OSError, ValueError):
        result["invalid_count"] += 1
        return result
    seen, used = set(), 0
    for path, location in candidates:
        try:
            payload = _receipt_bytes(path)
            used += len(payload)
            if used > _MAX_HISTORY_BYTES:
                result["truncated"] = True
                break
            digest = hashlib.sha256(payload).hexdigest()
            if location == "history" and digest != path.stem:
                raise ValueError("Historical receipt digest differs from its filename")
            if digest in seen:
                continue
            doc = _authenticated(project, model, payload)
            seen.add(digest)
            row = {"receipt_sha256": digest, "location": location,
                   "authentication": "verified", "provenance": "legacy_unknown",
                   "verification_context": None}
            if "verification_context" in doc:
                try:
                    row["verification_context"] = runtime_provenance.validate(doc["verification_context"])
                    row["provenance"] = "recorded"
                except (ValueError, TypeError):
                    row["provenance"] = "invalid"
                    result["invalid_count"] += 1
            if row["provenance"] != "invalid":
                if (doc.get("schema_version") != 1 or doc.get("state") not in _STATES
                        or not isinstance(doc.get("attempt_id"), str)
                        or not doc["attempt_id"] or len(doc["attempt_id"]) > 128):
                    raise ValueError("Invalid historical preflight fields")
                row.update(attempt_id=doc["attempt_id"], state=doc["state"])
                for field in ("started_at", "checked_at"):
                    value = doc.get(field)
                    if value is not None:
                        if (isinstance(value, bool) or not isinstance(value, (int, float))
                                or not 0 <= value < 1e12):
                            raise ValueError("Invalid historical preflight time")
                        row[field] = value
            result["records"].append(row)
        except FileNotFoundError:
            if location != "current":
                result["invalid_count"] += 1
        except (OSError, ValueError, TypeError, UnicodeError):
            result["invalid_count"] += 1
    # The atomic current pointer is stronger ordering evidence than a wall
    # clock. A clock rollback must not hide the current failed/cancelled check
    # behind older passes when the bounded display is truncated.
    result["records"].sort(key=lambda row: (row["location"] == "current",
                                           row.get("checked_at", row.get("started_at", 0)),
                                           row["receipt_sha256"]), reverse=True)
    if len(result["records"]) > limit:
        result["truncated"] = True
        result["records"] = result["records"][:limit]
    return result


def _write(project: Path, model: str, doc: dict) -> dict:
    with ki_guard.operation(project / "models" / model / "ki"):
        path = _receipt_path(project, model)
        _archive_current(project, model, path)
        sealed = _receipts().sign(project, dict(doc))
        payload = json.dumps(sealed, indent=2, ensure_ascii=False) + "\n"
        if len(payload.encode("utf-8")) > _MAX_RECEIPT_BYTES:
            raise ValueError("Project verification receipt is too large to persist")
        # Keep short common paths, and use the existing host-I/O spelling for
        # genuinely long Windows project directories (never for model argv).
        path = ki_guard._io(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex[:12] + ".tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            if doc.get("state") == "verified":
                # Signing/serialization and filesystem writes can take time.
                # A stop during them must not publish the prepared success.
                install.check_cancelled()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return sealed


def _config(project: Path, home: Path, model: str):
    """Parse once, in memory, with the existing project role ownership rules.

    KissConfig's legacy compatibility reader can repair files, so it cannot be
    used by a read-only status gate. No ancestor fallback or root repair here.
    """
    location = home / paths.CONFIG_NAME
    if location.resolve() != location:
        raise ValueError("Project KI configuration is aliased")
    text = location.read_text(encoding="utf-8")
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raw = tomllib.loads(paths._repair_backslash_strings(text))
    settings = raw.get("kiss")
    roles = raw.get("paths", {})
    if not isinstance(settings, dict) or not isinstance(roles, dict):
        raise ValueError("Project configuration needs [kiss] and valid [paths] tables")
    for key in ("root", "python"):
        value = settings.get(key)
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            raise ValueError(f"Project configuration kiss.{key} must be an explicit nonempty string")
    if Path(settings["root"]).expanduser().resolve() != project:
        raise ValueError("Saved KI configuration root does not match this project")
    cfg = paths.KissConfig.default(project)
    cfg.python = settings["python"]
    cfg.relocation = settings.get("relocation", cfg.relocation)
    if cfg.relocation not in ("none", "sandbox", "port", "symlink"):
        raise ValueError("Invalid project configuration relocation mode")
    for role, value in roles.items():
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            raise ValueError(f"Project configuration path {role} must be a nonempty string")
        cfg.roles[role] = Path(value).expanduser()
    known = project_paths._known_models(project) | {model}
    project_paths._check_ambiguous_inputs(cfg, project, model, known)
    cfg.roles.update(project_paths._overrides(cfg, project, model, known, strict=True))
    cfg.roles["ki_root"] = project / "models"
    cfg.roles["server_root"] = project
    return cfg


def _manifest(ki, supplied, receipt=None):
    actual = Manifest.load(ki.manifest) if ki.manifest else None
    if actual is not None:
        if supplied is not None and manifest_document(supplied) != manifest_document(actual):
            raise ValueError("Supplied effective manifest differs from the project's actual KI manifest")
        selected, doc = actual, manifest_document(actual)
    elif supplied is not None:
        selected, doc = supplied, manifest_document(supplied)
    else:
        selected, doc = None, (receipt or {}).get("effective_manifest")
        if not isinstance(doc, dict):
            raise ValueError("No checked effective manifest exists for this project KI")
    if doc.get("model") != ki.name:
        raise ValueError("Effective manifest does not belong to the selected project KI")
    return selected, doc


def _identity(project, home, ki, manifest, receipt=None):
    from .runtime_arguments import declared_runtime_bindings
    from . import runtime_data, ki_data_lineage
    ki_guard.require_intact(ki.root, required=True)
    digest = ki_verification.content_digest(ki.root)
    if not digest:
        raise ValueError("Cannot fingerprint the project's exact KI tree")
    cfg = _config(project, home, ki.name)
    # A derived setup repair remains conditional on its authenticated source,
    # runtime and project maintenance history. Check the common host seam so
    # API/CLI dispatch cannot retain readiness after that authority changes.
    derivation = ki_data_lineage.require_setup_projection(project, ki.name, ki.root, cfg)
    man, document = _manifest(ki, manifest, receipt)
    # The checked effective manifest may be retained only in the signed receipt.
    from types import SimpleNamespace
    data_identity = runtime_data.inspect(man or SimpleNamespace(runtime_data=document.get("runtime_data")), cfg)
    return cfg, man, {
        "project": str(project), "model": ki.name, "ki_root": str(ki.root),
        "ki_content_digest": digest,
        "setup_derivation": (_hash(derivation["project_derivation"])
                             if derivation is not None and derivation.get("project_derivation") is not None else None),
        "runtime_identity": software_verification.runtime_identity(cfg),
        "declared_runtime_bindings": declared_runtime_bindings(ki.root),
        "effective_manifest_digest": _hash(document), "effective_manifest": document,
        "runtime_data": data_identity,
    }


def _origin(source_ki, manifest, library_root):
    if source_ki is None:
        if library_root is not None:
            raise ValueError("An explicit source KI is required with library_root")
        return None
    digest = ki_verification.content_digest(source_ki.root)
    if not digest:
        raise ValueError("Cannot fingerprint the supplied upstream KI")
    return {"ki_root": str(Path(source_ki.root).resolve()), "ki_content_digest": digest,
            "snapshot_identity": software_verification.identity(source_ki, manifest, library_root)}


def _result(state, detail, receipt=None):
    return {"ok": state == "verified", "can_run": state == "verified",
            "state": state, "detail": detail, "receipt": receipt}


def _finish(project, ki, doc):
    doc["checked_at"] = time.time()
    # Do not let an older, slower attempt overwrite a newer pending/pass result.
    with ki_guard.operation(ki.root):
        current = _read(_receipt_path(project, ki.name))
        if not current or current.get("attempt_id") != doc["attempt_id"]:
            return _result("failed", "Project verification was superseded by another attempt", current)
        try:
            if doc["state"] == "verified":
                install.check_cancelled()
            sealed = _write(project, ki.name, doc)
            if doc["state"] == "verified":
                # Also cover Stop during the atomic replacement itself. Revoke
                # within this same host operation before returning any success.
                install.check_cancelled()
        except install.InstallStopped as exc:
            current = _read(_receipt_path(project, ki.name))
            if not current or current.get("attempt_id") != doc["attempt_id"]:
                return _result("failed", "Project verification was superseded by another attempt", current)
            doc.update(state="cancelled", ok=False, detail=str(exc), checked_at=time.time())
            sealed = _write(project, ki.name, doc)
    return _result(doc["state"], doc["detail"], sealed)


def _status(project, project_ki, manifest=None, *, source_ki=None, library_root=None) -> dict:
    doc = None
    try:
        project, home, ki = _target(project, project_ki)
        doc = _read(_receipt_path(project, ki.name))
        if doc is None:
            return _result("unverified", "This exact project KI has not been verified")
        if not _receipts().verify(project, doc):
            raise ValueError("Project verification receipt is unauthenticated")
        if doc.get("policy") != POLICY or doc.get("schema_version") != 1:
            raise ValueError("Project verification policy changed; verify this project KI again")
        if doc.get("state") not in _STATES:
            raise ValueError("Project verification receipt has an invalid state")
        if doc["state"] != "verified":
            return _result(doc["state"], doc.get("detail", "Project verification did not pass"), doc)
        if doc.get("ok") is not True:
            raise ValueError("Project verification receipt did not pass")
        _cfg, man, current = _identity(project, home, ki, manifest, doc)
        if any(doc.get(key) != value for key, value in current.items()):
            raise ValueError("Project KI, saved runtime bindings, or effective manifest changed; verify again")
        if source_ki is not None or library_root is not None:
            if man is None:
                raise ValueError("Explicit upstream comparison requires the effective manifest")
            if doc.get("origin") != _origin(source_ki, man, library_root):
                raise ValueError("Explicit upstream verification origin changed")
        return _result("verified", "Exact project KI preflight and manifest requirements passed", doc)
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        return _result("stale", str(exc), doc)


def status(project, project_ki, manifest=None, *, source_ki=None, library_root=None) -> dict:
    """Read proof without executing checks, adopting files, or repairing TOML.

    Origin is pinned provenance. Compare current upstream only when explicitly
    requested; unrelated catalogue updates do not invalidate retained projects.
    The host operation lock prevents reading a pass that is being revoked by
    cancellation during publication. It does not lock out external processes.
    """
    try:
        project, _home, ki = _target(project, project_ki)
        with ki_guard.operation(ki.root):
            return _status(project, ki, manifest, source_ki=source_ki, library_root=library_root)
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        return _result("stale", str(exc))


def verify(project, project_ki, manifest, *, source_ki=None, library_root=None,
           dependency_check=None, stop=None, turn_id=None) -> dict:
    """Explicitly check the saved project binding; never copy/adopt/install a KI.

    Revoke the previous pass before parsing or running anything. The caller
    retains responsibility for approving this check within its Flow/setup turn.
    Proven byte-identical projection metadata may be revalidated here; status
    reads and ordinary dispatch never perform that host metadata refresh.
    """
    project, home, ki = _target(project, project_ki)
    from . import runtime_provenance
    context = runtime_provenance.validate(runtime_provenance.capture())
    doc = {"schema_version": 1, "policy": POLICY, "attempt_id": uuid.uuid4().hex,
           "project": str(project), "model": ki.name, "ki_root": str(ki.root),
           "started_at": time.time(), "state": "pending", "ok": False,
           "detail": "Checking the exact project KI and saved runtime bindings", "checks": [],
           "verification_context": context}
    _write(project, ki.name, doc)  # persistence failure must prevent any execution
    try:
        with install.cancellation_context(project, stop=stop, turn_id=turn_id), ki_guard.worker(ki.root):
            install.check_cancelled()
            from . import ki_adaptations
            saved = _config(project, home, ki.name)
            ki_adaptations.refresh_project_projection(ki.root, saved, model=ki.name, manifest=manifest)
            install.check_cancelled()
            cfg, man, before = _identity(project, home, ki, manifest)
            doc.update(before)
            origin = _origin(source_ki, man, library_root)
            doc["origin"] = origin
            step = install.run_preflight(ki, cfg.python, cfg, project=project, stop=stop, turn_id=turn_id)
            doc["checks"].append(asdict(step))
            install.check_cancelled()
            if not step.ok:
                raise ValueError(step.detail or "Project KI preflight failed")
            step = software_verification.requirements(man, cfg, dependency_check=dependency_check)
            doc["checks"].append(asdict(step))
            install.check_cancelled()
            if not step.ok:
                raise ValueError(step.detail or "Project KI manifest requirements failed")
            _saved, _man, after = _identity(project, home, ki, manifest)
            if (before != after or software_verification.runtime_identity(cfg) != before["runtime_identity"]
                    or origin != _origin(source_ki, man, library_root)
                    or runtime_provenance.validate(runtime_provenance.capture()) != context):
                raise ValueError("Project KI, configuration, manifest, or supplied origin changed during verification")
            doc.update(state="verified", ok=True,
                       detail="Exact project KI preflight and manifest requirements passed")
            # The last check and signing stay inside the cancellation/worker
            # scope; stopping after probes must not publish a fresh pass.
            install.check_cancelled()
            return _finish(project, ki, doc)
    except install.InstallStopped as exc:
        doc.update(state="cancelled", ok=False, detail=str(exc))
    except Exception as exc:
        doc.update(state="failed", ok=False, detail=str(exc))
    return _finish(project, ki, doc)


def require_current(project, model_name: str, ki_root, *, cfg=None, environment=None, stop=None,
                    native_executable=None):
    """Guard materialized dispatch; leave explicit nonmaterialized legacy routes.

    Both namespace and resolved location count, so an alias cannot silently
    downgrade a project KI into the legacy path. This never reruns KI preflight
    or a model. Supported native profiles inspect current dependency/executable
    identities using trusted host probes before dispatch.
    """
    project = Path(project).expanduser().resolve()
    project_paths._model_home(project, model_name)  # validate name/ownership
    candidate = Path(ki_root).expanduser()
    if not candidate.is_absolute():
        candidate = project / candidate
    candidate = Path(os.path.abspath(candidate))
    namespace = project / "models"
    if not (candidate.is_relative_to(namespace) or candidate.resolve().is_relative_to(namespace)):
        return
    result = status(project, KI(model_name, candidate))
    if not result["can_run"]:
        raise ValueError("Project KI verification required before execution: " + result["detail"])
    if cfg is not None and software_verification.runtime_identity(cfg) != result["receipt"]["runtime_identity"]:
        raise ValueError("Project KI launch configuration differs from its verified saved runtime bindings")
    # All provider adapters reach this dispatch seam. Rehash authenticated
    # native dependency/executable evidence; never accept an agent's pass flag.
    from . import native_dependency_gate
    if cfg is None:
        cfg, _man, _identity_record = _identity(project, candidate.parent, KI(model_name, candidate), None, result["receipt"])
    return native_dependency_gate.require_current(result["receipt"].get("effective_manifest", {}), cfg,
                                           environment=environment, stop=stop,
                                           native_executable=native_executable)
