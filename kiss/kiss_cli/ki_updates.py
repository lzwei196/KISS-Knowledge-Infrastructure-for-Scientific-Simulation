"""Validated, non-blocking updates for GeoForge's curated KI library.

The desktop app ships a known-good KI snapshot so it always starts offline.
On each desktop launch this module checks the platform branch of GeoForge's
public repository.  A changed library is downloaded into a versioned staging
directory, checked with the same deterministic package verifier used by the
Library import screen, and only then made active.  On Windows, a snapshot
that would remove the Windows installation notes or recipes from the current
library is reported as ``kept`` and not activated.

Updates never touch chat projects, installed scientific software, input data,
or user-imported KIs.  Old snapshots remain available while a running request
may still hold a path into them, so activation is a pointer switch rather than
an in-place rewrite.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import tomllib
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import quote, urlsplit

from . import doctor, firstrun, ki_platform_overlay, paths, reference_portability, settings, tls
from .catalog import KI, Catalog, installation_platform


REPOSITORY = "lzwei196/KISS---Knowledge-Infrastructure-for-Scientific-Simulation"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
ARCHIVE_ROOT = f"https://codeload.github.com/{REPOSITORY}/zip"
MAX_ARCHIVE_BYTES = 900 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 50_000
SNAPSHOT_MANIFEST = ".geoforge-library.json"


def _validation_policy() -> str:
    return getattr(doctor, "VALIDATION_POLICY_VERSION", "ki-doctor-v1")


class SnapshotValidationError(RuntimeError):
    """Full static findings accompany the short user-facing error preview."""

    def __init__(self, message: str, findings: list[dict], portability_files: list[dict]):
        super().__init__(message)
        self.findings = findings
        self.portability_files = portability_files


def _portability_files(catalog: Catalog, root: Path) -> list[dict]:
    rows = []
    for ki in catalog:
        classified = reference_portability.classify_reference_paths(ki)
        for relative in sorted(ki.portability.files):
            source = ki.root / relative
            classifications = {(item["line"], item["path"], item["role"]): item
                               for item in classified.get(Path(relative).as_posix(), [])}
            matches = [
                {"line": number, "path": matched, "role": role,
                 "classification": classifications.get((number, matched, role), {}).get("classification", "blocked"),
                 "reason": classifications.get((number, matched, role), {}).get("reason", "Outside recognized reference-case metadata or configurable runner defaults")}
                for number, line in enumerate(source.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
                for matched, role in paths.scan_text(line)
            ]
            rows.append({"ki": ki.name, "path": source.relative_to(root).as_posix(),
                         "sha256": _file_digest(source), "matches": matches})
    return rows


def _reference_case_summary(catalog: Catalog, findings: list) -> dict:
    counts = {"provenance": 0, "runtime_binding_metadata": 0, "configurable_default": 0}
    affected = set()
    for ki in catalog:
        for records in reference_portability.classify_reference_paths(ki).values():
            for record in records:
                category = record["classification"]
                if category in counts:
                    counts[category] += 1
                    affected.add(ki.name)
    return {"validation_policy": _validation_policy(), "native_verification": "not_performed",
            "configurable_path_count": counts["configurable_default"],
            "historical_path_count": counts["provenance"],
            "runtime_binding_metadata_count": counts["runtime_binding_metadata"],
            "affected_kis": sorted(affected),
            "warnings": [vars(item).copy() for item in findings
                         if item.check in {"reference-case-provenance", "reference-case-binding"}]}


def _revision_identity(trees: dict, overlay_id: str | None = None) -> str:
    # Keep the on-disk path no longer than the legacy two-tree identity. Full
    # component identities and overlay provenance remain in the manifest.
    value = {"trees": trees, "overlay_id": overlay_id,
             "policy": ki_platform_overlay.POLICY_VERSION,
             "validation_policy": _validation_policy()}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]


def data_ki_root(library_root: Path, fallback: Path | None = None) -> Path | None:
    root = Path(library_root) / "kiss" / "data_kis"
    return root if root.is_dir() else fallback


def shared_tools_root(library_root: Path, bundled_root: Path) -> Path:
    """Select runtime helpers without changing the app/harness source root."""
    library_root = Path(library_root)
    marker = library_root / SNAPSHOT_MANIFEST
    expects_marker = (bool(re.fullmatch(r"[0-9a-f]{16}(?:-[0-9a-f]{16}){3,}", library_root.name))
                      or (library_root.parent.name == "snapshots" and
                          bool(re.fullmatch(r"[0-9a-f]{32}", library_root.name))))
    if expects_marker and not marker.is_file():
        raise ValueError("The active KI snapshot's component manifest is missing")
    if marker.is_file() and not (_read_json(marker).get("trees") or {}).get("shared_tools"):
        raise ValueError("The active KI snapshot's shared helper identity is missing")
    candidate = library_root / "ki_tools_common"
    if (candidate / "ki_tools_common" / "__init__.py").is_file():
        return library_root
    if ((library_root / SNAPSHOT_MANIFEST).is_file()
            or re.fullmatch(r"[0-9a-f]{16}(?:-[0-9a-f]{16}){3,}", library_root.name)):
        raise ValueError("The active KI snapshot's pinned shared helper package is missing")
    # Older snapshots contained only models and manifests. Keep them usable,
    # with this fallback exposed explicitly in the component report.
    return Path(bundled_root)


def component_sources(library_root: Path, bundled_root: Path | None = None) -> dict:
    root = Path(library_root)
    meta = _read_json(root / SNAPSHOT_MANIFEST)
    if not meta:
        state = _read_json(update_root() / "state.json")
        if state.get("active_snapshot") == root.name:
            meta = {"source_commit": state.get("source_commit"), "trees": {
                "models": state.get("models_tree"), "manifests": state.get("manifests_tree")}}
    trees = meta.get("trees") or {}
    commit = meta.get("source_commit")
    out = {}
    for name, present in (
            ("models", True), ("manifests", True),
            ("shared_tools", (root / "ki_tools_common/ki_tools_common/__init__.py").is_file()),
            ("data_kis", (root / "kiss/data_kis").is_dir())):
        pinned = bool(meta and present)
        out[name] = {"state": "snapshot" if pinned else "bundled_fallback",
                     "tree_sha": trees.get(name) if pinned else None,
                     "source_commit": commit if pinned else None}
    return out


def _snapshot_content_hash(root: Path) -> str:
    files = _file_digests(root)
    files.pop(SNAPSHOT_MANIFEST, None)
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def _snapshot_valid(root: Path) -> bool:
    marker = root / SNAPSHOT_MANIFEST
    if not marker.exists():
        state = _read_json(update_root() / "state.json")
        recorded_new = (state.get("active_snapshot") == root.name
                        and bool((state.get("component_trees") or {}).get("shared_tools")))
        return bool(re.fullmatch(r"[0-9a-f]{16}-[0-9a-f]{16}", root.name)) and not recorded_new
    meta = _read_json(marker)
    trees = meta.get("trees")
    if meta.get("schema_version") != 1 or not isinstance(trees, dict):
        return False
    if not all(isinstance(trees.get(key), str) and len(trees[key]) == 40
               and all(c in "0123456789abcdef" for c in trees[key].lower())
               for key in ("models", "manifests", "shared_tools")):
        return False
    if not (root / "ki_tools_common/ki_tools_common/__init__.py").is_file() or not (root / "ki_tools_common/pyproject.toml").is_file():
        return False
    if trees.get("data_kis") and not (root / "kiss/data_kis").is_dir():
        return False
    if trees.get("data_kis") is not None and not re.fullmatch(r"[0-9a-f]{40}", str(trees["data_kis"])):
        return False
    try:
        return bool(meta.get("content_sha256")) and meta["content_sha256"] == _snapshot_content_hash(root)
    except OSError:
        return False


def branch_for_platform() -> str:
    override = os.environ.get("GEOFORGE_KI_UPDATE_BRANCH", "").strip()
    if override:
        return override
    # Application release branches contain platform packaging changes.  The
    # KI library itself has one canonical source, recorded in the release
    # manifest as main@ki_library.source_commit, so every desktop must fetch
    # KIs from main rather than replacing them with a platform-branch snapshot.
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


def active_library_root(reference: Path | None = None) -> Path | None:
    """Return the last activated snapshot, never a path supplied by JSON.

    With ``reference`` (the library bundled with this build), a Windows
    snapshot that lacks installation guidance the reference ships is not
    used: an older updater could activate one without the guard below.
    """
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
        if not _snapshot_valid(candidate):
            return None
        if (reference is not None and _guards_guidance() and
                _lost_guidance(Path(reference), candidate)):
            return None
        return candidate
    return None


PLATFORM_LABELS = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}


def _guards_guidance() -> bool:
    """Whether a snapshot may be refused for dropping install guidance.

    Windows only: its notes and recipes live on the Windows branch, which the
    canonical main library does not carry.  macOS and Linux keep activating
    main as before; their gap belongs to the mac side, not this branch.
    """
    return installation_platform() == "windows"


def _platform_guidance(library_root: Path) -> dict[str, set[str]]:
    """This platform's installation notes and recipe per KI.

    Resolved through ``catalog.KI`` so the check follows exactly the files the
    installer reads on this machine.  A recipe renamed between
    ``kiss.<platform>.yaml`` and ``kiss.<platform>.<arch>.yaml`` still counts.
    """
    platform = installation_platform()
    models = library_root / "models"
    out: dict[str, set[str]] = {}
    if not platform or not models.is_dir():
        return out
    for path in models.iterdir():
        if not (path / "SKILL.md").is_file():
            continue
        ki = KI(path.name, path)
        kinds = out.setdefault(path.name, set())
        if ki.installation_notes:
            kinds.add(f"docs/install.{platform}.md")
        manifest = ki.manifest
        if manifest is not None and manifest.name != "kiss.yaml":
            kinds.add(f"{platform} install recipe")
    return out


def _lost_guidance(before: Path, after: Path) -> list[str]:
    """Guidance ``before`` ships for a KI that ``after`` keeps but without it.

    File presence is compared rather than commit ancestry: it needs no
    network, and platform notes live on platform branches that the canonical
    library branch does not contain, so "newer" is not "complete".  A KI
    removed upstream takes its notes with it and is reported as removed.
    """
    old = _platform_guidance(before)
    new = _platform_guidance(after)
    return sorted(f"{name}: {kind}" for name, kinds in old.items()
                  if name in new for kind in kinds - new[name])


def _guidance_fingerprint(library_root: Path) -> str:
    rows = sorted(f"{name}: {kind}" for name, kinds in
                  _platform_guidance(library_root).items() for kind in kinds)
    return hashlib.sha256(
        "\n".join([installation_platform(), *rows]).encode("utf-8")).hexdigest()


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
    package = library_root / "models" / name
    if not package.is_dir():
        package = library_root / "kiss" / "data_kis" / name
    files = _file_digests(package)
    manifest = library_root / "kiss" / "manifests" / f"{name}.yaml"
    if manifest.is_file():
        files["@shared-manifest"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return files


def _library_diff(before: Path, after: Path) -> dict:
    def names(root):
        return {p.name for rel in ("models", "kiss/data_kis")
                if (root / rel).is_dir() for p in (root / rel).iterdir()
                if p.is_dir() and (p / "SKILL.md").is_file()}
    old_names, new_names = names(before), names(after)
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
        # This starts as a branch reference only for diagnostic visibility.
        # A real update check replaces it with the exact commit SHA before the
        # archive is downloaded, avoiding mutable-branch CDN cache mismatches.
        self._archive_ref = f"refs/heads/{self.branch}"
        self._source_commit = ""
        self._component_trees: dict[str, str | None] = {}
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        previous = _read_json(update_root() / "last-report.json")
        if previous.get("state") == "checking":
            previous = {
                **previous,
                "state": "idle",
                "summary": "The previous KI update check was interrupted. Choose Check to retry.",
            }
        self._report = {
            **(previous or {
            "state": "idle",
            "summary": "KI updates have not been checked yet.",
            }),
            "source_url": REPOSITORY_URL,
            "branch": self.branch,
            "components": component_sources(self.current_library_root),
            "windows_overlay": _read_json(self.current_library_root / SNAPSHOT_MANIFEST).get("windows_overlay"),
            "reference_cases": _read_json(self.current_library_root / SNAPSHOT_MANIFEST).get("reference_cases"),
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
        with self._open(request, timeout=30) as response:
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("GitHub returned an invalid repository response")
        return value

    def _proxy_url(self) -> str:
        proxy = settings.proxy_url_for(settings.GITHUB_PROXY_TARGET)
        if proxy and urlsplit(proxy).scheme not in {"http", "https"}:
            raise RuntimeError(
                "GitHub and KI updates require an HTTP/HTTPS proxy address. "
                "For Clash or another local proxy, select its HTTP or mixed port.")
        return proxy

    def _open(self, request: urllib.request.Request, *, timeout: int):
        """Open one updater request through the dedicated saved route."""
        proxy = self._proxy_url()
        handlers = [
            urllib.request.ProxyHandler(
                {"http": proxy, "https": proxy} if proxy else {}),
            urllib.request.HTTPSHandler(context=tls.context()),
        ]
        return urllib.request.build_opener(*handlers).open(request, timeout=timeout)

    def _remote_revision(self) -> tuple[str, str, str]:
        commit = self._request_json(
            f"{API_ROOT}/commits/{quote(self.branch, safe='')}")
        commit_sha = str(commit.get("sha") or "")
        tree_sha = str(((commit.get("commit") or {}).get("tree") or {}).get("sha") or "")
        if not commit_sha or not tree_sha:
            raise RuntimeError("GitHub returned an incomplete branch revision")
        self._source_commit = commit_sha
        self._archive_ref = commit_sha
        root = self._request_json(f"{API_ROOT}/git/trees/{tree_sha}")
        entries = {row.get("path"): row for row in root.get("tree") or []
                   if isinstance(row, dict)}
        models_sha = str((entries.get("models") or {}).get("sha") or "")
        kiss_sha = str((entries.get("kiss") or {}).get("sha") or "")
        common_sha = str((entries.get("ki_tools_common") or {}).get("sha") or "")
        if not models_sha or not kiss_sha:
            raise RuntimeError(
                f"the {self.branch} branch does not contain models/ and kiss/")
        if not common_sha:
            raise RuntimeError(f"the {self.branch} branch has no required ki_tools_common/ package")
        kiss = self._request_json(f"{API_ROOT}/git/trees/{kiss_sha}")
        kiss_entries = {row.get("path"): row for row in kiss.get("tree") or []
                        if isinstance(row, dict)}
        manifests_sha = str((kiss_entries.get("manifests") or {}).get("sha") or "")
        if not manifests_sha:
            raise RuntimeError(f"the {self.branch} branch has no kiss/manifests/")
        data_sha = str((kiss_entries.get("data_kis") or {}).get("sha") or "")
        self._component_trees = {"models": models_sha, "manifests": manifests_sha,
                                 "shared_tools": common_sha, "data_kis": data_sha or None}
        revision = _revision_identity(self._component_trees)
        return revision, models_sha, manifests_sha

    def _download(self, destination: Path) -> None:
        url = f"{ARCHIVE_ROOT}/{quote(self._archive_ref, safe='')}"
        request = urllib.request.Request(
            url, headers={"User-Agent": "GeoForge-Desktop-KI-Updater",
                          "Cache-Control": "no-cache"})
        with self._open(request, timeout=90) as response:
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

    def _obtain_archive(self, destination: Path) -> dict:
        """Reuse exact downloaded bytes, never a cached validation verdict."""
        commit = self._source_commit
        cache = update_root() / "archives" / f"{commit}.zip"
        meta_path = cache.with_suffix(".json")
        pinned = bool(re.fullmatch(r"[0-9a-f]{40}", commit))
        meta = _read_json(meta_path) if pinned else {}
        if (meta.get("source_commit") == commit and cache.is_file()
                and 0 < cache.stat().st_size <= MAX_ARCHIVE_BYTES
                and meta.get("size_bytes") == cache.stat().st_size
                and meta.get("sha256") == _file_digest(cache)):
            shutil.copyfile(cache, destination)
            return {**meta, "cache_reused": True}
        self._download(destination)
        size = destination.stat().st_size
        if not 0 < size <= MAX_ARCHIVE_BYTES:
            raise RuntimeError("the KI update archive has an invalid size")
        return {"source_commit": commit, "sha256": _file_digest(destination),
                "size_bytes": size, "cache_reused": False}

    def _cache_archive(self, archive: Path, meta: dict) -> None:
        # Called only after safe extraction succeeds. This remains unvalidated
        # source material; every retry repeats extraction, overlay and doctor.
        if not re.fullmatch(r"[0-9a-f]{40}", self._source_commit) or meta.get("cache_reused"):
            return
        cache = update_root() / "archives" / f"{self._source_commit}.zip"
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_name(f".{uuid.uuid4().hex}.zip")
        try:
            shutil.copyfile(archive, temporary)
            temporary.replace(cache)
            _atomic_json(cache.with_suffix(".json"), {**meta, "validation": "not_reusable"})
        finally:
            temporary.unlink(missing_ok=True)

    def _quarantine(self, incoming: Path, error: Exception, *, stage: str,
                    archive_meta: dict, source_hash: str | None, overlay: dict | None) -> dict:
        """Preserve rejected bytes separately from every activatable snapshot."""
        target = update_root() / "quarantine" / uuid.uuid4().hex[:12]
        target.parent.mkdir(parents=True, exist_ok=True)
        incoming.replace(target)
        report = {
            "schema_version": 1, "activated": False, "stage": stage,
            "validation_policy": _validation_policy(),
            "source_commit": self._source_commit, "component_trees": self._component_trees,
            "archive_sha256": archive_meta.get("sha256"),
            "archive_cache_reused": archive_meta.get("cache_reused", False),
            "source_content_sha256": source_hash,
            "candidate_content_sha256": _snapshot_content_hash(target),
            "quarantine_path": str(target), "report_path": str(target / "validation-report.json"),
            "windows_overlay": overlay, "error": str(error),
            "reference_cases": getattr(self, "_reference_case_summary", None),
            "findings": getattr(error, "findings", []),
            "portability_scanner": "catalog.Portability.scan / paths.scan_text",
            "portability_files": getattr(error, "portability_files", []),
        }
        _atomic_json(target / "validation-report.json", report)
        return report

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
                if parts[1] in {"models", "ki_tools_common"}:
                    rel = PurePosixPath(*parts[1:])
                elif len(parts) >= 4 and parts[1] == "kiss" and parts[2] in {"manifests", "data_kis"}:
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
            # Zip link payloads use POSIX syntax even when extraction runs on
            # Windows. pathlib.Path('/Users/...') is not absolute under
            # WindowsPath, so check the archive spelling as well.
            if link_path.is_absolute() or PurePosixPath(link).is_absolute():
                raise RuntimeError(f"KI archive contains an absolute symbolic link: {link}")
            resolved = (target.parent / link_path).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as error:
                raise RuntimeError(f"KI archive symbolic link escapes the snapshot: {link}") from error
            target.symlink_to(link)

    def _validate(self, root: Path) -> tuple[int, int, list[dict]]:
        self._reference_case_summary = None
        common = root / "ki_tools_common"
        if not (common / "ki_tools_common/__init__.py").is_file() or not (common / "pyproject.toml").is_file():
            raise RuntimeError("downloaded KI snapshot is missing the required ki_tools_common package")
        with (common / "pyproject.toml").open("rb") as handle:
            tomllib.load(handle)
        for source in common.rglob("*.py"):
            ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
        catalog = Catalog(root / "models", data_dir=data_ki_root(root))
        if not len(catalog):
            raise RuntimeError("the downloaded snapshot contains no KIs")
        findings = []
        for ki in catalog:
            findings.extend(doctor.check_ki(ki))
        findings.extend(doctor.check_cross_model(catalog))
        self._reference_case_summary = _reference_case_summary(catalog, findings)
        blocked = [finding for finding in findings if finding.severity == doctor.BLOCK]
        if blocked:
            preview = "; ".join(
                f"{finding.ki}: {finding.detail}" for finding in blocked[:5])
            raise SnapshotValidationError(
                f"downloaded KI snapshot failed {len(blocked)} blocking checks: {preview}",
                [vars(finding).copy() for finding in findings], _portability_files(catalog, root))
        warnings = [finding for finding in findings if finding.severity == doctor.WARN]
        # Binding caveats must not disappear behind unrelated package warnings.
        ordered = sorted(warnings, key=lambda finding: finding.check != "reference-case-binding")
        preview = [{"ki": finding.ki, "check": finding.check,
                    "detail": finding.detail} for finding in ordered[:20]]
        return len(catalog), len(warnings), preview

    def _refusal(self, revision: str, reference: str, lost: list[str]) -> dict:
        platform = installation_platform()
        label = PLATFORM_LABELS.get(platform, platform)
        examples = ", ".join(lost[:5]) + (", …" if len(lost) > 5 else "")
        return {
            # Not "error": nothing failed, and the window must not blame the
            # network or validation for a deliberate decision.
            "state": "kept",
            "summary": (f"GeoForge kept the current KI library because the "
                        f"repository version would remove {label} installation "
                        "guidance."),
            "error": (f"The {self.branch} snapshot lacks {len(lost)} {label} "
                      "installation notes or recipes that the current library "
                      f"ships ({examples}), so it was not activated. Updates "
                      "resume once the repository carries them."),
            "refused": {"revision": revision, "reference": reference, "lost": lost,
                        "policy": ki_platform_overlay.POLICY_VERSION},
            # Nothing changed; do not show an earlier update's lists under it.
            "added": [], "updated": [], "removed": [], "changes": [],
            "warning_count": 0,
        }

    def _run(self) -> None:
        checked_at = time.time()
        validation_failure = None
        self._reference_case_summary = None
        try:
            revision, models_sha, manifests_sha = self._remote_revision()
            upstream_revision = revision
            route = self._proxy_url() or "direct"
            state_path = update_root() / "state.json"
            state = _read_json(state_path)
            active = active_library_root(self.current_library_root)
            if (state.get("validation_policy") == _validation_policy() and
                    (state.get("revision") == revision or
                 (state.get("upstream_revision") == revision and
                  state.get("overlay_policy") == ki_platform_overlay.POLICY_VERSION)) and
                    active is not None):
                if active != self.current_library_root:
                    self.activate(active)
                    self.current_library_root = active
                active_meta = _read_json(active / SNAPSHOT_MANIFEST)
                self._set(
                    state="up_to_date", checked_at=checked_at,
                    active_revision=state.get("revision") or revision,
                    summary="The KI library is already up to date.",
                    network_route=route, source_commit=self._source_commit,
                    added=[], updated=[], removed=[], changes=[],
                    unchanged_count=int(state.get("package_count") or 0),
                    warning_count=active_meta.get("warning_count", 0),
                    warnings=active_meta.get("warnings", []),
                    error=None, refused=None, validation_failure=None,
                    components=component_sources(self.current_library_root),
                    windows_overlay=active_meta.get("windows_overlay"),
                    reference_cases=active_meta.get("reference_cases"),
                )
                return
            guard = _guards_guidance()
            reference = ""
            if guard:
                # The same revision checked against the same library would be
                # refused again; do not download ~90 MB on every launch to see it.
                reference = _guidance_fingerprint(self.current_library_root)
                refused = self.status().get("refused") or {}
                if (refused.get("revision") == revision and
                        refused.get("reference") == reference and
                        refused.get("policy") == ki_platform_overlay.POLICY_VERSION):
                    self._set(checked_at=checked_at, network_route=route,
                              source_commit=self._source_commit,
                              **self._refusal(revision, reference,
                                              list(refused.get("lost") or [])))
                    return

            home = update_root()
            home.mkdir(parents=True, exist_ok=True)
            incoming = home / f".incoming-{uuid.uuid4().hex}"
            with tempfile.NamedTemporaryFile(
                    prefix="geoforge-ki-", suffix=".zip", delete=False) as temporary:
                archive = Path(temporary.name)
            stage, archive_meta, source_hash, overlay = "download", {}, None, None
            try:
                archive_meta = self._obtain_archive(archive)
                stage = "extraction"
                self._extract(archive, incoming)
                self._cache_archive(archive, archive_meta)
                source_hash = _snapshot_content_hash(incoming)
                stage = "windows_overlay"
                overlay = ki_platform_overlay.apply_windows_overlay(
                    self.current_library_root, incoming,
                    platform=installation_platform(), upstream_commit=self._source_commit,
                    source_identity=self.current_library_root.name)
                if overlay.get("files"):
                    revision = _revision_identity(self._component_trees, overlay["overlay_id"])
                # Windows install notes and recipes live only on the Windows
                # branch; a main snapshot without them would silently take
                # this machine's installation guidance away.
                lost = (_lost_guidance(self.current_library_root, incoming)
                        if guard else [])
                if lost:
                    failure = SnapshotValidationError("Required platform installation guidance is missing",
                        [{"ki": row.split(":", 1)[0], "severity": doctor.BLOCK,
                          "check": "installation-guidance", "detail": row, "count": 1} for row in lost], [])
                    validation_failure = self._quarantine(incoming, failure, stage="platform_guard",
                        archive_meta=archive_meta, source_hash=source_hash, overlay=overlay)
                    self._set(checked_at=checked_at, network_route=route,
                              source_commit=self._source_commit,
                              validation_failure=validation_failure,
                              **self._refusal(revision, reference, lost))
                    return
                stage = "package_validation"
                package_count, warning_count, warnings = self._validate(incoming)
                diff = _library_diff(self.current_library_root, incoming)
                helper_changed = (_file_digests(self.current_library_root / "ki_tools_common") !=
                                  _file_digests(incoming / "ki_tools_common"))
                _atomic_json(incoming / SNAPSHOT_MANIFEST, {
                    "schema_version": 1, "revision": revision,
                    "source_commit": self._source_commit, "trees": self._component_trees,
                    "upstream_revision": upstream_revision,
                    "validation_policy": _validation_policy(),
                    "reference_cases": getattr(self, "_reference_case_summary", None),
                    "warning_count": warning_count, "warnings": warnings,
                    "windows_overlay": overlay if overlay.get("files") else None,
                    "content_sha256": _snapshot_content_hash(incoming)})
                snapshot = home / "snapshots" / revision
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                stage = "snapshot_activation"
                if snapshot.exists():
                    cached = _read_json(snapshot / SNAPSHOT_MANIFEST)
                    if (not _snapshot_valid(snapshot) or cached.get("revision") != revision
                            or cached.get("validation_policy") != _validation_policy()
                            or cached.get("trees") != self._component_trees):
                        raise RuntimeError("The cached KI snapshot was changed or is incomplete; preserved without activation")
                    shutil.rmtree(incoming)
                else:
                    incoming.replace(snapshot)
                new_state = {
                    "active_snapshot": revision,
                    "revision": revision,
                    "upstream_revision": upstream_revision,
                    "overlay_policy": ki_platform_overlay.POLICY_VERSION,
                    "models_tree": models_sha,
                    "manifests_tree": manifests_sha,
                    "package_count": package_count,
                    "activated_at": time.time(),
                    "branch": self.branch,
                    "source_commit": self._source_commit,
                    "component_trees": self._component_trees,
                    "validation_policy": _validation_policy(),
                }
                _atomic_json(state_path, new_state)
                self.activate(snapshot)
                self.current_library_root = snapshot
                changed_count = len(diff["added"]) + len(diff["updated"]) + len(diff["removed"]) + int(helper_changed)
                summary = (
                    f"KI library updated: {len(diff['added'])} added, "
                    f"{len(diff['updated'])} changed, {len(diff['removed'])} removed."
                    + (" Shared helpers updated." if helper_changed else "")
                    if changed_count else "The repository was checked; KI contents are unchanged.")
                self._set(
                    state="updated" if changed_count else "up_to_date",
                    checked_at=checked_at, active_revision=revision,
                    network_route=route, source_commit=self._source_commit,
                    summary=summary, package_count=package_count,
                    warning_count=warning_count, warnings=warnings,
                    error=None, refused=None, validation_failure=None,
                    archive_sha256=archive_meta.get("sha256"),
                    archive_cache_reused=archive_meta.get("cache_reused", False),
                    components=component_sources(snapshot),
                    reference_cases=getattr(self, "_reference_case_summary", None),
                    windows_overlay=overlay if overlay.get("files") else None, **diff)
            except Exception as error:
                if incoming.exists():
                    try:
                        validation_failure = self._quarantine(incoming, error, stage=stage,
                            archive_meta=archive_meta, source_hash=source_hash, overlay=overlay)
                    except Exception as evidence_error:
                        # Never discard a candidate when retaining evidence failed.
                        validation_failure = {"activated": False, "stage": stage,
                            "source_commit": self._source_commit, "quarantine_path": str(incoming),
                            "error": str(error), "evidence_error": str(evidence_error)}
                raise
            finally:
                archive.unlink(missing_ok=True)
                if incoming.exists() and validation_failure is None:
                    shutil.rmtree(incoming, ignore_errors=True)
        # This worker must always terminate in a report the window can show.
        # A malformed remote archive should never leave the UI saying
        # "checking" forever merely because its exact exception type was new.
        except Exception as error:
            self._set(
                state="error", checked_at=checked_at,
                summary=("Could not update the KI library. GeoForge kept the last "
                         "validated version."),
                network_route=(settings.proxy_url_for(
                    settings.GITHUB_PROXY_TARGET) or "direct"),
                error=str(error)[:2000],
                source_commit=self._source_commit,
                validation_failure=validation_failure,
                added=[], updated=[], removed=[], changes=[], warning_count=0,
            )
