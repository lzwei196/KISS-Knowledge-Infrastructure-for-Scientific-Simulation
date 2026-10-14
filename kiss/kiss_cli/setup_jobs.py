"""Durable ownership and cancellation for standalone Desktop setup attempts.

An OS-held lease owns both the selected model and its canonical installation
folder. The record lock linearizes Stop and terminal bookkeeping; a saved PID
is never used to decide ownership or terminate a process.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid

from . import api, execution, install, install_locations


ACTIVE = frozenset({"running", "stopping"})
TERMINAL = frozenset({"completed", "failed", "cancelled", "interrupted", "waiting_for_user"})
_LIVE: dict[str, "Job"] = {}
_LIVE_LOCK = threading.RLock()
_RECORD_LOCKS: dict[str, threading.RLock] = {}
_RECORD_LOCKS_LOCK = threading.Lock()
_POLL = 0.1
_PENDING_VERIFICATION_DETAIL = "Setup is running; verification is pending."


class BusyError(RuntimeError):
    def __init__(self, job: dict):
        self.job = job
        super().__init__("This model or installation folder already has an active setup operation.")


def _canonical(path) -> Path:
    return Path(path).expanduser().resolve()


def _model(model) -> str:
    name = str(model or "").strip()
    if not name:
        raise ValueError("model name is required")
    return name


def _paths(workroot, model):
    workroot = _canonical(workroot)
    key = hashlib.sha256(_model(model).casefold().encode("utf-8")).hexdigest()
    base = workroot / ".geoforge" / "setup-jobs"
    return base / (key + ".json"), base / (key + ".lease"), base / (key + ".lock")


def _root_lease(root: Path) -> Path:
    return root / ".geoforge" / "setup-job.lease"


def _root_record(root: Path) -> Path:
    return root / ".geoforge" / "setup-job-owner.json"


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        pending.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for attempt in range(40):
            try:
                pending.replace(path)
                break
            except PermissionError:
                if os.name != "nt" or attempt == 39:
                    raise
                time.sleep(0.025)
    finally:
        pending.unlink(missing_ok=True)


class _FileLock:
    """Independent file handles also exclude other threads in this process."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        self.held = False
        self.file.seek(0, os.SEEK_END)
        if not self.file.tell():
            self.file.write(b"\0")
            self.file.flush()

    def acquire(self, *, blocking=False) -> bool:
        while True:
            try:
                self.file.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.held = True
                return True
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                if not blocking:
                    return False
                time.sleep(0.025)

    def close(self):
        try:
            if self.held:
                self.file.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.held = False
            self.file.close()


@contextmanager
def _record_lock(path: Path):
    key = os.path.normcase(str(path))
    with _RECORD_LOCKS_LOCK:
        mutex = _RECORD_LOCKS.setdefault(key, threading.RLock())
    with mutex:
        lock = _FileLock(path)
        try:
            lock.acquire(blocking=True)
            yield
        finally:
            lock.close()


def _public(doc: dict) -> dict:
    value = dict(doc)
    value["active"] = value.get("state") in ACTIVE
    value["can_stop"] = value.get("state") == "running"
    return value


def _busy(workroot, model, root, *, root_conflict=False) -> BusyError:
    path, _, _ = _paths(workroot, model)
    doc = _read(_root_record(root)) if root_conflict else _read(path)
    if not doc or doc.get("state") not in ACTIVE:
        doc = {"id": None, "model": model, "root": str(root), "state": "busy",
               "active": True, "can_stop": False}
    return BusyError(_public(doc) if doc.get("state") in ACTIVE else doc)


def _leases(workroot, model, root):
    _, model_path, _ = _paths(workroot, model)
    model_lock = _FileLock(model_path)
    root_lock = None
    try:
        if not model_lock.acquire():
            raise _busy(workroot, model, root)
        root_lock = _FileLock(_root_lease(root))
        if not root_lock.acquire():
            raise _busy(workroot, model, root, root_conflict=True)
        return model_lock, root_lock
    except BaseException:
        if root_lock is not None:
            root_lock.close()
        model_lock.close()
        raise


def _revoke(root: Path, model: str, detail: str, *, preserve_error=False) -> None:
    """Revoke readiness only while holding this installation folder's lease."""
    path = root / "status.json"
    doc = _read(path) or {}
    error = (doc.get("primary_error") if preserve_error and not doc.get("ok") else None)
    # Preserve a concrete preflight/integrity diagnosis, but the initial
    # running placeholder cannot remain the reason for a terminal failure.
    if (isinstance(error, dict) and error.get("name") == "setup-job"
            and error.get("detail") == _PENDING_VERIFICATION_DETAIL):
        error = None
    doc.update(model=model, ok=False, verified_at=None, verification_identity=None,
               runtime_identity=None, ki_content_digest=None,
               primary_error=error or {"name": "setup-job", "detail": detail})
    _write(path, doc)
    install_locations.invalidate_verification(root)
    probe_path = root / "installation-test.json"
    probe = _read(probe_path)
    if probe is not None:
        probe.update(usable=False, state="interrupted", summary=detail)
        _write(probe_path, probe)


