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

from . import doctor, firstrun, ki_platform_overlay, ki_verification, paths, published_acceptance, reference_portability, settings, tls
from .catalog import KI, Catalog, installation_platform


REPOSITORY = "lzwei196/KISS---Knowledge-Infrastructure-for-Scientific-Simulation"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
ARCHIVE_ROOT = f"https://codeload.github.com/{REPOSITORY}/zip"
MAX_ARCHIVE_BYTES = 900 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 50_000
MAX_JSON_BYTES = 16 * 1024 * 1024
SNAPSHOT_MANIFEST = ".geoforge-library.json"


class _HTTPSOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Official update identities must remain authenticated across redirects."""

    def redirect_request(self, request, response, code, message, headers, new_url):
        if urlsplit(new_url).scheme.lower() != "https":
            raise RuntimeError("KI updater refused a redirect without HTTPS; the current library was kept")
        return super().redirect_request(request, response, code, message, headers, new_url)


def _validation_policy() -> str:
    return (getattr(doctor, "VALIDATION_POLICY_VERSION", "ki-doctor-v1")
            + ":" + ki_verification.GATE_POLICY + ":" + published_acceptance.POLICY
            + ":" + published_acceptance.profile_digest())


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
        return False
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
        if not meta.get("content_sha256") or meta["content_sha256"] != _snapshot_content_hash(root):
            return False
        # Unsigned historical snapshots must be re-fetched under the current
        # contract. Removing fields cannot downgrade a signed snapshot to an
        # older acceptance mode; the bundled library remains the fallback.
        published_acceptance.require_snapshot(root, meta)
        return True
    except (OSError, ValueError, TypeError):
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


def _selection_bytes(path: Path) -> bytes | None:
    """Missing selection is distinct from an unreadable selection."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _selection_value(value: bytes | None) -> dict:
    try:
        decoded = json.loads(value) if value is not None else {}
    except (ValueError, UnicodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


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


def _platform_guidance(library_root: Path, *, source_models: list[str] | None = None) -> dict[str, set[str]]:
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
        if not (path.name in source_models if source_models is not None else (path / "SKILL.md").is_file()):
            continue
        ki = KI(path.name, path)
        kinds = out.setdefault(path.name, set())
        if ki.installation_notes:
            kinds.add(f"docs/install.{platform}.md")
        manifest = ki.manifest
        if manifest is not None and manifest.name != "kiss.yaml":
            kinds.add(f"{platform} install recipe")
    return out


def _lost_guidance(before: Path, after: Path, *, source_models: list[str] | None = None) -> list[str]:
    """Guidance ``before`` ships for a KI that ``after`` keeps but without it.

    File presence is compared rather than commit ancestry: it needs no
    network, and platform notes live on platform branches that the canonical
    library branch does not contain, so "newer" is not "complete".  A KI
    removed upstream takes its notes with it and is reported as removed.
    """
    old = _platform_guidance(before, source_models=source_models)
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
        self._published_origin = None
        self._activation = None
        self._activation_unresolved = False
        self._overlay_source_root = self.current_library_root
        self._overlay_source_files = self._overlay_inputs(self.current_library_root)
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        previous = _read_json(update_root() / "last-report.json")
        prior_activation = previous.get("activation")
        if previous.get("state") == "checking":
            previous = {
                **previous,
                "state": "idle",
                "progress": None,
                "summary": "The previous KI update check was interrupted. Choose Check to retry.",
            }
        elif (prior_activation or {}).get("outcome") == "uncertain":
            previous = {**previous, "state": "idle", "progress": None, "error": None,
                "summary": "GeoForge restarted with the current library. Check for KI updates again."}
        current_meta = _read_json(self.current_library_root / SNAPSHOT_MANIFEST)
        self._report = {
            **(previous or {
            "state": "idle",
            "summary": "KI updates have not been checked yet.",
            }),
            "source_url": REPOSITORY_URL,
            "branch": self.branch,
            # A previous session's callback outcome cannot describe the new
            # process. Its constructor root is the actual loaded catalogue.
            "activation": None, "previous_activation": prior_activation,
            "active_revision": current_meta.get("revision"),
            "components": component_sources(self.current_library_root),
            "windows_overlay": current_meta.get("windows_overlay"),
            "reference_cases": current_meta.get("reference_cases"),
        }

    def status(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._report))

    @staticmethod
    def _overlay_inputs(root: Path) -> dict:
        """Capture only inputs used by the existing platform overlay."""
        candidates = set((root / "kiss/manifests").glob("*.yaml"))
        candidates.update((root / "models").glob("*/kiss*.yaml"))
        candidates.update((root / "models").glob("*/docs/install.windows.md"))
        return {p.relative_to(root).as_posix(): hashlib.sha256(
                    ki_platform_overlay._read(root, p)).hexdigest()
                for p in sorted(candidates) if p.is_file()}

    def _check_overlay_source(self, overlay: dict) -> None:
        """Retained guidance is existing host content, never upstream authorship."""
        if not overlay.get("files"):
            return
        from . import ki_guard
        from . import published_kdt
        import sys
        root = self.current_library_root
        current = self._overlay_inputs(root)
        if root != self._overlay_source_root:
            if not _snapshot_valid(root):
                raise ValueError("Retained guidance source has no intact snapshot")
            self._overlay_source_root, self._overlay_source_files = root, current
        if current != self._overlay_source_files:
            raise ValueError("Platform guidance changed during this update attempt")
        missing_ki_baseline = False
        for item in overlay["files"]:
            for key in ("source", "base_generic", "excluded_platform_duplicate"):
                record = item.get(key)
                if record and current.get(record["path"]) != record["sha256"]:
                    raise ValueError("Platform overlay source differs from its captured host baseline")
            relative = Path(item["source"]["path"])
            if relative.parts[:1] == ("models",):
                source_ki = root / "models" / relative.parts[1]
                if ki_guard.is_managed(source_ki):
                    # A changed registered KI must not escape its guard through
                    # the narrower official-guidance authentication route.
                    ki_guard.require_intact(source_ki)
                else:
                    missing_ki_baseline = True
        if missing_ki_baseline:
            from . import platform_guidance_provenance
            object_root = None
            if not platform_guidance_provenance.has_git_object_store(root):
                # An extracted snapshot has no .git directory. The application
                # checkout can supply hash-checked objects, never trust in its
                # working files or permission to enroll the selected source KI.
                checkout = Path(__file__).resolve().parents[2]
                if platform_guidance_provenance.has_git_object_store(checkout):
                    object_root = checkout
            evidence = platform_guidance_provenance.authenticate(
                root, overlay, request_json=self._request_json, object_root=object_root)
            if self._overlay_inputs(root) != current:
                raise ValueError("Platform guidance changed during authentication")
            overlay["host_source"] = {"root": str(root),
                "scope": platform_guidance_provenance.SCOPE,
                "evidence": evidence}
            return
        # Generic recipes can live outside an enrolled KI. Keep an explicit
        # signed first-use inventory for this app build, rather than silently
        # recapturing changed generic inputs on each retry or restart.
        authority = published_acceptance._authority(root)
        identity = {"root": str(root), "app_source": published_kdt._module_identity(sys.modules[__name__])}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
        baseline_path = authority / "guidance" / f"{key}.json"
        baseline = _read_json(baseline_path)
        payload = {"scope": "existing_host_guidance_baseline", **identity, "files": current}
        if baseline_path.exists():
            if (not published_acceptance._authentic(root, baseline)
                    or any(baseline.get(k) != v for k, v in payload.items())):
                raise ValueError("Platform guidance differs from its signed host baseline")
        else:
            baseline = published_acceptance._sign(root, payload)
            _atomic_json(baseline_path, baseline)
        overlay["host_source"] = {"root": str(root), "scope": "existing_host_guidance",
            "inputs_sha256": hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest(),
            "baseline": baseline}

    def _set(self, **values) -> None:
        with self._lock:
            if "state" in values and values["state"] != "checking":
                values.setdefault("progress", None)
            self._report = {**self._report, **values,
                            "source_url": REPOSITORY_URL,
                            "branch": self.branch}
            _atomic_json(update_root() / "last-report.json", self._report)

    def _begin_attempt(self) -> None:
        """Separate this attempt's progress/findings from the previous result."""
        with self._lock:
            self._activation = None
            self._ki_verification = []
            # Refusal caching still avoids downloading the same known-incomplete
            # source. Its old error is not a finding from the new attempt.
            self._previous_refusal = self._report.get("refused") or {}
            self._set(state="checking", started_at=time.time(), checked_at=None,
                summary="Checking the main KI revision…", source_commit=None,
                network_route=None, error=None, refused=None, validation_failure=None,
                activation=None, report_persistence_error=None,
                ki_verification=[], added=[], updated=[], removed=[], changes=[],
                warning_count=0, warnings=[], package_count=None, unchanged_count=0,
                archive_sha256=None, archive_cache_reused=None,
                progress={"stage": "check_main", "checked": None, "total": None, "current": None})

    def _progress(self, stage: str, *, checked: int | None = None,
                  total: int | None = None, current: str | None = None) -> None:
        """Report completed checks, never elapsed-time estimates or pass counts."""
        labels = {"check_main": "Checking the main KI revision…",
                  "raw_windows": "Authenticating Windows installation support…",
                  "download": "Obtaining the KI archive…",
                  "extract": "Extracting the KI archive…",
                  "compose": "Preparing platform installation guidance…",
                  "validate": "Checking KI packages…",
                  "activate": "Finalizing and activating the checked library…"}
        if stage not in labels:
            raise ValueError("Unknown KI update progress stage")
        if ((checked is None) != (total is None) or
                (checked is not None and (type(checked) is not int or type(total) is not int
                                         or not 0 <= checked <= total))):
            raise ValueError("Invalid KI update check counts")
        summary = labels[stage]
        if checked is not None:
            summary += f" {checked}/{total} checks finished."
        if current:
            summary += f" Current package: {current}."
        self._set(progress={"stage": stage, "checked": checked, "total": total,
                            "current": current}, summary=summary)

    def _windows_guidance(self) -> dict | None:
        """Resolve raw platform inputs independently of the active KI snapshot."""
        if installation_platform() != "windows":
            return None
        from . import raw_windows_guidance
        return raw_windows_guidance.prepare(None, request_json=self._request_json,
            request_bytes=self._request_bytes, object_root=Path(__file__).resolve().parents[2])

    def _check_retained_guidance_integrity(self) -> None:
        """New official inputs cannot conceal an altered registered active KI."""
        from . import ki_guard
        root = self.current_library_root
        current = self._overlay_inputs(root)
        if root != self._overlay_source_root:
            if not _snapshot_valid(root):
                raise ValueError("Retained guidance source has no intact snapshot")
            self._overlay_source_root, self._overlay_source_files = root, current
        if current != self._overlay_source_files:
            raise ValueError("Platform guidance changed during this update attempt")
        # A registered KI remains guarded even when its guidance is stored in
        # kiss/manifests, or a local guidance file was deleted before this
        # manager was constructed. Metadata discovery is not KI membership.
        current_catalog = Catalog(root / "models", data_dir=data_ki_root(root))
        for ki in current_catalog:
            if ki_guard.is_managed(ki.root):
                ki_guard.require_intact(ki.root)

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            if self._activation_unresolved:
                self._activation_error_report(
                    RuntimeError("Restart GeoForge before another KI update; library activation is uncertain"),
                    checked_at=time.time(), validation_failure=None)
                return False
            try:
                self._begin_attempt()
            except Exception as error:
                self._activation_error_report(error, checked_at=time.time(), validation_failure=None)
                return False
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="geoforge-ki-update")
            self._thread.start()
            return True

    def _activate_candidate(self, candidate: Path, *, state_path: Path,
                            expected_state: bytes | None, new_state: dict | None = None) -> None:
        """Switch this session before saving its selection, with explicit recovery.

        Compare the exact selection captured before validation, both before and
        after the callback. These checks detect observed concurrent changes;
        they are not a cross-process compare-and-swap. No failure path writes
        an old pointer over another process's selection.
        """
        previous = self.current_library_root
        result = {"outcome": "unchanged", "previous_root": str(previous),
                  "candidate_root": str(candidate), "current_root": str(previous),
                  "saved_selection": "unchanged", "restart_required": False}
        self._activation = result
        callback_started = write_started = False
        try:
            if _selection_bytes(state_path) != expected_state:
                result["saved_selection"] = "foreign"
                raise RuntimeError("The saved library selection changed during this update; it was not overwritten")
            callback_started = candidate != previous or new_state is not None
            if callback_started:
                self.activate(candidate)
            if _selection_bytes(state_path) != expected_state:
                result["saved_selection"] = "foreign"
                raise RuntimeError("The saved library selection changed during activation; it was not overwritten")
            if new_state is not None:
                write_started = True
                _atomic_json(state_path, new_state)
                if _selection_value(_selection_bytes(state_path)) != new_state:
                    result["saved_selection"] = "foreign"
                    raise RuntimeError("The saved library selection changed while activation was being saved")
        except Exception as error:
            result["error"] = str(error)[:2000]
            # A writer may report failure after the atomic replacement already
            # committed. Reconcile against the actual pointer before rollback.
            try:
                observed = _selection_bytes(state_path)
            except OSError as read_error:
                result.update(outcome="uncertain", current_root=None,
                    saved_selection="unknown", restart_required=True,
                    state_error=str(read_error)[:2000])
                self._activation_unresolved = True
                raise
            if write_started and _selection_value(observed) == new_state:
                self.current_library_root = candidate
                result.update(outcome="committed", current_root=str(candidate),
                              saved_selection="candidate")
                raise
            if observed != expected_state:
                result["saved_selection"] = "foreign"
            if callback_started:
                try:
                    self.activate(previous)
                except Exception as rollback_error:
                    result.update(outcome="uncertain", current_root=None,
                        restart_required=True, rollback_error=str(rollback_error)[:2000])
                    self._activation_unresolved = True
                else:
                    self.current_library_root = previous
                    result.update(outcome="restored", current_root=str(previous))
            raise
        self.current_library_root = candidate
        result.update(outcome="committed", current_root=str(candidate), saved_selection="candidate")

    def _activation_bindings(self) -> dict:
        """Only label bindings proven for this session, never a prior report."""
        empty = {"active_revision": None, "components": {},
                 "windows_overlay": None, "reference_cases": None}
        if not self._activation or self._activation.get("outcome") == "uncertain":
            return empty
        root = Path(self._activation["current_root"])
        try:
            meta = _read_json(root / SNAPSHOT_MANIFEST)
            return {"active_revision": meta.get("revision"),
                    "components": component_sources(root),
                    "windows_overlay": meta.get("windows_overlay"),
                    "reference_cases": meta.get("reference_cases")}
        except Exception as error:
            # Activation can be committed even if ancillary display data fails.
            self._activation["binding_report_error"] = str(error)[:2000]
            return empty

    def _activation_error_report(self, error: Exception, *, checked_at: float,
                                 validation_failure: dict | None) -> None:
        result = self._activation
        outcome = (result or {}).get("outcome")
        summary = {
            "committed": "The new KI library is active, but finishing the update reported an error.",
            "restored": "KI activation failed. The previous library was restored for this session.",
            "uncertain": "KI library activation is uncertain. Restart GeoForge before continuing.",
        }.get(outcome, "Could not update the KI library. GeoForge kept the current library.")
        if result and result.get("saved_selection") == "foreign":
            summary += " The saved selection changed separately and was not overwritten."
        try:
            route = settings.proxy_url_for(settings.GITHUB_PROXY_TARGET) or "direct"
        except Exception:
            route = None  # Ancillary settings cannot conceal the activation outcome.
        values = dict(state="error", checked_at=checked_at, summary=summary,
            network_route=route,
            error=str(error)[:2000], source_commit=self.status().get("source_commit"),
            validation_failure=validation_failure, ki_verification=self._ki_verification,
            activation=result, added=[], updated=[], removed=[], changes=[], warning_count=0)
        if result:
            values.update(self._activation_bindings())
        try:
            self._set(**values)
        except Exception as report_error:
            # Disk full/permissions must not leave a live worker saying checking
            # or replace a committed outcome with a false kept-library claim.
            with self._lock:
                self._report = {**self._report, **values, "progress": None,
                    "report_persistence_error": str(report_error)[:2000],
                    "source_url": REPOSITORY_URL, "branch": self.branch}

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
            body = response.read(MAX_JSON_BYTES + 1)
            if len(body) > MAX_JSON_BYTES:
                raise RuntimeError("GitHub JSON response exceeded the safe size limit")
            value = json.loads(body.decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("GitHub returned an invalid repository response")
        return value

    def _request_bytes(self, url: str, *, max_bytes: int) -> bytes:
        """Bounded metadata download using the same saved verified HTTPS route."""
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com":
            raise ValueError("Windows guidance requires the official HTTPS raw-content host")
        if not 0 < max_bytes <= ki_platform_overlay.MAX_GUIDANCE_BYTES:
            raise ValueError("Invalid Windows guidance download limit")
        request = urllib.request.Request(url, headers={"User-Agent": "GeoForge-Desktop-KI-Updater"})
        with self._open(request, timeout=30) as response:
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > max_bytes:
                raise RuntimeError("Windows guidance file exceeds its byte limit")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise RuntimeError("Windows guidance file exceeds its byte limit")
            return body

    def _proxy_url(self) -> str:
        proxy = settings.proxy_url_for(settings.GITHUB_PROXY_TARGET)
        if proxy and urlsplit(proxy).scheme not in {"http", "https"}:
            raise RuntimeError(
                "GitHub and KI updates require an HTTP/HTTPS proxy address. "
                "For Clash or another local proxy, select its HTTP or mixed port.")
        return proxy

    def _open(self, request: urllib.request.Request, *, timeout: int):
        """Open one updater request through the dedicated saved route."""
        if urlsplit(request.full_url).scheme.lower() != "https":
            raise ValueError("KI updater requests require HTTPS")
        proxy = self._proxy_url()
        handlers = [
            urllib.request.ProxyHandler(
                {"http": proxy, "https": proxy} if proxy else {}),
            urllib.request.HTTPSHandler(context=tls.context()),
            _HTTPSOnlyRedirectHandler(),
        ]
        return urllib.request.build_opener(*handlers).open(request, timeout=timeout)

    def _remote_revision(self) -> tuple[str, str, str]:
        # A failed retry must not retain the last attempt's pinned identity.
        self._source_commit = ""
        self._component_trees = {}
        self._archive_ref = f"refs/heads/{self.branch}"
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
            "ki_verification": getattr(self, "_ki_verification", []),
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
            # Windows stores the literal target spelling: a POSIX '../stage'
            # target creates a link that cannot be traversed even when the
            # directory exists. Use the already-validated native Path spelling
            # while preserving a relative link and its actual target type.
            target.symlink_to(link_path, target_is_directory=resolved.is_dir())

    def _validate(self, root: Path) -> tuple[int, int, list[dict]]:
        self._reference_case_summary = None
        self._ki_verification = []
        before = _snapshot_content_hash(root)
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
        self._progress("validate", checked=0, total=len(catalog), current=None)
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
        # Distribution and authoring are distinct evidence contracts. Official
        # downloads carry metadata-only papers; edits/imports retain the full
        # authoring gate. Every incoming package receives current publication
        # evidence tied to this origin. An intact existing baseline proves only
        # preservation of those old bytes, never that today's gate accepts them.
        current = Catalog(self.current_library_root / "models",
                          data_dir=data_ki_root(self.current_library_root))
        from . import ki_guard
        package_failures = []
        for ki in catalog:
            self._progress("validate", checked=len(self._ki_verification),
                           total=len(catalog), current=ki.name)
            previous = current.packages.get(ki.name)
            report = None
            try:
                # A differing upstream package must not hide a locally changed
                # registered KI by falling through to fresh verification.
                if previous and ki_guard.is_managed(previous.root):
                    ki_guard.require_intact(previous.root)
                if self._published_origin is None:
                    raise ValueError("Official update origin is missing")
                report = published_acceptance.verify_candidate(ki.root, name=ki.name,
                    kind=ki_verification.detect_kind(ki.root), origin=self._published_origin)
                if not report.get("ok"):
                    details = report.get("failures") or [
                        f["detail"] for f in (report.get("desktop") or {}).get("findings", [])
                        if f.get("severity") == doctor.BLOCK]
                    raise ValueError("; ".join(details[:5]) or "KI package validation failed")
                published_acceptance.require_current(ki.root, report, name=ki.name,
                                                     origin=self._published_origin)
            except (ValueError, RuntimeError, OSError) as error:
                package_failures.append({"ki": ki.name, "severity": doctor.BLOCK,
                    "check": "kdt-verification", "detail": str(error), "count": 1})
                self._ki_verification.append({"name": ki.name, "state": "PublicationRejected",
                                             "detail": str(error), "report": report})
                self._progress("validate", checked=len(self._ki_verification),
                               total=len(catalog), current=None)
                continue
            self._ki_verification.append({"name": ki.name, "state": "PublishedPackageAccepted",
                "candidate_digest": report["candidate_digest"],
                "software_execution": report.get("software_execution"), "report": report})
            self._progress("validate", checked=len(self._ki_verification),
                           total=len(catalog), current=None)
        if before != _snapshot_content_hash(root):
            raise RuntimeError("KI snapshot changed during verification; activation refused")
        if package_failures:
            preview = "; ".join(f"{item['ki']}: published KDT verification required before activation: "
                                f"{item['detail']}" for item in package_failures[:3])
            raise SnapshotValidationError(f"{len(package_failures)} KI package(s) rejected. {preview}",
                                          package_failures, _portability_files(catalog, root))
        self._validated_content_hash = before
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
        self._published_origin = None
        self._ki_verification = []
        if not self._activation_unresolved:
            self._activation = None
        try:
            if self._activation_unresolved:
                raise RuntimeError("Restart GeoForge before another KI update; library activation is uncertain")
            if self.status().get("state") != "checking":
                self._begin_attempt()
            self._progress("check_main")
            revision, models_sha, manifests_sha = self._remote_revision()
            upstream_revision = revision
            self._set(source_commit=self._source_commit)
            # Resolve the independent raw platform component before the fast
            # path: main may be unchanged while its Windows guidance advances.
            if installation_platform() == "windows":
                self._progress("raw_windows")
            component = self._windows_guidance()
            windows_id = None
            if component is not None:
                from . import raw_windows_guidance
                evidence = raw_windows_guidance.require_current(component["root"], component["evidence"])
                windows_id = evidence["component_id"]
                self._check_retained_guidance_integrity()
            request_revision = (_revision_identity(self._component_trees, windows_id)
                                if component is not None else revision)
            route = self._proxy_url() or "direct"
            self._set(network_route=route)
            state_path = update_root() / "state.json"
            # Keep the exact bytes read before lengthy validation. Reading the
            # dict and fingerprint separately could accept an intervening edit.
            expected_state = _selection_bytes(state_path)
            state = _selection_value(expected_state)
            active = active_library_root(self.current_library_root)
            if active is not None and active.name != str(state.get("active_snapshot") or ""):
                raise RuntimeError("The saved library selection changed while it was being read")
            active_meta = _read_json(active / SNAPSHOT_MANIFEST) if active is not None else {}
            active_windows = (((active_meta.get("windows_overlay") or {}).get("composition") or {})
                              .get("windows") or {}).get("component_id")
            if (state.get("validation_policy") == _validation_policy() and
                    state.get("windows_component_id") == windows_id and active_windows == windows_id and
                    (state.get("revision") == revision or
                 (state.get("upstream_revision") == revision and
                  state.get("overlay_policy") == ki_platform_overlay.POLICY_VERSION)) and
                    active is not None):
                self._activate_candidate(active, state_path=state_path, expected_state=expected_state)
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
                    activation=self._activation,
                )
                return
            guard = _guards_guidance()
            reference = ""
            if guard:
                # The same revision checked against the same library would be
                # refused again; do not download ~90 MB on every launch to see it.
                reference = _guidance_fingerprint(self.current_library_root)
                refused = getattr(self, "_previous_refusal", {})
                if (refused.get("revision") == request_revision and
                        refused.get("reference") == reference and
                        refused.get("policy") == ki_platform_overlay.POLICY_VERSION):
                    self._set(checked_at=checked_at, network_route=route,
                              source_commit=self._source_commit,
                              **self._refusal(request_revision, reference,
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
                self._progress("download")
                archive_meta = self._obtain_archive(archive)
                stage = "extraction"
                self._progress("extract")
                self._extract(archive, incoming)
                self._cache_archive(archive, archive_meta)
                source_hash = _snapshot_content_hash(incoming)
                stage = "windows_overlay"
                self._progress("compose")
                if component is not None:
                    from . import ki_guidance_composition
                    overlay = ki_guidance_composition.compose(component, incoming,
                        source_commit=self._source_commit, archive_sha256=archive_meta["sha256"],
                        source_content_sha256=source_hash)
                    self._check_retained_guidance_integrity()
                else:
                    overlay = ki_platform_overlay.apply_windows_overlay(
                        self.current_library_root, incoming,
                        platform=installation_platform(), upstream_commit=self._source_commit,
                        source_identity=self.current_library_root.name)
                    self._check_overlay_source(overlay)
                if overlay.get("files") or component is not None:
                    revision = _revision_identity(self._component_trees, overlay["overlay_id"])
                retained_overlay = overlay if overlay.get("files") or component is not None else None
                # Windows install notes and recipes live only on the Windows
                # branch; a main snapshot without them would silently take
                # this machine's installation guidance away.
                lost = (_lost_guidance(self.current_library_root, incoming)
                        if guard else [])
                if component is not None:
                    lost = sorted(set(lost) | set(_lost_guidance(component["root"], incoming,
                        source_models=component["evidence"]["models"])))
                if lost:
                    failure = SnapshotValidationError("Required platform installation guidance is missing",
                        [{"ki": row.split(":", 1)[0], "severity": doctor.BLOCK,
                          "check": "installation-guidance", "detail": row, "count": 1} for row in lost], [])
                    validation_failure = self._quarantine(incoming, failure, stage="platform_guard",
                        archive_meta=archive_meta, source_hash=source_hash, overlay=overlay)
                    self._set(checked_at=checked_at, network_route=route,
                              source_commit=self._source_commit,
                              validation_failure=validation_failure,
                              **self._refusal(request_revision, reference, lost))
                    return
                stage = "package_validation"
                self._progress("validate")
                self._published_origin = published_acceptance._issue_origin(incoming,
                    source_commit=self._source_commit, archive_sha256=archive_meta["sha256"],
                    source_content_sha256=source_hash,
                    overlay=retained_overlay,
                    trees=self._component_trees)
                package_count, warning_count, warnings = self._validate(incoming)
                diff = _library_diff(self.current_library_root, incoming)
                helper_changed = (_file_digests(self.current_library_root / "ki_tools_common") !=
                                  _file_digests(incoming / "ki_tools_common"))
                if _snapshot_content_hash(incoming) != self._validated_content_hash:
                    raise RuntimeError("KI snapshot changed after verification; activation refused")
                self._progress("activate")
                _atomic_json(incoming / SNAPSHOT_MANIFEST, {
                    "schema_version": 1, "revision": revision,
                    "source_commit": self._source_commit, "trees": self._component_trees,
                    "upstream_revision": upstream_revision,
                    "windows_component_id": windows_id,
                    "validation_policy": _validation_policy(),
                    "reference_cases": getattr(self, "_reference_case_summary", None),
                    "ki_verification": self._ki_verification,
                    "publication_acceptance": published_acceptance._seal_snapshot(incoming,
                        origin=self._published_origin, rows=self._ki_verification, revision=revision),
                    "warning_count": warning_count, "warnings": warnings,
                    "windows_overlay": retained_overlay,
                    "content_sha256": _snapshot_content_hash(incoming)})
                snapshot = home / "snapshots" / revision
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                stage = "snapshot_activation"
                if _snapshot_content_hash(incoming) != self._validated_content_hash:
                    raise RuntimeError("KI snapshot changed before activation; activation refused")
                if snapshot.exists():
                    cached = _read_json(snapshot / SNAPSHOT_MANIFEST)
                    if (not _snapshot_valid(snapshot) or cached.get("revision") != revision
                            or cached.get("validation_policy") != _validation_policy()
                            or cached.get("trees") != self._component_trees):
                        raise RuntimeError("The cached KI snapshot was changed or is incomplete; preserved without activation")
                    shutil.rmtree(incoming)
                else:
                    incoming.replace(snapshot)
                if not _snapshot_valid(snapshot):
                    raise RuntimeError("Signed publication acceptance is invalid; activation refused")
                new_state = {
                    "active_snapshot": revision,
                    "revision": revision,
                    "upstream_revision": upstream_revision,
                    "overlay_policy": ki_platform_overlay.POLICY_VERSION,
                    "windows_component_id": windows_id,
                    "models_tree": models_sha,
                    "manifests_tree": manifests_sha,
                    "package_count": package_count,
                    "activated_at": time.time(),
                    "branch": self.branch,
                    "source_commit": self._source_commit,
                    "component_trees": self._component_trees,
                    "validation_policy": _validation_policy(),
                }
                self._activate_candidate(snapshot, state_path=state_path,
                                         expected_state=expected_state, new_state=new_state)
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
                    ki_verification=self._ki_verification,
                    activation=self._activation,
                    windows_overlay=retained_overlay, **diff)
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
            self._activation_error_report(error, checked_at=checked_at,
                                          validation_failure=validation_failure)
