"""Host-owned, provider-independent acceptance of an exact KI draft.

This gate proves package structure, not native execution or scientific validity.
Reports are signed with GeoForge's existing host key store and retained outside
the candidate. A CLI running with the user's OS rights is not an OS sandbox;
these signatures must not be described as protection from that user's account.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

from . import doctor, firstrun
from .catalog import KI

GATE_POLICY = "ki-draft-kdt-v1"
KINDS = ("process_model", "task_workflow")


class VerificationError(ValueError):
    """A candidate has no current, authentic host acceptance."""


def content_digest(root: Path) -> str | None:
    # Keep one tree definition for Studio, updater and installation boundaries.
    from . import kdtstudio
    try:
        return kdtstudio.tree_digest(Path(root))
    except (OSError, ValueError, RuntimeError):
        return None


def detect_kind(root: Path) -> str:
    """Recognise only an explicit supported KI kind; absent metadata is a model."""
    import yaml
    path = Path(root) / "knowledge_infrastructure.yaml"
    if not path.is_file():
        return "process_model"
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise VerificationError(f"Cannot read KI kind: {error}") from error
    if not isinstance(doc, dict):
        raise VerificationError("knowledge_infrastructure.yaml must be a mapping")
    package = doc.get("package") or {}
    values = [doc.get("package_kind"), doc.get("ki_kind")]
    if isinstance(package, dict):
        values.extend([package.get("kind"), package.get("ki_kind")])
    explicit = {str(value) for value in values if value is not None}
    if len(explicit) > 1 or any(value not in KINDS for value in explicit):
        raise VerificationError(f"Conflicting or unsupported KI kind: {sorted(explicit)}")
    return next(iter(explicit), "process_model")


def _store() -> Path:
    override = os.environ.get("GEOFORGE_KI_VERIFICATION_HOME")
    return (Path(override).expanduser() if override else
            firstrun.data_dir() / "ki-verification").resolve()


def _receipts():
    from . import flowgate
    return flowgate.load().receipts


def _authority(root: Path) -> Path:
    root = Path(root).resolve()
    authority = _store()
    for path in (authority, _receipts().keys_dir().resolve()):
        if path == root or path.is_relative_to(root):
            raise VerificationError("KI verification records and keys must remain outside the candidate")
    return authority


def _record_path(digest: str, kind: str, desktop: bool) -> Path:
    key = hashlib.sha256(f"{GATE_POLICY}:{kind}:{int(desktop)}:{digest}".encode()).hexdigest()
    return _store() / "records" / f"{key}.json"


def _seal(root: Path, report: dict, *, persist: bool = False) -> dict:
    """Internal host boundary: never expose arbitrary report signing as an AI tool."""
    authority = _authority(root)
    result = dict(report)
    result.pop("signature", None)
    result = _receipts().sign(authority, result)
    if persist:
        path = _record_path(result["candidate_digest"], result["kind"],
                            result["desktop_requested"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return result


def require_current(root: Path, report: dict, *, kind: str | None = None,
                    desktop: bool = True) -> dict:
    """Reject forged, failed, stale or differently scoped acceptance reports."""
    from . import kdtstudio
    if not isinstance(report, dict) or not _receipts().verify(_authority(root), report):
        raise VerificationError("KI verification is missing or unauthenticated; verify this draft with KDT")
    if (report.get("gate_policy") != GATE_POLICY or report.get("ok") is not True
            or report.get("kind") not in KINDS
            or (kind is not None and report.get("kind") != kind)
            or (desktop and report.get("desktop_requested") is not True)
            or report.get("doctor_policy") != doctor.VALIDATION_POLICY_VERSION
            or report.get("engine_policy") != kdtstudio.REVIEWED_COMMIT):
        raise VerificationError("KI verification failed or uses another gate contract; verify this draft again")
    if (report.get("engine_source_digest") != kdtstudio.engine_source_digest()
            or report.get("engine_override") != bool(os.environ.get("GEOFORGE_KDT_ENGINE"))):
        raise VerificationError("KDT verifier source changed; verify this draft again with the current reviewed engine")
    digest = content_digest(root)
    if not digest or digest != report.get("candidate_digest"):
        raise VerificationError("KI contents changed after verification; this revision is a draft and must pass KDT again")
    return report


def current_report(root: Path, *, kind: str = "process_model", desktop: bool = True) -> dict | None:
    digest = content_digest(root)
    if not digest or kind not in KINDS:
        return None
    try:
        report = json.loads(_record_path(digest, kind, desktop).read_text(encoding="utf-8"))
        return require_current(root, report, kind=kind, desktop=desktop)
    except (OSError, ValueError, TypeError):
        return None


def _frozen_windows() -> bool:
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


class _GateRuntimeSys:
    """Change only the loaded verifier's child launcher, never global sys."""
    frozen = False

    def __init__(self, executable: str):
        self.executable = executable

    def __getattr__(self, name):
        return getattr(sys, name)


def _preflight_interpreter() -> str:
    from . import install
    interpreter = install.runtime_python()
    resolved = Path(shutil.which(interpreter) or interpreter).resolve()
    if (not resolved.is_file() or
            (getattr(sys, "frozen", False) and resolved == Path(sys.executable).resolve())):
        raise VerificationError("A real Python interpreter is required for the isolated KDT preflight-contract check. Install/configure Python in GeoForge setup and verify again.")
    return str(resolved)


