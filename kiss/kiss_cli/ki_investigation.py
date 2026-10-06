"""Optional independent reviews and explicit project-local KI repair.

Reviewer prose is analysis, never execution evidence. Authority records live
outside the project and reviewer packet. This is a host integrity boundary,
not a sandbox against other programs running as the same OS user.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import threading
import time
import uuid

from . import firstrun, flowgate, kdtstudio, ki_guard, ki_verification, paths, setup as setup_flow

ROLES = ("contract_runtime", "data_science", "reproducibility_risks")
POLICY = "project-ki-investigation-v1"
MAX_TEXT_BYTES = 32 * 1024 * 1024
MAX_CONTEXT_BYTES = 192 * 1024 * 1024
MAX_AUTHOR_REPORT_CHARS = 16_000
MAX_CHANGE_FILES = 500
_LOCK = threading.RLock()
_STOPS: dict[str, threading.Event] = {}
_RUNNING: set[str] = set()
_ID = re.compile(r"^[a-f0-9]{16}$")
_SECRET_KEY = re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret|credential|(?:^|[_-])token$|^(?:proxy-)?authorization$|^(?:set-)?cookie$)")
_SECRET_VALUE = re.compile(
    r'''(?im)(["']?(?:[\w.-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret|credential)|token|(?:proxy-)?authorization|(?:set-)?cookie)["']?\s*[:=]\s*)'''
    r'''(?:"(?:\\.|[^"\\\r\n])*"|'(?:\\.|[^'\\\r\n])*'|[^\s,;\r\n}]+)''')
_TOKEN = re.compile(r"\b(?:gfd_[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{16,})\b")
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__"}


class InvestigationError(ValueError):
    pass


def _home() -> Path:
    return Path(os.environ.get("GEOFORGE_KI_INVESTIGATION_HOME") or
                firstrun.data_dir() / "ki-investigations").resolve()


def _project(project) -> Path:
    project = Path(project).resolve()
    if not project.is_dir():
        raise InvestigationError("Project directory does not exist")
    if _home() == project or _home().is_relative_to(project):
        raise InvestigationError("Investigation authority must stay outside the project")
    return project


def _base(project: Path) -> Path:
    ident = hashlib.sha256(os.path.normcase(str(project)).encode()).hexdigest()[:16]
    return _home() / ident


def _root(project: Path, job_id: str) -> Path:
    if not _ID.fullmatch(str(job_id)):
        raise InvestigationError("Invalid investigation id")
    return _base(project) / job_id


def _json(path: Path, value) -> None:
    ki_guard._io(path.parent).mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    ki_guard._io(tmp).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(ki_guard._io(tmp), ki_guard._io(path))


def _signed(path: Path, value) -> dict:
    doc = flowgate.load().receipts.sign(_home(), value)
    _json(path, doc)
    return doc


def _read_signed(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not flowgate.load().receipts.verify(_home(), doc):
            raise ValueError("invalid signature")
        return doc
    except (OSError, ValueError, TypeError) as exc:
        raise InvestigationError("Investigation record is missing or unauthenticated") from exc


def _load(project: Path, job_id: str) -> dict:
    doc = _read_signed(_root(project, job_id) / "job.json")
    if doc.get("project") != str(project) or doc.get("id") != job_id or doc.get("policy") != POLICY:
        raise InvestigationError("Investigation belongs to another project or policy")
    return doc


def _save(project: Path, doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("signature", None)
    doc["updated_at"] = time.time()
    return _signed(_root(project, doc["id"]) / "job.json", doc)


def redact(text: str) -> str:
    """Redact common credential forms before any packet/provider/public output."""
    text = str(text)
    for key, value in os.environ.items():
        if len(value) >= 8 and _SECRET_KEY.search(key):
            text = text.replace(value, "[redacted]")
    # Structured JSON catches quoted keys, escaped strings, nested values,
    # cookie/header dictionaries and credentials containing whitespace. Keep
    # untouched JSON byte layout unless a value actually needs redaction.
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, (dict, list)):
        safe = _safe(parsed)
        if safe != parsed:
            text = json.dumps(safe, ensure_ascii=False, indent=2)
    text = re.sub(r"(?im)(\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*[:=]\s*)[^\r\n]+",
                  r"\1[redacted]", text)
    text = _SECRET_VALUE.sub(lambda m: m[1] + '"[redacted]"', text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@", r"\1[redacted]@", text)
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
                  "[redacted private key]", text, flags=re.S)
    return _TOKEN.sub("[redacted]", text)


def _safe(value):
    if isinstance(value, dict):
        return {redact(k): ("[redacted]" if _SECRET_KEY.search(str(k)) else _safe(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_safe(v) for v in value]
    return redact(value) if isinstance(value, str) else value


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(root: Path):
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs.sort()
        names.sort()
        for name in list(dirs):
            path = Path(current) / name
            reparse = bool(getattr(path.lstat(), "st_file_attributes", 0) &
                           getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
            if name in _SKIP_DIRS or path.is_symlink() or reparse:
                dirs.remove(name)
                yield path, "excluded_directory" if name in _SKIP_DIRS else "linked_directory"
        for name in names:
            path = Path(current) / name
            yield path, "linked_file" if path.is_symlink() else ""


def _sources(project: Path, ki_roots: dict) -> dict[str, Path]:
    sources = {"project": project}
    for name, value in sorted(ki_roots.items()):
        if not re.fullmatch(r"[\w .+-]{1,100}", str(name)) or str(name) in {".", ".."}:
            raise InvestigationError("Invalid selected KI name")
        root = Path(value).resolve()
        if not root.is_dir() or not (root / "SKILL.md").is_file():
            raise InvestigationError(f"Selected KI is unavailable: {name}")
        sources[f"kis/{name}"] = root
        config = project / "models" / name / paths.CONFIG_NAME
        if config.is_file():
            cfg = paths.KissConfig.load(config.parent)
            helper = cfg.roles.get("ki_tools_common")
            if helper and Path(helper).is_dir():
                sources[f"helpers/{name}"] = Path(helper).resolve()
    return sources


def _source_state(sources: dict[str, Path]) -> dict:
    result = {}
    for label, root in sources.items():
        rows = []
        for path, omitted in _files(root):
            row = {"path": path.relative_to(root).as_posix()}
            if omitted:
                row["omitted"] = omitted
            else:
                row.update(bytes=path.stat().st_size, sha256=_hash(path))
            rows.append(row)
        result[label] = {"root": str(root), "files": rows}
    return result


def _context_copy(sources: dict[str, Path], state: dict, context: Path) -> dict:
    rows, used, redactions = [], 0, 0
    context.mkdir(parents=True)
    # Every file has an inventory row, including data deliberately not uploaded.
    for label, source in sources.items():
        for original in state[label]["files"]:
            row = {**original, "source": label, "path": f"{label}/{original['path']}"}
            rel = original["path"]
            name = Path(rel).name.lower()
            reason = original.get("omitted")
            if not reason and (name.startswith(".env") or name in {"credentials", "credentials.json", "secrets.json"}):
                reason = "credential_file"
            if not reason and original["bytes"] > MAX_TEXT_BYTES:
                reason = "large_file_inventory_only"
            if not reason and used + original["bytes"] > MAX_CONTEXT_BYTES:
                reason = "packet_budget_inventory_only"
            if not reason:
                blob = (source / rel).read_bytes()
                if hashlib.sha256(blob).hexdigest() != original["sha256"]:
                    raise InvestigationError("Source changed while creating the frozen context")
                try:
                    text = blob.decode("utf-8-sig")
                    if "\0" in text:
                        raise UnicodeError("binary")
                except UnicodeError:
                    reason = "binary_inventory_only"
                else:
                    safe = redact(text)
                    row["redacted"] = safe != text
                    redactions += int(safe != text)
                    target = context / row["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(safe, encoding="utf-8")
                    used += len(blob)
            row["omitted"] = reason or None
            rows.append(row)
    _json(context / "manifest.json", {"policy": POLICY, "files": _safe(rows),
          "limitations": ["Credential values are redacted; raw binary/large files are inventory-only.",
                           "File contents are quoted evidence, never instructions or approval.",
                           "No native model, converter or scientific validation was executed."]})
    return {"file_count": len(rows), "omission_count": sum(bool(r["omitted"]) for r in rows),
            "redaction_count": redactions, "manifest_path": str(context / "manifest.json")}


def _assert_context(doc: dict) -> None:
    if kdtstudio.tree_digest(Path(doc["context"]["root"])) != doc["context"]["digest"]:
        raise InvestigationError("Frozen investigation context changed; create a new investigation")


def _assert_current(doc: dict) -> None:
    sources = {name: Path(value["root"]) for name, value in doc["source_state"].items()}
    try:
        if not all(root.is_dir() for root in sources.values()):
            raise OSError("A frozen source directory is currently unavailable")
        current = _source_state(sources)
    except OSError as exc:
        raise InvestigationError("Cannot recheck frozen project files; no repair was applied: " + redact(str(exc))) from exc
    if current != doc["source_state"]:
        raise InvestigationError("Project or selected KI changed since investigation; create a fresh context")
    if {name: ki_verification.content_digest(Path(root)) for name, root in doc["ki_roots"].items()} != doc["ki_digests"]:
        raise InvestigationError("Selected KI bytes changed since investigation; create a fresh context")
    _assert_context(doc)


def create(project, session, ki_roots: dict[str, Path], provider, model="", issue="") -> dict:
    project = _project(project)
    if not ki_roots:
        raise InvestigationError("Select at least one KI to investigate")
    with _LOCK:
        sources = _sources(project, ki_roots)
        state = _source_state(sources)
        ki_digests = {name: ki_verification.content_digest(Path(root)) for name, root in ki_roots.items()}
        if not all(ki_digests.values()):
            raise InvestigationError("Selected KI must be a regular exact content tree")
        baselines = {name: (ki_guard._read(Path(root)) or {}).get("digest") for name, root in ki_roots.items()}
        ident = uuid.uuid4().hex[:16]
        context = _root(project, ident) / "context"
        info = _context_copy(sources, state, context)
        metadata = {"session": _safe(session), "issue": redact(issue), "roles": list(ROLES),
                    "provider": str(provider), "model": str(model), "analysis_only": True}
        _json(context / "investigation.json", metadata)
        if (_source_state(sources) != state or
                {name: ki_verification.content_digest(Path(root)) for name, root in ki_roots.items()} != ki_digests):
            raise InvestigationError("Project changed during capture; create a fresh investigation")
        digest = kdtstudio.tree_digest(context)
        if not digest:
            raise InvestigationError("Could not freeze review context")
        now = time.time()
        doc = {"id": ident, "policy": POLICY, "status": "created", "created_at": now,
               "project": str(project), "session_id": str(session.get("id", "") if isinstance(session, dict) else session),
               "provider": str(provider), "model": str(model), "issue": redact(issue),
               "ki_roots": {k: str(Path(v).resolve()) for k, v in ki_roots.items()},
               "ki_digests": ki_digests, "baseline_digests": baselines,
               "source_state": state, "context": {**info, "root": str(context), "digest": digest},
               "reviewers": [{"role": role, "status": "pending"} for role in ROLES],
               "combined_report": None, "draft": None, "verification": None, "apply": None,
               "native_verified": False}
        _save(project, doc)
        _signed(_root(project, ident) / "capture.json", {"source_state": state, "context_digest": digest})
    return get(project, ident)


def get(project, job_id=None) -> dict:
    project = _project(project)
    with _LOCK:
        if job_id is None:
            candidates = sorted(_base(project).glob("*/job.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not candidates:
                return {"status": "none", "can_apply": False, "reviewers": []}
            job_id = candidates[0].parent.name
        doc = _load(project, job_id)
        public = {k: v for k, v in doc.items() if k not in {"source_state", "signature"}}
        public["report_path"] = str(_root(project, job_id) / "job.json")
        public["can_apply"] = False
        if doc.get("draft") and doc["status"] != "applied":
            public["draft"] = {**doc["draft"], "current_digest": ki_verification.content_digest(Path(doc["draft"]["path"]))}
        if doc["status"] == "verified" and doc.get("verification", {}).get("ok"):
            try:
                # Polling never rehashes a potentially huge raw-data archive.
                # Mutation is checked against the full frozen source state at
                # verify/apply; this flag only offers that guarded action.
                _assert_context(doc)
                ki_verification.require_current(Path(doc["draft"]["path"]), doc["verification"]["report"])
                public["can_apply"] = bool(doc["draft"]["project_local"])
            except (ValueError, RuntimeError, OSError) as exc:
                public["stale_reason"] = str(exc)
        if doc["status"] in {"reviewing", "verifying", "authoring", "applying"} and job_id not in _RUNNING:
            public.update(interrupted=True, interrupted_operation=doc["status"], can_apply=False,
                          retryable=doc["status"] in {"verifying", "authoring"})
            if doc["status"] == "applying":
                public.update(status="recovery_required", recovery_required=True,
                    error="GeoForge stopped during adoption. Inspect the signed repair journal and retained KI revisions; adoption will not retry automatically.")
            else:
                public["status"] = "interrupted"
        return _safe(public)


def latest_applied(project) -> dict | None:
    """Recover the latest committed repair generation, independently of new reviews.

    This only reads host-signed records; it never scans live project/raw data
    or rehashes a retained candidate. It supplies a context-reset handoff, not
    permission to resume execution or a substitute for the live KI guard.
    """
    project = _project(project)
    with _LOCK:
        candidates = []
        for path in _base(project).glob("*/job.json"):
            doc = _load(project, path.parent.name)
            result = doc.get("apply") or {}
            if doc["status"] == "applied" and result.get("status") == "complete" and result.get("generation"):
                candidates.append(doc)
        if not candidates:
            return None
        latest = max(candidates, key=lambda doc: (float(doc["apply"].get("applied_at") or doc["updated_at"]), doc["id"]))
        return get(project, latest["id"])


def _normal_report(role: str, value, context: Path, digest: str) -> dict:
    if not isinstance(value, dict):
        raise InvestigationError("Reviewer did not return a structured report")
    status = value.get("status", "completed")
    if status != "completed":
        return {"role": role, "status": status if status in {"failed", "cancelled", "unsupported"} else "failed",
                "error": redact(value.get("error", "Reviewer did not complete"))[:3000]}
    if value.get("context_digest", digest) != digest:
        raise InvestigationError("Reviewer reported a different context revision")
    if not isinstance(value.get("summary"), str) or not isinstance(value.get("findings"), list):
        raise InvestigationError("Reviewer report needs summary and findings")
    for finding in value["findings"]:
        if not isinstance(finding, dict):
            raise InvestigationError("Invalid reviewer finding")
        evidence = finding.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise InvestigationError("Reviewer findings must cite frozen evidence")
        for ref in evidence:
            if not isinstance(ref, str) or Path(ref).is_absolute() or ".." in Path(ref).parts:
                raise InvestigationError("Reviewer evidence must refer to a frozen packet file")
            target = context / ref
            if not target.is_file() or not target.resolve().is_relative_to(context.resolve()):
                raise InvestigationError("Reviewer evidence does not exist in the frozen packet")
    report = _safe(value)
    report.update(role=role, context_digest=digest, native_verified=False,
                  native_execution_verified=False, analysis_only=True)
    return {"role": role, "status": "completed", "report": report}


def run_reviews(project, job_id, runner) -> dict:
    project = _project(project)
    with _LOCK:
        doc = _load(project, job_id)
        if doc["status"] != "created" or job_id in _RUNNING:
            raise InvestigationError("This investigation has already started; create a new one to rerun")
        _assert_current(doc)
        stop = threading.Event()
        _STOPS[job_id] = stop
        _RUNNING.add(job_id)
        doc["status"] = "reviewing"
        doc["reviewers"] = [{"role": r, "status": "running"} for r in ROLES]
        _save(project, doc)
        _signed(_root(project, job_id) / "before-reviews.json", {"source_state": doc["source_state"],
                "context_digest": doc["context"]["digest"], "time": time.time()})
    context, digest = Path(doc["context"]["root"]), doc["context"]["digest"]

    def emit(value):
        # Provider diagnostics never become approval or verification evidence.
        with _LOCK:
            latest = _load(project, job_id)
            latest["activity"] = redact(str(value))[-2000:]
            _save(project, latest)

    def one(role):
        try:
            if stop.is_set():
                return {"role": role, "status": "cancelled"}
            result = runner(role, context, digest, stop, emit)
            _assert_context(doc)
            return _normal_report(role, result, context, digest)
        except Exception as exc:
            return {"role": role, "status": "failed", "error": redact(str(exc))[:3000]}

    try:
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="ki-review") as pool:
            futures = {pool.submit(one, role): role for role in ROLES}
            for future in as_completed(futures):
                row = future.result()
                with _LOCK:
                    doc = _load(project, job_id)
                    doc["reviewers"] = [row if old["role"] == row["role"] else old for old in doc["reviewers"]]
                    _save(project, doc)
        with _LOCK:
            doc = _load(project, job_id)
            reports = [r["report"] for r in doc["reviewers"] if r["status"] == "completed"]
            try:
                _assert_current(doc)
                stale = None
            except (ValueError, RuntimeError, OSError) as exc:
                stale = str(exc)
            doc["status"] = ("cancelled" if stop.is_set() else "stale" if stale else
                             "reviewed" if len(reports) == 3 else "review_failed")
            if stale:
                doc["error"] = stale
            doc["combined_report"] = {"summary": "\n\n".join(f"{r['role']}: {r['summary']}" for r in reports),
                "findings": [{**f, "reviewer": r["role"]} for r in reports for f in r["findings"]],
                "disagreements": "Reports are retained independently; agreement is not scientific proof.",
                "limitations": ["Analysis only; no native tests were run by this review workflow.",
                    f"{len(reports)} of 3 reviewers completed; omissions are listed in the context manifest.",
                    "The reviewers may use the same provider/model and share systematic errors."],
                "native_verified": False, "context_digest": digest}
            _save(project, doc)
            _signed(_root(project, job_id) / "after-reviews.json", {
                "source_state": _source_state({k: Path(v["root"]) for k, v in doc["source_state"].items()}),
                "context_digest": kdtstudio.tree_digest(context), "status": doc["status"], "time": time.time()})
    finally:
        with _LOCK:
            _RUNNING.discard(job_id)
            _STOPS.pop(job_id, None)
    return get(project, job_id)


def cancel(project, job_id) -> dict:
    project = _project(project)
    with _LOCK:
        doc = _load(project, job_id)
        if doc["status"] in {"applying", "applied"}:
            raise InvestigationError("An applied repair cannot be cancelled")
        if job_id in _STOPS:
            _STOPS[job_id].set()
        doc["status"] = "cancelled"
        _save(project, doc)
    return get(project, job_id)


def mark_authoring(project, job_id) -> dict:
    project = _project(project)
    with _LOCK:
        doc = _load(project, job_id)
        if doc["status"] not in {"draft", "verified", "verification_failed", "author_failed", "authoring"} or job_id in _RUNNING:
            raise InvestigationError("Repair draft is not available for authoring")
        _assert_current(doc)
        kdtstudio.continue_modifying(doc["draft"]["studio_job_id"])
        doc.update(status="authoring", verification=None, author_report=None, author_report_meta=None)
        doc.pop("error", None)
        _STOPS[job_id] = threading.Event()
        _RUNNING.add(job_id)
        _save(project, doc)
    return get(project, job_id)


def stop_event(project, job_id) -> threading.Event:
    project = _project(project)
    with _LOCK:
        _load(project, job_id)
        if job_id not in _STOPS:
            raise InvestigationError("No cancellable investigation operation is active")
        return _STOPS[job_id]


def mark_authored(project, job_id, error=None, author_report=None) -> dict:
    project = _project(project)
    with _LOCK:
        doc = _load(project, job_id)
        if doc["status"] not in {"authoring", "cancelled"}:
            raise InvestigationError("Repair authoring is not active")
        if doc["status"] != "cancelled":
            doc["status"] = "author_failed" if error else "draft"
            if error:
                doc["error"] = redact(str(error))
        if author_report is not None:
            text = (author_report if isinstance(author_report, str) else
                    json.dumps(_safe(author_report), ensure_ascii=False, default=str))
            text = redact(text)
            text = "".join(c for c in text if c in "\n\r\t" or ord(c) >= 32)
            original_chars = len(text)
            truncated = original_chars > MAX_AUTHOR_REPORT_CHARS
            if truncated:
                suffix = "\n[Author report truncated; see recorded character count.]"
                text = text[:MAX_AUTHOR_REPORT_CHARS - len(suffix)] + suffix
            # Plain text, never HTML or proof of tests. The GUI must escape it
            # in exactly the same way as other agent-authored report text.
            doc["author_report"] = text
            doc["author_report_meta"] = {"format": "plain_text", "original_chars": original_chars,
                "truncated": truncated, "analysis_only": True,
                "candidate_digest": ki_verification.content_digest(Path(doc["draft"]["path"]))}
        doc["verification"] = None
        _save(project, doc)
        _RUNNING.discard(job_id)
        _STOPS.pop(job_id, None)
    return get(project, job_id)


def fail(project, job_id, error) -> dict:
    project = _project(project)
    with _LOCK:
        doc = _load(project, job_id)
        if doc["status"] not in {"applied", "applying", "apply_failed"}:
            if doc["status"] != "cancelled":
                doc["status"] = "failed"
            doc["error"] = redact(str(error))
            doc["verification"] = None
            _save(project, doc)
        _RUNNING.discard(job_id)
        _STOPS.pop(job_id, None)
    return get(project, job_id)


def create_draft(project, job_id, ki_name) -> dict:
    project = _project(project)
    with _LOCK:
        doc = _load(project, job_id)
        if doc["status"] != "reviewed" or doc.get("draft"):
            raise InvestigationError("Complete all three reviews before creating one repair draft")
        _assert_current(doc)
        if ki_name not in doc["ki_roots"]:
            raise InvestigationError("KI was not selected in this investigation")
        active = Path(doc["ki_roots"][ki_name])
        expected = project / "models" / ki_name / "ki"
        local = active == expected.resolve() and active.is_relative_to(project)
        parent = _root(project, job_id) / "studio"
        parent.mkdir()
        studio = kdtstudio.create_job(model_name=ki_name, domain="general", source_type="local",
            source=str(Path(doc["context"]["root"]) / "kis" / ki_name),
            provider=doc["provider"], llm_model=doc["model"], parent=str(parent),
            ki_kind=ki_verification.detect_kind(active))
        candidate = Path(studio["candidate"])
        # create_job's candidate is empty; keep the working/materialized revision
        # exactly. No projection or relocation occurs after this gate.
        for item in active.iterdir():
            target = candidate / item.name
            if item.is_symlink():
                raise InvestigationError("A linked KI cannot seed an exact repair draft")
            if item.is_dir():
                shutil.copytree(ki_guard._io(item), ki_guard._io(target), symlinks=True)
            else:
                shutil.copy2(ki_guard._io(item), ki_guard._io(target))
        digest = ki_verification.content_digest(candidate)
        if not digest or digest != ki_verification.content_digest(active):
            raise InvestigationError("KI changed during draft creation")
        evidence = Path(studio["root"]) / "evidence" / "investigation"
        shutil.copytree(ki_guard._io(Path(doc["context"]["root"])), ki_guard._io(evidence))
        _json(Path(studio["root"]) / "evidence" / "combined-review.json", doc["combined_report"])
        doc["draft"] = {"ki_name": ki_name, "studio_job_id": studio["id"], "path": str(candidate),
                        "base_digest": digest, "project_local": local, "active_root": str(active)}
        doc["status"] = "draft"
        _save(project, doc)
    return get(project, job_id)


def mark_verifying(project, job_id) -> dict:
    project = _project(project)
    with _LOCK:
        doc = _load(project, job_id)
        if doc["status"] not in {"draft", "verification_failed", "verified", "verifying"} or job_id in _RUNNING:
            raise InvestigationError("No editable repair draft is available")
        _assert_current(doc)
        ident = uuid.uuid4().hex[:16]
        doc.update(status="verifying", verification={"id": ident, "ok": False, "started": False})
        _save(project, doc)
        _RUNNING.add(job_id)
        _STOPS[job_id] = threading.Event()
    return get(project, job_id)


def _candidate_changes(doc: dict, candidate: Path, digest: str) -> dict:
    """Compare raw-byte identities, independent of the author's change claims."""
    rows = doc["source_state"]["kis/" + doc["draft"]["ki_name"]]["files"]
    baseline = {r["path"]: r["sha256"] for r in rows if r.get("sha256")}
    omitted_before = sorted(r["path"] for r in rows if not r.get("sha256"))
    current, omitted_after = {}, []
    for path, omitted in _files(candidate):
        rel = path.relative_to(candidate).as_posix()
        if omitted:
            omitted_after.append(rel)
        else:
            current[rel] = _hash(path)
    unknown = omitted_before + omitted_after
    def comparable(rel):
        return not any(rel == p or rel.startswith(p + "/") for p in unknown)
    baseline = {p: h for p, h in baseline.items() if comparable(p)}
    current = {p: h for p, h in current.items() if comparable(p)}
    changes = {"added": sorted(current.keys() - baseline.keys()),
               "removed": sorted(baseline.keys() - current.keys()),
               "modified": sorted(p for p in baseline.keys() & current.keys() if baseline[p] != current[p])}
    counts = {name: len(values) for name, values in changes.items()}
    return {"candidate_digest": digest, "baseline_digest": doc["draft"]["base_digest"],
            **{name: values[:MAX_CHANGE_FILES] for name, values in changes.items()},
            "counts": counts, "truncated": any(n > MAX_CHANGE_FILES for n in counts.values()),
            "limit_per_list": MAX_CHANGE_FILES, "complete": not unknown,
            "uncompared_baseline_paths": omitted_before,
            "uncompared_candidate_paths": sorted(omitted_after)}