@contextmanager
def idle_guard(workroot, model, root=None):
    """Exclude setup while a host changes setup location or resumes a request."""
    model = _model(model)
    root = _canonical(root if root is not None else install_locations.resolve(workroot, model))
    leases = _leases(workroot, model, root)
    try:
        yield
    finally:
        for lease in reversed(leases):
            lease.close()


class Job:
    def __init__(self, workroot, doc, leases):
        self.workroot = _canonical(workroot)
        self.root = Path(doc["root"])
        self.id = doc["id"]
        self.turn_id = doc["turn_id"]
        self.model = doc["model"]
        self.handle = api.TurnHandle()
        self.events = {"_handle": self.handle, "project": str(self.root),
                       "_turn_id": self.turn_id, "provider": doc["provider"]}
        self._doc = doc
        self._leases = leases
        self._done = threading.Event()
        self._signalled = False
        self._signal_lock = threading.Lock()
        self._path, _, self._lockpath = _paths(workroot, self.model)

    def _signal(self):
        with self._signal_lock:
            if self._signalled:
                return
            # Closing an HTTP response can block: neither Stop's HTTP handler
            # nor CLI termination waits for that transport cleanup.
            self.handle.stopped.set()
            try:
                threading.Thread(target=self.handle.stop, daemon=True,
                                 name="geoforge-setup-response-stop").start()
            except RuntimeError:
                pass  # Resource exhaustion must not prevent process cleanup.
            proc = self.events.get("_process_handle")
            if proc is not None and proc.poll() is None:
                try:
                    execution.terminate_tree(proc)
                except OSError:
                    pass  # It may have exited after poll().
            # Publish only after terminate_tree has registered its escalation
            # worker. Shutdown may now safely snapshot/wait for those workers.
            self._signalled = True

    def _watch(self):
        while not self._done.wait(_POLL):
            try:
                doc = _read(self._path)
                if ((doc and doc.get("id") == self.id and doc.get("state") == "stopping") or
                        execution.stop_requested(self.root, turn_id=self.turn_id)):
                    self._signal()
                    return
            except OSError:
                # Temporary Windows reader/rename contention does not revoke
                # ownership; the next poll observes the durable stop intent.
                continue

    def check_cancelled(self):
        if (self._done.is_set() or self.handle.stopped.is_set() or
                execution.stop_requested(self.root, turn_id=self.turn_id)):
            raise install.InstallStopped("Stopped by the user; setup was interrupted.")

    def request_stop(self) -> dict:
        """Stop the owned worker even if durable stop bookkeeping cannot write."""
        try:
            return stop(self.workroot, self.model, self.id)
        finally:
            self._signal()

    def snapshot(self) -> dict:
        with _record_lock(self._lockpath):
            doc = _read(self._path)
            return _public(doc if doc and doc.get("id") == self.id else self._doc)

    def update(self, *, phase=None, detail=None) -> dict:
        with _record_lock(self._lockpath):
            doc = _read(self._path)
            if not doc or doc.get("id") != self.id or self._done.is_set():
                return _public(self._doc)
            if phase is not None:
                doc["phase"] = str(phase)
            if detail is not None:
                doc["detail"] = str(detail)
            doc["updated_at"] = time.time()
            _write(self._path, doc)
            self._doc = doc
            return _public(doc)

    def finish(self, state: str, detail: str = "", cleanup=None) -> dict:
        """Commit one terminal state; cleanup(state) runs before releasing ownership.

        Stop and this commit use the same lock. A Stop accepted before this
        commit dominates even a successful verification performed just before it.
        """
        if state not in TERMINAL:
            raise ValueError(f"invalid terminal setup state: {state}")
        with _record_lock(self._lockpath):
            if self._done.is_set():
                return _public(self._doc)
            try:
                doc = _read(self._path)
                if not doc or doc.get("id") != self.id:
                    raise ValueError("setup job record changed before completion")
                cancelled = (state == "cancelled" or doc.get("state") == "stopping" or self.handle.stopped.is_set() or
                             execution.stop_requested(self.root, turn_id=self.turn_id))
                if cancelled:
                    state = "cancelled"
                if state in {"cancelled", "failed", "interrupted"}:
                    _revoke(self.root, self.model, detail or f"Setup {state}; verification is required.",
                            preserve_error=state == "failed")
                if cleanup is not None:
                    try:
                        cleanup(state)
                    except Exception as error:
                        state = "cancelled" if cancelled else "failed"
                        detail = (detail + "\n" if detail else "") + f"Setup cleanup failed: {error}"
                        _revoke(self.root, self.model, detail)
                now = time.time()
                doc.update(state=state, detail=str(detail), updated_at=now,
                           finished_at=now, ended_at=now)
                _write(self._path, doc)
                _write(_root_record(self.root), doc)
                self._doc = doc
                return _public(doc)
            finally:
                self._done.set()
                with _LIVE_LOCK:
                    _LIVE.pop(self.id, None)
                for lease in reversed(self._leases):
                    lease.close()


