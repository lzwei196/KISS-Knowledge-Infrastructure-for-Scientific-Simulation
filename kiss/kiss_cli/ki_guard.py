"""Host-managed active KI baselines and explicit, verified candidate adoption.

This is an integrity boundary at host operations, not an OS filesystem sandbox.
External processes with the user's permissions can write files; their changes
must not become a verified active KI merely because a provider returned success.
"""
from __future__ import annotations

import hashlib
import contextlib
import json
import os
import shutil
import sys
import threading
import uuid
from pathlib import Path

from . import firstrun


class KIIntegrityError(ValueError):
    pass


_LOCK = threading.RLock()
_WORKERS: dict[str, threading.RLock] = {}
_ACTIVE: dict[str, int] = {}


def _io(path: Path) -> Path:
    """Extended Win32 spelling for host backup I/O, not native model argv."""
    path = Path(path).absolute()
    value = str(path)
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
    return Path(value)


@contextlib.contextmanager
def operation(root: Path | None):
    """Serialize short host metadata/copy operations for one KI.

    This does not exclude external applications or other same-user processes.
    """
    if root is None:
        yield
        return
    key = os.path.normcase(str(Path(root).absolute()))
    with _LOCK:
        lock = _WORKERS.setdefault(key, threading.RLock())
    with lock:
        yield


@contextlib.contextmanager
def worker(root: Path | None):
    """Count live host workers without blocking cross-thread tool callbacks."""
    if root is None:
        yield
        return
    key = os.path.normcase(str(Path(root).absolute()))
    with operation(root), _LOCK:
        _ACTIVE[key] = _ACTIVE.get(key, 0) + 1
    try:
        yield
    finally:
        with operation(root), _LOCK:
            _ACTIVE[key] -= 1
            if not _ACTIVE[key]:
                _ACTIVE.pop(key)


def _no_workers(root: Path) -> None:
    key = os.path.normcase(str(Path(root).absolute()))
    if _ACTIVE.get(key, 0):
        raise KIIntegrityError("A host worker still uses this KI; recovery/adoption is deferred")


def _home() -> Path:
    override = os.environ.get("GEOFORGE_KI_GUARD_HOME")
    return Path(override).resolve() if override else firstrun.data_dir() / "ki-guard"


def _entry(root: Path) -> Path:
    identity = os.path.normcase(str(Path(root).absolute()))
    return _home() / hashlib.sha256(identity.encode()).hexdigest()[:12]


def _digest(root: Path) -> str:
    from .ki_verification import content_digest
    value = content_digest(_io(root))
    if not value:
        raise KIIntegrityError(f"Cannot establish a regular, contained KI tree: {root}")
    return value


def _copy(source: Path, target: Path) -> None:
    # Preserve exact bytes, including pre-existing caches. Hosted Python calls
    # suppress new bytecode; no source filename is silently excluded.
    _digest(source)
    shutil.copytree(_io(source), _io(target), symlinks=True)
    if _digest(source) != _digest(target):
        raise KIIntegrityError("KI changed while copying; nothing was activated")


def _read(root: Path) -> dict | None:
    from . import flowgate
    receipts = flowgate.load().receipts
    path = _io(_entry(root) / "baseline.json")
    if not path.exists():
        return None
    if _home() == root or root in _home().parents:
        raise KIIntegrityError("KI baseline records must stay outside the KI")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        valid = (isinstance(doc, dict) and receipts.verify(root, doc)
                 and doc.get("root") == str(root.absolute()))
    except (OSError, ValueError, TypeError) as exc:
        raise KIIntegrityError("Active KI baseline cannot be read") from exc
    if not valid:
        raise KIIntegrityError("Active KI baseline signature is invalid")
    return doc


def _save(root: Path, digest: str, *, origin: str) -> dict:
    from . import flowgate
    receipts = flowgate.load().receipts
    doc = receipts.sign(root, {"schema_version": 1, "root": str(root.absolute()),
                              "digest": digest, "origin": origin})
    entry = _entry(root)
    _io(entry).mkdir(parents=True, exist_ok=True)
    temp = entry / f"state-{uuid.uuid4().hex}.tmp"
    _io(temp).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    _io(temp).replace(_io(entry / "baseline.json"))
    return doc