def verify_candidate(root: Path, *, kind: str = "process_model", desktop: bool = True,
                     name: str | None = None) -> dict:
    """Run the actual installed KDT gate on an isolated, unchanged snapshot.

    Missing KDT never falls back to doctor or an agent's claimed success.
    Candidate Python is not granted execution during this structural check;
    its preflight report contract is checked on every platform before the
    isolated preflight is deferred. Native regression remains a separate gate.
    """
    from . import kdtstudio
    root = Path(root).resolve()
    if kind not in KINDS:
        raise VerificationError(f"Unsupported KI kind: {kind!r}")
    _authority(root)
    if not root.is_dir() or not any(root.iterdir()):
        raise VerificationError("The candidate KI is empty")
    before = content_digest(root)
    if not before:
        raise VerificationError("Cannot hash KI candidate; symbolic links or oversized trees are not accepted")
    engine = kdtstudio.engine_status()
    if not engine.get("installed"):
        reason = "modified" if engine.get("dirty") else "unavailable"
        raise VerificationError(f"KDT engine is {reason}. Open KI Studio, install the reviewed KDT engine (preserving the previous checkout), then verify this draft again.")
    failures: list[str] = []
    findings: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="geoforge-kdt-gate-") as td:
        snapshot = Path(td) / "candidate"
        shutil.copytree(root, snapshot)
        if content_digest(snapshot) != before or content_digest(root) != before:
            raise VerificationError("KI changed while preparing verification; retry on an unchanged draft")
        if desktop:
            findings = [dict(severity=f.severity, check=f.check, detail=f.detail, count=f.count)
                        for f in doctor.check_ki(KI(name=name or root.name, root=snapshot))]
        preflight = snapshot / "preflight_check.py"
        if preflight.is_file():
            source = preflight.read_text(encoding="utf-8", errors="replace")
            if "PREFLIGHT_REPORT=" not in source:
                failures.append("preflight_check.py does not contain the PREFLIGHT_REPORT= contract")
            try:
                ast.parse(source)
            except SyntaxError as error:
                failures.append(f"preflight_check.py has invalid Python syntax at line {error.lineno}")
            preflight.write_text(
                "import json\n"
                "report={'checks':[{'kind':'run','subject':'deferred',"
                "'critical':True,'status':'fail','fix':'Run GeoForge software setup and verification'}]}\n"
                "print('PREFLIGHT_REPORT='+json.dumps(report))\n"
                "raise SystemExit(1)\n", encoding="utf-8")
        else:
            failures.append("preflight_check.py is missing; the KDT preflight report contract is required")
        isolated_digest = content_digest(snapshot)
        with kdtstudio._engine_imports():
            gate = kdtstudio._load_engine_module("verify_ki_structure.py", "gate")
            if _frozen_windows():
                # Keep KDT's required preflight file and real report check.
                # Only the safe stub runs under a real interpreter; replacing
                # global sys.executable would affect concurrent model work.
                gate.sys = _GateRuntimeSys(_preflight_interpreter())
            result = gate.verify(snapshot, kind=kind)
        if not isinstance(result, dict):
            raise VerificationError("KDT returned an invalid verification report")
        if content_digest(snapshot) != isolated_digest or content_digest(root) != before:
            raise VerificationError("KI changed during verification; no acceptance was recorded")
        if kdtstudio.engine_source_digest() != engine["source_digest"]:
            raise VerificationError("KDT verifier source changed during verification; no acceptance was recorded")
    failures.extend(kdtstudio._desktopize_gate_text(item) for item in result.get("failures") or [])
    warnings = [kdtstudio._desktopize_gate_text(item) for item in result.get("warnings") or []]
    kdt_ok = result.get("ok") is True and not failures
    blockers = [f for f in findings if f["severity"] == doctor.BLOCK]
    ok = bool(kdt_ok and not blockers)
    report = {
        "report_version": 1, "gate_policy": GATE_POLICY, "kind": kind,
        "doctor_policy": doctor.VALIDATION_POLICY_VERSION,
        "checked_at": time.time(), "state": "Verified" if ok else "Draft", "ok": ok,
        "candidate_digest": before, "digest": before,
        "engine_policy": kdtstudio.REVIEWED_COMMIT,
        "engine_commit": engine.get("commit"),
        "engine_source_digest": engine["source_digest"],
        "engine_override": bool(os.environ.get("GEOFORGE_KDT_ENGINE")),
        "desktop_requested": bool(desktop),
        "kdt": {"ok": kdt_ok, "failures": failures, "warnings": warnings,
                "info": result.get("info") or {}},
        "desktop": {"checked": bool(desktop), "ok": not blockers if desktop else None,
                    "blocking": len(blockers), "findings": findings},
        "failures": failures, "warnings": warnings, "info": result.get("info") or {},
        "software_execution": "deferred_to_geoforge_setup",
        "native_regression": {"status": "not_run", "verified": False},
        "assurance": "host_attestation_not_os_sandbox",
    }
    if content_digest(root) != before:
        raise VerificationError("KI changed before acceptance could be recorded")
    return _seal(root, report, persist=True)