def verify_draft(project, job_id) -> dict:
    project = _project(project)
    with _LOCK:
        doc = _load(project, job_id)
        if doc["status"] != "verifying":
            mark_verifying(project, job_id)
            doc = _load(project, job_id)
        if job_id not in _RUNNING or doc["verification"].get("started"):
            raise InvestigationError("Verification is interrupted or already executing")
        ident = doc["verification"]["id"]
        doc["verification"]["started"] = True
        _save(project, doc)
    try:
        candidate = Path(doc["draft"]["path"])
        report = ki_verification.verify_candidate(candidate, kind=ki_verification.detect_kind(candidate),
                                                   desktop=True, name=doc["draft"]["ki_name"])
        if report.get("ok"):
            ki_verification.require_current(candidate, report)
        digest = report.get("candidate_digest") or ki_verification.content_digest(candidate)
        if not digest:
            raise InvestigationError("Cannot inventory changes in an irregular candidate tree")
        changes = _candidate_changes(doc, candidate, digest)
        if ki_verification.content_digest(candidate) != digest:
            raise InvestigationError("Candidate changed while its repair diff was checked; verify it again")
        with _LOCK:
            latest = _load(project, job_id)
            if latest["status"] == "cancelled" or latest["verification"]["id"] != ident:
                raise InvestigationError("Verification was cancelled or superseded")
            _assert_current(latest)
            latest["verification"] = {"id": ident, "ok": report.get("ok") is True,
                "candidate_digest": report.get("candidate_digest"), "report": report, "changes": changes,
                "native_regression": {"status": "not_run", "verified": False}}
            latest["status"] = "verified" if report.get("ok") else "verification_failed"
            _save(project, latest)
    except Exception as exc:
        with _LOCK:
            latest = _load(project, job_id)
            if latest["status"] != "cancelled":
                latest.update(status="verification_failed", error=redact(str(exc)))
                _save(project, latest)
        raise
    finally:
        with _LOCK:
            _RUNNING.discard(job_id)
            _STOPS.pop(job_id, None)
    return get(project, job_id)