def is_managed(root: Path) -> bool:
    return _io(_entry(Path(root)) / "baseline.json").exists()


def _legacy_installation_roots() -> list[Path]:
    """The installed app's bootstrap locations, never cwd or a --models argument."""
    package = Path(__file__).resolve().parents[1]
    roots = [package.parent / "models", package / "data_kis",
             firstrun.data_dir() / "models", firstrun.data_dir() / "user_models",
             Path.home() / "kiss" / "models"]
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent / "models")
        bundled = getattr(sys, "_MEIPASS", None)
        if bundled:
            roots.extend([Path(bundled) / "models", Path(bundled) / "data_kis"])
    return list(dict.fromkeys(path.resolve() for path in roots))


def _legacy_inventory() -> tuple[dict, bool]:
    """Issue one host-wide migration inventory, not a new allowance per folder.

    An upgrade from the initial guard imports only signed recorded identities.
    A genuinely new install snapshots its known installed/default package roots
    once. Unrecognised --models directories never contribute bootstrap bytes.
    """
    from . import flowgate
    receipts = flowgate.load().receipts
    authority = _home() / "catalogues"
    path = _io(authority / "legacy-inventory.json")
    with operation(authority):
        if path.exists():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                if (not receipts.verify(authority, doc) or doc.get("schema_version") != 1
                        or doc.get("origin") != "one_time_legacy_inventory"):
                    raise KIIntegrityError("Legacy KI inventory signature is invalid")
                return doc, False
            except (OSError, ValueError, TypeError) as error:
                raise KIIntegrityError(f"Cannot read legacy KI inventory: {error}") from error
        records: dict[tuple[str, str], dict] = {}

        def add(root, digest, origin):
            if (not isinstance(root, str) or not isinstance(digest, str)
                    or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
                raise KIIntegrityError("Recorded KI provenance has an invalid content identity")
            records[(root, digest)] = {"root": root, "digest": digest, "origin": origin}

        catalogues = list(_io(authority).glob("*.json")) if _io(authority).is_dir() else []
        for prior_path in catalogues:
            try:
                prior = json.loads(prior_path.read_text(encoding="utf-8"))
                source = Path(prior["root"])
                if (not receipts.verify(source, prior) or
                        prior.get("origin") != "host_catalogue_baseline"):
                    raise KIIntegrityError("Prior catalogue signature is invalid")
                for item in (prior.get("models") or {}).values():
                    add(item["root"], item["digest"], "signed_catalogue")
            except (OSError, KeyError, ValueError, TypeError) as error:
                raise KIIntegrityError(f"Cannot migrate prior catalogue {prior_path.name}: {error}") from error
        # Explicitly enrolled installations/projects are also existing host
        # provenance. Read their recorded hashes, never newly edited bytes.
        for prior_path in _io(_home()).glob("*/baseline.json"):
            try:
                prior = json.loads(prior_path.read_text(encoding="utf-8"))
                source = Path(prior["root"])
                if not receipts.verify(source, prior):
                    raise KIIntegrityError("Prior KI baseline signature is invalid")
                add(prior["root"], prior["digest"], "signed_baseline")
            except (OSError, KeyError, ValueError, TypeError) as error:
                raise KIIntegrityError(f"Cannot migrate prior KI baseline: {error}") from error
        if not catalogues:
            # Gather all known roots at once, so starting with a data-only or
            # alternate catalogue does not consume migration for built-in KIs.
            recorded_roots = {os.path.normcase(str(Path(item["root"]).absolute()))
                              for item in records.values()}
            for installed in _legacy_installation_roots():
                if not installed.is_dir():
                    continue
                for root in installed.iterdir():
                    if root.is_dir() and (root / "SKILL.md").is_file():
                        if os.path.normcase(str(root.absolute())) in recorded_roots:
                            continue  # Recorded original bytes outrank edited disk bytes.
                        add(str(root.absolute()), _digest(root), "installed_bootstrap")
        doc = receipts.sign(authority, {
            "schema_version": 1, "origin": "one_time_legacy_inventory",
            "models": sorted(records.values(), key=lambda item: (item["root"], item["digest"])),
        })
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + f".{uuid.uuid4().hex[:8]}.tmp")
        temp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        temp.replace(path)
        return doc, True