def start(workroot, model, root, provider, installation_only=False) -> Job:
    model, root = _model(model), _canonical(root)
    # Recover the old folder before a user switches this model to a new one.
    status(workroot, model)
    leases = _leases(workroot, model, root)
    path, _, lockpath = _paths(workroot, model)
    try:
        with _record_lock(lockpath):
            _revoke(root, model, _PENDING_VERIFICATION_DETAIL)
            turn_id = execution.begin_turn(root)
            now = time.time()
            doc = {"schema_version": 1, "id": uuid.uuid4().hex, "model": model,
                   "root": str(root), "provider": str(provider),
                   "installation_only": bool(installation_only), "state": "running",
                   "phase": "preparing", "detail": "", "started_at": now,
                   "updated_at": now, "finished_at": None, "ended_at": None,
                   "turn_id": turn_id}
            _write(path, doc)
            _write(_root_record(root), doc)
            job = Job(workroot, doc, leases)
            with _LIVE_LOCK:
                _LIVE[job.id] = job
            threading.Thread(target=job._watch, daemon=True,
                             name="geoforge-setup-stop-watch").start()
            return job
    except BaseException:
        for lease in reversed(leases):
            lease.close()
        raise


def status(workroot, model) -> dict | None:
    """Read status, recovering an abandoned attempt only after proving ownership."""
    path, leasepath, lockpath = _paths(workroot, model)
    if not path.exists():
        return None
    with _record_lock(lockpath):
        doc = _read(path)
        if not doc or doc.get("state") not in ACTIVE:
            return _public(doc) if doc else None
        model_lock = _FileLock(leasepath)
        root_lock = None
        try:
            if not model_lock.acquire():
                return _public(doc)
            root = _canonical(doc["root"])
            root_lock = _FileLock(_root_lease(root))
            if not root_lock.acquire():
                # Another model or a location mutation owns this folder. Do not
                # revoke its result. Recover once the folder is idle again.
                value = _public(doc)
                value.update(can_stop=False, recovery_pending=True)
                return value
            owner = _read(_root_record(root))
            owns_record = not owner or owner.get("id") == doc.get("id")
            # A different model may have subsequently completed setup in this
            # same folder. Its newer verified result must remain untouched.
            if owns_record:
                # An orphaned CLI may still have the old generation captured.
                # Revoke that generation cooperatively; never act on a saved
                # PID or place an old marker into a newer turn.
                if execution.current_turn_id(root) == doc.get("turn_id"):
                    execution.request_stop(root)
                _revoke(root, str(doc["model"]), "Setup was interrupted when its owning app stopped.")
            now = time.time()
            doc.update(state="interrupted", detail="The owning app stopped before setup finished.",
                       updated_at=now, finished_at=now, ended_at=now)
            _write(path, doc)
            if owns_record:
                _write(_root_record(root), doc)
            return _public(doc)
        finally:
            if root_lock is not None:
                root_lock.close()
            model_lock.close()


def stop(workroot, model, job_id) -> dict:
    """Accept Stop for this exact attempt; the owner's watcher handles transports."""
    status(workroot, model)
    path, _, lockpath = _paths(workroot, model)
    with _record_lock(lockpath):
        doc = _read(path)
        if not doc or not job_id or doc.get("id") != job_id:
            raise ValueError("The setup attempt changed; refresh its status before stopping.")
        if doc.get("state") not in ACTIVE:
            return _public(doc)
        root = _canonical(doc["root"])
        # A later generation must never receive an old browser tab's marker.
        if execution.current_turn_id(root) == doc.get("turn_id"):
            execution.request_stop(root)
        now = time.time()
        doc.update(state="stopping", updated_at=now,
                   stop_requested_at=doc.get("stop_requested_at") or now)
        _write(path, doc)
        return _public(doc)


def stop_all() -> None:
    with _LIVE_LOCK:
        jobs = list(_LIVE.values())
    for job in jobs:
        try:
            stop(job.workroot, job.model, job.id)
        except (OSError, ValueError):
            # The handle belongs to this process, so it is safe even if a
            # damaged record prevents durable stop bookkeeping.
            job.handle.stopped.set()
        job._signal()