def _pending_path(project: Path) -> Path:
    return _base(project) / "pending-preflight.json"


def pending_preflight(project) -> dict:
    project = _project(project)
    path = _pending_path(project)
    if not path.exists():
        return {"pending": False, "kis": {}}
    doc = _read_signed(path)
    if doc.get("project") != str(project):
        raise InvestigationError("Project preflight record belongs to another project")
    return {**doc, "pending": any(not row.get("passed") for row in doc["kis"].values())}


def record_preflight(project, ki_name, digest, passed) -> dict:
    """Host callback after real preflight, never an agent-callable evidence tool."""
    project = _project(project)
    with _LOCK:
        doc = pending_preflight(project)
        row = doc["kis"].get(ki_name)
        if row is None:
            return doc
        root = project / "models" / ki_name / "ki"
        ki_guard.require_intact(root)
        if digest != row["digest"] or ki_verification.content_digest(root) != digest:
            raise InvestigationError("Preflight did not check the applied KI revision")
        row.update(passed=passed is True, checked_at=time.time())
        doc.pop("signature", None)
        doc.pop("pending", None)
        _signed(_pending_path(project), doc)
        _signed(project / ".geoforge" / "ki-repair-preflight.json", doc)
    return pending_preflight(project)


def apply(project, job_id, verification_id, quiescent=True) -> dict:
    project = _project(project)
    if not quiescent:
        raise InvestigationError("Stop project workers before applying a KI repair")
    with _LOCK, ExitStack() as stack:
        doc = _load(project, job_id)
        if (doc["status"] != "verified" or not doc.get("verification", {}).get("ok") or
                doc["verification"]["id"] != verification_id):
            raise InvestigationError("Apply requires the exact current verification id")
        _assert_current(doc)
        draft = doc["draft"]
        active, candidate = Path(draft["active_root"]), Path(draft["path"])
        if not draft["project_local"] or active != (project / "models" / draft["ki_name"] / "ki").resolve():
            raise InvestigationError("Repair adoption requires a prepared project-local KI; global catalogues are unchanged")
        for root in sorted(set(doc["ki_roots"].values())):
            stack.enter_context(ki_guard.operation(Path(root)))
            ki_guard._no_workers(Path(root))
        _assert_current(doc)
        # Fail before revoking anything if the host never enrolled this KI.
        if not ki_guard.is_managed(active):
            raise InvestigationError("Project KI lacks its host baseline; prepare it through GeoForge first")
        baseline = ki_guard._read(active)
        if not baseline or baseline["digest"] != doc["baseline_digests"][draft["ki_name"]]:
            raise InvestigationError("Active KI baseline changed since the investigation")
        report = doc["verification"]["report"]
        ki_verification.require_current(candidate, report)
        flow = flowgate.load()
        ctx = flow.states.FlowContext.load(project)
        allowed = {"PLANNING", "PLAN_REVIEW", "WAITING_FOR_USER", "APPROVED", "EXECUTING", "COMPLETED",
                   "BLOCKED", "FAILED", "FAILED_VALIDATION", "REPLAN_REQUIRED", "SETUP_REQUIRED", "SETUP_VERIFIED"}
        if ctx.state.value not in allowed:
            raise InvestigationError(f"Cannot apply repair while project is {ctx.state.value}; stop or finish its active phase")
        prior_approval = flow.approval.approval_id(flow.approval.read(project) or {})
        transaction = {"id": uuid.uuid4().hex[:16], "status": "prepared", "ki_name": draft["ki_name"],
            "old_digest": ki_verification.content_digest(active), "new_digest": report["candidate_digest"],
            "verification_id": verification_id, "prior_approval": prior_approval, "old_state": ctx.state.value,
            "created_at": time.time()}
        doc.update(status="applying", apply=transaction)
        _save(project, doc)
        _RUNNING.add(job_id)
        try:
            flow.approval.revoke(project, f"User applied KI repair {job_id}/{verification_id}; fresh review required")
            transaction["status"] = "approval_revoked"
            _save(project, doc)
            # Persist the deny-by-default preflight requirement before any
            # replacement. A crash after adoption must not expose the new KI
            # under an old shared-installation readiness report.
            pending = pending_preflight(project)
            pending["kis"][draft["ki_name"]] = {"digest": report["candidate_digest"], "passed": False,
                                                    "job_id": job_id, "verification_id": verification_id}
            _signed(_pending_path(project), {"project": str(project), "kis": pending["kis"]})
            _signed(project / ".geoforge" / "ki-repair-preflight.json", {"project": str(project), "kis": pending["kis"]})
            recorded_dirty = doc["ki_digests"][draft["ki_name"]] != baseline["digest"]
            recovered = ki_guard.recover_drift(active, quiescent=True) if recorded_dirty else None
            adopted = ki_guard.activate(active, candidate, report, quiescent=True)
            transaction.update(status="adopted", recovered_draft=str(recovered) if recovered else None,
                               adopted_digest=adopted["digest"])
            _save(project, doc)
            history = _root(project, job_id) / "prior-project-state"
            for rel in (setup_flow.REQUEST_FILE, "runs/plan-review.json"):
                source = project / rel
                if source.is_file():
                    target = history / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    source.unlink()
            # Host-only invalidation. REPLAN_REQUIRED grants planning, never
            # execution. No generic agent transition or approval is added.
            ctx.state = flow.states.State.REPLAN_REQUIRED
            ctx.approval_sha256 = None
            ctx.save()
            generation = uuid.uuid4().hex
            reason = f"KI repair {job_id} applied to {draft['ki_name']}; review the revised plan and verify this exact KI before continuing."
            transaction.update(status="complete", generation=generation, applied_at=time.time(), resume_reason=reason,
                               native_verified=False, requires_plan_review=True, requires_preflight=True)
            doc.update(status="applied", apply=transaction)
            _save(project, doc)
        except Exception as exc:
            transaction.update(status="needs_recovery", error=redact(str(exc)))
            doc.update(status="apply_failed", apply=transaction, error=redact(str(exc)))
            _save(project, doc)
            raise InvestigationError("Repair transaction stopped; old approval remains revoked. Inspect the retained repair journal: " + str(exc)) from exc
        finally:
            _RUNNING.discard(job_id)
    return get(project, job_id)