def enroll_catalogue(catalog) -> dict:
    """Bind a catalogue to recorded legacy bytes or current KDT acceptance.

    Later unknown names need a current KDT acceptance. A signed first-use list
    binds legacy source bytes; this migration does not claim KDT verification.
    Individual failures are returned so unrelated KIs remain available.
    """
    from . import flowgate, ki_verification
    source = Path(catalog.models_dir).absolute()
    authority = _home() / "catalogues"
    key = hashlib.sha256(os.path.normcase(str(source)).encode()).hexdigest()[:12]
    path = _io(authority / f"{key}.json")
    receipts = flowgate.load().receipts
    result = {"enrolled": [], "errors": {}, "legacy_migration": False}
    try:
        legacy, migrated = _legacy_inventory()
        legacy_digests = {item["digest"] for item in legacy["models"]}
        result["legacy_migration"] = migrated
    except (OSError, ValueError, RuntimeError) as error:
        return {**result, "errors": {ki.name: str(error) for ki in catalog}}
    with operation(source):
        prior = None
        if path.exists():
            try:
                prior = json.loads(path.read_text(encoding="utf-8"))
                if not receipts.verify(source, prior) or prior.get("root") != str(source):
                    raise KIIntegrityError("Catalogue baseline signature is invalid")
            except (OSError, ValueError, TypeError) as exc:
                return {**result, "errors": {ki.name: str(exc) for ki in catalog}}
        known = dict((prior or {}).get("models") or {})
        for ki in catalog:
            root = Path(ki.root).absolute()
            try:
                digest = _digest(root)
                before = known.get(ki.name)
                if before is not None:
                    if before != {"root": str(root), "digest": digest}:
                        accepted = _read(root)
                        if (before.get("root") != str(root) or accepted is None or
                                accepted.get("origin") != "verified_candidate" or accepted.get("digest") != digest):
                            raise KIIntegrityError("Catalogue KI differs from its host baseline; explicit verified adoption is required")
                else:
                    known_baseline = _read(root)
                    recorded = bool(known_baseline and known_baseline.get("digest") == digest)
                    if not recorded and digest not in legacy_digests:
                        kind = ki_verification.detect_kind(root)
                        if ki_verification.current_report(root, kind=kind) is None:
                            raise KIIntegrityError(
                                "New catalogue KI has no current KDT acceptance or exact recorded legacy provenance; "
                                "a new --models directory cannot restart migration")
                # Record source identity even if backing up a legacy tree fails;
                # a later attempt can only retry those same recorded bytes.
                known[ki.name] = {"root": str(root), "digest": digest}
                enroll(root)
                result["enrolled"].append(ki.name)
            except (OSError, ValueError, RuntimeError) as exc:
                result["errors"][ki.name] = str(exc)
        doc = receipts.sign(source, {"schema_version": 1, "root": str(source),
                                     "origin": "host_catalogue_baseline", "models": known})
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + f".{uuid.uuid4().hex[:8]}.tmp")
        temp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        temp.replace(path)
    return result


def enroll(root: Path) -> dict:
    """Host creation/explicit legacy migration only; never called on agent exit."""
    root = Path(root).absolute()
    if root.is_symlink():
        raise KIIntegrityError("Cannot enroll a linked KI root")
    if _home() == root or root in _home().parents:
        raise KIIntegrityError("KI baseline records must stay outside the KI")
    with operation(root), _LOCK:
        if _read(root) is not None:
            return require_intact(root)
        digest = _digest(root)
        entry = _entry(root)
        backup = entry / digest[:12]
        _io(entry).mkdir(parents=True, exist_ok=True)
        if not _io(backup).exists():
            _copy(root, backup)
        if _digest(backup) != digest:
            raise KIIntegrityError("Saved KI baseline content is inconsistent")
        return _save(root, digest, origin="existing_host_baseline")


