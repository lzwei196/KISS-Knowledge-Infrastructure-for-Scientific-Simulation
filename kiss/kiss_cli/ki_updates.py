"""Validated, non-blocking updates for GeoForge's curated KI library.

The desktop app ships a known-good KI snapshot so it always starts offline.
On each desktop launch this module checks the platform branch of GeoForge's
public repository.  A changed library is downloaded into a versioned staging
directory, checked with the same deterministic package verifier used by the
Library import screen, and only then made active.

Updates never touch chat projects, installed scientific software, input data,
or user-imported KIs.  Old snapshots remain available while a running request
may still hold a path into them, so activation is a pointer switch rather than
an in-place rewrite.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import quote

from . import doctor, firstrun, tls
from .catalog import Catalog


REPOSITORY = "lzwei196/KISS---Knowledge-Infrastructure-for-Scientific-Simulation"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
ARCHIVE_ROOT = f"https://codeload.github.com/{REPOSITORY}/zip/refs/heads"
MAX_ARCHIVE_BYTES = 900 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 50_000


def branch_for_platform() -> str:
    override = os.environ.get("GEOFORGE_KI_UPDATE_BRANCH", "").strip()
    if override:
        return override
    system = platform.system()
    if system == "Darwin":
        return "mac-version"
    if system == "Windows":
        return "windows-version"
    return "main"


def update_root() -> Path:
    override = os.environ.get("GEOFORGE_KI_UPDATE_HOME", "").strip()
    return (Path(override).expanduser().resolve() if override else
            firstrun.data_dir() / "ki-updates")


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def active_library_root() -> Path | None:
    """Return the last activated snapshot, never a path supplied by JSON."""
    home = update_root()
    active = str(_read_json(home / "state.json").get("active_snapshot") or "")
    if not active or not all(c in "0123456789abcdef-" for c in active.lower()):
        return None
    candidate = (home / "snapshots" / active).resolve()
    snapshots = (home / "snapshots").resolve()
    try:
        candidate.relative_to(snapshots)
    except ValueError:
        return None
    if ((candidate / "models").is_dir() and
            any((candidate / "models").glob("*/SKILL.md"))):
        return candidate
    return None


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_digests(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_dir():
        return out
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if not (item.is_file() or item.is_symlink()):
            continue
        rel = item.relative_to(path).as_posix()
        if item.is_symlink():
            out[rel] = "link:" + os.readlink(item)
        else:
            out[rel] = _file_digest(item)
    return out


def _package_files(library_root: Path, name: str) -> dict[str, str]:
    files = _file_digests(library_root / "models" / name)
    manifest = library_root / "kiss" / "manifests" / f"{name}.yaml"
    if manifest.is_file():
        files["@shared-manifest"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return files


def _library_diff(before: Path, after: Path) -> dict:
    old_names = ({p.name for p in (before / "models").iterdir()
                  if p.is_dir() and (p / "SKILL.md").is_file()}
                 if (before / "models").is_dir() else set())
    new_names = ({p.name for p in (after / "models").iterdir()
                  if p.is_dir() and (p / "SKILL.md").is_file()}
                 if (after / "models").is_dir() else set())
    added = sorted(new_names - old_names)
    removed = sorted(old_names - new_names)
    changed: list[dict] = []
    unchanged = 0
    for name in sorted(old_names & new_names):
        old = _package_files(before, name)
        new = _package_files(after, name)
        if old == new:
            unchanged += 1
            continue
        changed.append({
            "name": name,
            "added_files": sorted(set(new) - set(old))[:20],
            "updated_files": sorted(key for key in set(old) & set(new)
                                    if old[key] != new[key])[:20],
            "removed_files": sorted(set(old) - set(new))[:20],
        })
    return {
        "added": added,
        "updated": [row["name"] for row in changed],
        "removed": removed,
        "unchanged_count": unchanged,
        "changes": changed,
    }


class UpdateManager:
    """Own one launch's update check and its user-facing report."""

    def __init__(self, current_library_root: Path,
                 activate: Callable[[Path], None], branch: str | None = None):
        self.current_library_root = Path(current_library_root).resolve()
        self.activate = activate
        self.branch = branch or branch_for_platform()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        previous = _read_json(update_root() / "last-report.json")
        self._report = previous or {
            "state": "idle",
            "summary": "KI updates have not been checked yet.",
            "source_url": REPOSITORY_URL,
            "branch": self.branch,
        }

    def status(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._report))

    def _set(self, **values) -> None:
        with self._lock:
            self._report = {**self._report, **values,
                            "source_url": REPOSITORY_URL,
                            "branch": self.branch}
            _atomic_json(update_root() / "last-report.json", self._report)

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._report = {
                **self._report,
                "state": "checking",
                "summary": "Checking the GeoForge repository for KI updates…",
                "started_at": time.time(),
                "source_url": REPOSITORY_URL,
                "branch": self.branch,
            }
            _atomic_json(update_root() / "last-report.json", self._report)
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="geoforge-ki-update")
            self._thread.start()
            return True

    def wait(self, timeout: float | None = None) -> dict:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return self.status()

    def _request_json(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "GeoForge-Desktop-KI-Updater",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(request, timeout=30, context=tls.context()) as response:
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("GitHub returned an invalid repository response")
        return value

    def _remote_revision(self) -> tuple[str, str, str]:
        root = self._request_json(
            f"{API_ROOT}/git/trees/{quote(self.branch, safe='')}")
        entries = {row.get("path"): row for row in root.get("tree") or []
                   if isinstance(row, dict)}
        models_sha = str((entries.get("models") or {}).get("sha") or "")
        kiss_sha = str((entries.get("kiss") or {}).get("sha") or "")
        if not models_sha or not kiss_sha:
            raise RuntimeError(
                f"the {self.branch} branch does not contain models/ and kiss/")
        kiss = self._request_json(f"{API_ROOT}/git/trees/{kiss_sha}")
        kiss_entries = {row.get("path"): row for row in kiss.get("tree") or []
                        if isinstance(row, dict)}
        manifests_sha = str((kiss_entries.get("manifests") or {}).get("sha") or "")
        if not manifests_sha:
            raise RuntimeError(f"the {self.branch} branch has no kiss/manifests/")
        revision = f"{models_sha[:16]}-{manifests_sha[:16]}".lower()
        return revision, models_sha, manifests_sha

    def _download(self, destination: Path) -> None:
        url = f"{ARCHIVE_ROOT}/{quote(self.branch, safe='')}"
        request = urllib.request.Request(
            url, headers={"User-Agent": "GeoForge-Desktop-KI-Updater"})
        with urllib.request.urlopen(request, timeout=90, context=tls.context()) as response:
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > MAX_ARCHIVE_BYTES:
                raise RuntimeError("the KI update archive is unexpectedly large")
            total = 0
            with destination.open("wb") as handle:
                while True:
                    block = response.read(1 << 20)
                    if not block:
                        break
                    total += len(block)
                    if total > MAX_ARCHIVE_BYTES:
                        raise RuntimeError("the KI update archive exceeded the safe size limit")
                    handle.write(block)

    def _extract(self, archive: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        files = 0
        total = 0
        symlinks: list[tuple[Path, str]] = []
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                parts = PurePosixPath(info.filename).parts
                if len(parts) < 3:
                    continue
                rel: PurePosixPath | None = None
                if parts[1] == "models":
                    rel = PurePosixPath(*parts[1:])
                elif len(parts) >= 4 and parts[1:3] == ("kiss", "manifests"):
                    rel = PurePosixPath(*parts[1:])
                if rel is None or info.is_dir():
                    continue
                if rel.is_absolute() or ".." in rel.parts:
                    raise RuntimeError("the KI update archive contains an unsafe path")
                files += 1
                total += info.file_size
                if files > MAX_ARCHIVE_FILES or total > MAX_EXTRACTED_BYTES:
                    raise RuntimeError("the extracted KI update exceeds the safe size limit")
                target = destination.joinpath(*rel.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    link = bundle.read(info).decode("utf-8", errors="strict")
                    symlinks.append((target, link))
                    continue
                with bundle.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1 << 20)
                if mode & 0o111:
                    target.chmod(target.stat().st_mode | 0o111)

        # Create links only after normal files are present.  A KI archive may
        # use relative links for shared helpers, but it may never escape the
        # validated snapshot or point at an author's private server path.
        root = destination.resolve()
        for target, link in symlinks:
            link_path = Path(link)
            if link_path.is_absolute():
                raise RuntimeError(f"KI archive contains an absolute symbolic link: {link}")
            resolved = (target.parent / link_path).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as error:
                raise RuntimeError(f"KI archive symbolic link escapes the snapshot: {link}") from error
            target.symlink_to(link)

    def _validate(self, root: Path) -> tuple[int, int, list[dict]]:
        catalog = Catalog(root / "models")
        if not len(catalog):
            raise RuntimeError("the downloaded snapshot contains no KIs")
        findings = []
        for ki in catalog:
            findings.extend(doctor.check_ki(ki))
        findings.extend(doctor.check_cross_model(catalog))
        blocked = [finding for finding in findings if finding.severity == doctor.BLOCK]
        if blocked:
            preview = "; ".join(
                f"{finding.ki}: {finding.detail}" for finding in blocked[:5])
            raise RuntimeError(
                f"downloaded KI snapshot failed {len(blocked)} blocking checks: {preview}")
        warnings = [finding for finding in findings if finding.severity == doctor.WARN]
        preview = [{"ki": finding.ki, "check": finding.check,
                    "detail": finding.detail} for finding in warnings[:20]]
        return len(catalog), len(warnings), preview

    def _run(self) -> None:
        checked_at = time.time()
        try:
            revision, models_sha, manifests_sha = self._remote_revision()
            state_path = update_root() / "state.json"
            state = _read_json(state_path)
            if (state.get("revision") == revision and active_library_root() is not None):
                self._set(
                    state="up_to_date", checked_at=checked_at,
                    active_revision=revision,
                    summary="The KI library is already up to date.",
                    added=[], updated=[], removed=[], changes=[],
                    unchanged_count=int(state.get("package_count") or 0),
                )
                return

            home = update_root()
            home.mkdir(parents=True, exist_ok=True)
            incoming = home / f".incoming-{uuid.uuid4().hex}"
            with tempfile.NamedTemporaryFile(
                    prefix="geoforge-ki-", suffix=".zip", delete=False) as temporary:
                archive = Path(temporary.name)
            try:
                self._download(archive)
                self._extract(archive, incoming)
                package_count, warning_count, warnings = self._validate(incoming)
                diff = _library_diff(self.current_library_root, incoming)
                snapshot = home / "snapshots" / revision
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                if snapshot.exists():
                    shutil.rmtree(incoming)
                else:
                    incoming.replace(snapshot)
                new_state = {
                    "active_snapshot": revision,
                    "revision": revision,
                    "models_tree": models_sha,
                    "manifests_tree": manifests_sha,
                    "package_count": package_count,
                    "activated_at": time.time(),
                    "branch": self.branch,
                }
                _atomic_json(state_path, new_state)
                self.activate(snapshot)
                self.current_library_root = snapshot
                changed_count = len(diff["added"]) + len(diff["updated"]) + len(diff["removed"])
                summary = (
                    f"KI library updated: {len(diff['added'])} added, "
                    f"{len(diff['updated'])} changed, {len(diff['removed'])} removed."
                    if changed_count else "The repository was checked; KI contents are unchanged.")
                self._set(
                    state="updated" if changed_count else "up_to_date",
                    checked_at=checked_at, active_revision=revision,
                    summary=summary, package_count=package_count,
                    warning_count=warning_count, warnings=warnings, **diff)
            finally:
                archive.unlink(missing_ok=True)
                if incoming.exists():
                    shutil.rmtree(incoming, ignore_errors=True)
        # This worker must always terminate in a report the window can show.
        # A malformed remote archive should never leave the UI saying
        # "checking" forever merely because its exact exception type was new.
        except Exception as error:
            self._set(
                state="error", checked_at=checked_at,
                summary=("Could not update the KI library. GeoForge kept the last "
                         "validated version."),
                error=str(error)[:2000],
            )