def require_intact(root: Path, *, required: bool = True) -> dict | None:
    """Never enroll or accept changed bytes as a new baseline."""
    root = Path(root).absolute()
    with operation(root), _LOCK:
        doc = _read(root)
        if doc is None:
            if not required:
                return None
            raise KIIntegrityError(f"KI has no host baseline: {root}")
        if root.is_symlink() or _digest(root) != doc["digest"]:
            raise KIIntegrityError(
                f"Active KI changed: {root}. Keep edits in a KI draft and verify "
                "the exact candidate through KDT before adoption; this KI cannot run or be marked ready.")
        return doc


def reject_write(root: Path, path: Path) -> None:
    root, path = Path(root).resolve(), Path(path).resolve()
    if is_managed(root) and (path == root or root in path.parents):
        raise KIIntegrityError(
            "Active KI files are read-only to setup/project tools. Create a KI draft; "
            "only an exact candidate passing the host KDT gate may be adopted.")


def preserve_drift(root: Path) -> Path | None:
    """Copy changed bytes for review; never alter a possibly still-used tree."""
    root = Path(root).absolute()
    with operation(root), _LOCK:
        doc = _read(root)
        if doc is None or _digest(root) == doc["digest"]:
            return None
        draft = root.parent / f"ki-draft-{uuid.uuid4().hex[:12]}"
        _copy(root, draft)
        return draft


def recover_drift(root: Path, *, quiescent: bool = False) -> Path | None:
    """Preserve changed bytes and restore known source only after workers stop.

    Both trees are renamed locally; the rejected tree is never deleted. If any
    verification or rename fails, fail closed instead of claiming restoration.
    """
    root = Path(root).absolute()
    with operation(root), _LOCK:
        doc = _read(root)
        if doc is None:
            return None
        try:
            if _digest(root) == doc["digest"]:
                return None
        except KIIntegrityError:
            pass
        if not quiescent:
            raise KIIntegrityError("KI drift detected; stop active workers before preserving/restoring the KI")
        _no_workers(root)
        if root.is_symlink() or not root.is_dir():
            raise KIIntegrityError("KI root was replaced or removed; manual recovery is required")
        backup = _entry(root) / doc["digest"][:12]
        if _digest(backup) != doc["digest"]:
            raise KIIntegrityError("Known KI backup failed its content check; restoration refused")
        restored = root.parent / f".ki-restore-{uuid.uuid4().hex[:12]}"
        draft = root.parent / f"ki-draft-{uuid.uuid4().hex[:12]}"
        _copy(backup, restored)
        _io(root).rename(_io(draft))
        try:
            _io(restored).rename(_io(root))
        except OSError:
            _io(draft).rename(_io(root))
            raise
        require_intact(root)
        return draft


def activate(root: Path, draft: Path, report: dict, *, quiescent: bool = False) -> dict:
    """Explicit host adoption; callers own user review and project invalidation."""
    from .ki_verification import require_current, detect_kind
    if not quiescent:
        raise KIIntegrityError("Stop active workers before adopting a KI revision")
    root, draft = Path(root).resolve(), Path(draft).resolve()
    if root == draft or root in draft.parents or draft in root.parents:
        raise KIIntegrityError("Candidate and active KI must be separate trees")
    with operation(root), _LOCK:
        _no_workers(root)
        require_intact(root)
        require_current(draft, report, kind=detect_kind(draft))
        digest = _digest(draft)
        replacement = root.parent / f".ki-adopt-{uuid.uuid4().hex[:12]}"
        _copy(draft, replacement)
        require_current(draft, report, kind=detect_kind(draft))
        if _digest(replacement) != digest:
            raise KIIntegrityError("Candidate copy does not match the verified bytes")
        backup = _entry(root) / digest[:12]
        if not _io(backup).exists():
            _copy(replacement, backup)
        if _digest(backup) != digest:
            raise KIIntegrityError("Candidate backup failed its content check")
        previous = root.parent / f"ki-previous-{uuid.uuid4().hex[:12]}"
        _io(root).rename(_io(previous))
        try:
            _io(replacement).rename(_io(root))
            return _save(root, digest, origin="verified_candidate")
        except (OSError, ValueError):
            # Preserve both revisions; a failed state update must not activate.
            if root.exists():
                _io(root).rename(_io(replacement))
            _io(previous).rename(_io(root))
            raise
