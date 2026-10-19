"""Official, independently checked KI selections for new setup/project views.

This never activates a global library or changes an existing project. Every
selected package and its declared installation dependencies receive the same
published KDT checks as a full update, with a distinct signed selection scope.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from . import ki_copy, ki_guard, ki_updates, ki_verification, published_acceptance, published_kdt
from .catalog import Catalog
from .manifest import Manifest

POLICY = "official-ki-selection-v1"
CONTRACT = "all-selected-packages-current-published-kdt-v1"
_JOBS: dict[str, threading.Thread] = {}
_LOCK = threading.RLock()


def _implementation() -> str:
    # Frozen apps may retain only their loader's complete module code. Use the
    # same fail-closed, source/code-separated identity as publication profiles.
    return published_kdt._module_identity(sys.modules[__name__])


def _id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError("Invalid official KI selection identifier")
    return value


def _names(values) -> list[str]:
    if (not isinstance(values, list) or not values or len(values) > 127
            or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", v)
                   or v in {".", ".."} for v in values)
            or len({v.casefold() for v in values}) != len(values)):
        raise ValueError("Choose a nonempty, unique list of exact KI names")
    return sorted(values)


def _job_path(job_id: str) -> Path:
    return ki_updates.update_root() / "selection-jobs" / (_id(job_id) + ".json")


def status(job_id: str) -> dict:
    result = ki_updates._read_json(_job_path(job_id))
    if result.get("job_id") != job_id:
        raise ValueError("Official KI selection job is unavailable")
    return result


def _closure(root: Path, requested: list[str]) -> list[str]:
    """Resolve exact manifest dependencies; never fuzzy-match or omit one."""
    catalog = Catalog(root / "models", data_dir=ki_updates.data_ki_root(root))
    pending, selected = list(requested), set()
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        if name not in catalog.packages:
            raise ValueError(f"Required KI is absent from this official revision: {name}")
        ki = catalog.packages[name]
        path = ki.manifest or root / "kiss" / "manifests" / (name + ".yaml")
        if path.is_file():
            manifest = Manifest.load(path)
        elif path.exists() or path.is_symlink():
            raise ValueError(f"Official installation manifest is not a regular file: {name}")
        else:
            # Match normal Desktop setup when this platform has no recipe.
            # The in-memory stub declares no dependencies or readiness; it is
            # never written into the official tree. Every selected package
            # still passes the unchanged publication/KDT gate below.
            manifest = Manifest.stub_for(ki)
        if manifest.model != name:
            raise ValueError(f"Official manifest names a different KI: {name}")
        dependencies = manifest.depends_on
        if dependencies:
            _names(dependencies)
        selected.add(name)
        pending.extend(dependencies)
    return sorted(selected)


def _copy_selection(source: Path, target: Path, names: list[str]) -> dict:
    catalog = Catalog(source / "models", data_dir=ki_updates.data_ki_root(source))
    source_packages = {}
    for name in names:
        ki = catalog.packages[name]
        relative = ki.root.relative_to(source)
        ki_copy.copytree(ki.root, target / relative)
        source_packages[name] = {"path": relative.as_posix(),
                                 "digest": ki_verification.content_digest(ki.root)}
    # One complete helper revision; manifests retain their official names and
    # platform composition. Nonselected KI directories never enter this view.
    for relative in ("ki_tools_common", "kiss/manifests"):
        ki_copy.copytree(source / relative, target / relative)
    return source_packages


def require_selection(scope_id: str) -> tuple[Path, dict]:
    try:
        return _require_selection(scope_id)
    except (AttributeError, KeyError, OSError, TypeError, RuntimeError) as error:
        raise ValueError("Official KI selection metadata is invalid or unavailable") from error


def _require_selection(scope_id: str) -> tuple[Path, dict]:
    root = ki_updates.update_root() / "scoped-snapshots" / _id(scope_id)
    if root.resolve() != root.absolute() or root.parent.resolve() != (
            ki_updates.update_root() / "scoped-snapshots").resolve():
        raise ValueError("Official KI selection path is aliased")
    meta = ki_updates._read_json(root / ki_updates.SNAPSHOT_MANIFEST)
    envelope = meta.get("publication_acceptance") or {}
    if (not published_acceptance._authentic(root, envelope)
            or envelope.get("scope") != "official_published_selection"
            or envelope.get("policy") != POLICY
            or envelope.get("package_validation") != CONTRACT
            or envelope.get("implementation") != _implementation()
            or envelope.get("profile_digest") != published_acceptance.profile_digest()
            or meta.get("revision") != scope_id or envelope.get("revision") != scope_id
            or meta.get("selection_scope") is not True):
        raise ValueError("Official KI selection has no current signed acceptance")
    origin = envelope.get("origin") or {}
    trees = meta.get("trees") or {}
    if (not isinstance(trees, dict) or any(not isinstance(trees.get(key), str)
            or not re.fullmatch(r"[0-9a-f]{40}", trees[key])
            for key in ("models", "manifests", "shared_tools"))
            or (trees.get("data_kis") is not None and not re.fullmatch(
                r"[0-9a-f]{40}", str(trees["data_kis"])))):
        raise ValueError("Official KI selection component identities are invalid")
    if (not published_acceptance._origin_valid(root, origin)
            or meta.get("source_commit") != origin.get("source_commit")
            or meta.get("trees") != origin.get("trees")
            or (meta.get("windows_overlay") or None) != (origin.get("overlay") or None)
            or meta.get("content_sha256") != envelope.get("content_sha256")
            or envelope.get("content_sha256") != ki_updates._snapshot_content_hash(root)
            or envelope.get("content_sha256") != origin.get("candidate_content_sha256")):
        raise ValueError("Official KI selection provenance or contents changed")
    requested, selected = _names(meta.get("requested_models")), _names(meta.get("selected_models"))
    selection = envelope.get("selection") or {}
    actual = Catalog(root / "models", data_dir=ki_updates.data_ki_root(root))
    if (requested != selection.get("requested") or selected != selection.get("selected")
            or set(actual.packages) != set(selected)
            or _closure(root, requested) != selected
            or selection.get("source_packages") != origin.get("packages")
            or not re.fullmatch(r"[0-9a-f]{64}", selection.get("composed_source_sha256", ""))):
        raise ValueError("Official KI selection coverage or dependency closure changed")
    published_acceptance._require_package_reports(root, origin, envelope.get("packages"))
    return root, meta


def catalogue_bindings(catalog) -> dict:
    root = Path(catalog.models_dir).resolve().parent
    if root.parent != (ki_updates.update_root() / "scoped-snapshots").resolve():
        return {}
    try:
        checked, meta = require_selection(root.name)
        origin = meta["publication_acceptance"]["origin"]
        return {name: row["digest"] for name, row in origin["packages"].items()
                if name in catalog.packages and catalog.packages[name].root.resolve()
                == (checked / row["path"]).resolve()}
    except (OSError, ValueError, TypeError, RuntimeError):
        return {}


class _Builder(ki_updates.UpdateManager):
    def __init__(self, current_library_root: Path, names: list[str], expected_commit: str | None):
        super().__init__(current_library_root, lambda _: None, branch="main")
        self.job_id = uuid.uuid4().hex
        self.requested = _names(names)
        if expected_commit is not None and not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
            raise ValueError("Expected official revision must be an exact commit")
        self.expected_commit = expected_commit
        self._report = {"job_id": self.job_id, "state": "checking",
                        "requested": self.requested, "scope_id": None,
                        "global_library_changed": False, "started_at": time.time()}
        self._set(progress={"stage": "check_main", "checked": None, "total": None, "current": None})

    def _set(self, **values) -> None:
        with self._lock:
            self._report = {**self._report, **values}
            ki_updates._atomic_json(_job_path(self.job_id), self._report)

    def build(self) -> dict:
        home = ki_updates.update_root()
        target = home / (".incoming-selection-" + self.job_id)
        try:
            self._progress("check_main")
            self._remote_revision()
            if self.expected_commit is not None and self._source_commit != self.expected_commit:
                raise ValueError("The official KI revision changed; refresh the update report before selecting it")
            if not re.fullmatch(r"[0-9a-f]{40}", self._source_commit or ""):
                raise ValueError("Official KI selection requires an authenticated exact revision")
            self._set(source_commit=self._source_commit)
            component = self._windows_guidance()
            with tempfile.TemporaryDirectory(prefix=".selection-source-", dir=home) as temporary:
                work = Path(temporary)
                archive, source = work / "source.zip", work / "source"
                self._progress("download")
                archive_meta = self._obtain_archive(archive)
                self._progress("extract")
                self._extract(archive, source)
                self._cache_archive(archive, archive_meta)
                source_hash = ki_updates._snapshot_content_hash(source)
                self._progress("compose")
                if component is not None:
                    from . import ki_guidance_composition
                    overlay = ki_guidance_composition.compose(component, source,
                        source_commit=self._source_commit, archive_sha256=archive_meta["sha256"],
                        source_content_sha256=source_hash)
                    self._check_retained_guidance_integrity()
                else:
                    from . import ki_platform_overlay
                    overlay = ki_platform_overlay.apply_windows_overlay(self.current_library_root, source,
                        platform=ki_updates.installation_platform(), upstream_commit=self._source_commit,
                        source_identity=self.current_library_root.name)
                    self._check_overlay_source(overlay)
                selected = _closure(source, self.requested)
                lost = ki_updates._lost_guidance(self.current_library_root, source) if ki_updates._guards_guidance() else []
                if component is not None:
                    lost += ki_updates._lost_guidance(component["root"], source,
                        source_models=component["evidence"]["models"])
                relevant_lost = [item for item in lost if item.split(":", 1)[0] in selected]
                if relevant_lost:
                    raise ValueError("Selected KI lost required platform guidance: " + "; ".join(relevant_lost))
                composed_hash = ki_updates._snapshot_content_hash(source)
                source_packages = _copy_selection(source, target, selected)
                if ki_updates._snapshot_content_hash(source) != composed_hash:
                    raise ValueError("Official source changed while selecting packages")
                kept_overlay = overlay if overlay.get("files") or component is not None else None
                self._published_origin = published_acceptance._issue_origin(target,
                    source_commit=self._source_commit, archive_sha256=archive_meta["sha256"],
                    source_content_sha256=source_hash, overlay=kept_overlay, trees=self._component_trees)
                if source_packages != self._published_origin["packages"]:
                    raise ValueError("Selected package bytes differ from the official composed source")
                self._validate(target)
                if ki_updates._snapshot_content_hash(target) != self._published_origin["candidate_content_sha256"]:
                    raise ValueError("Selected KI files changed after package verification")
                selection = {"requested": self.requested, "selected": selected,
                             "source_packages": source_packages, "composed_source_sha256": composed_hash}
                content = ki_updates._snapshot_content_hash(target)
                revision = published_acceptance._hash({"selection": selection, "content": content,
                    "source_commit": self._source_commit, "policy": POLICY,
                    "implementation": _implementation(), "profile": published_acceptance.profile_digest()})[:32]
                published_acceptance._require_package_reports(target, self._published_origin, self._ki_verification)
                envelope = published_acceptance._sign(target, {
                    "scope": "official_published_selection", "policy": POLICY,
                    "package_validation": CONTRACT, "implementation": _implementation(),
                    "profile_digest": published_acceptance.profile_digest(), "revision": revision,
                    "content_sha256": content, "origin": self._published_origin,
                    "packages": self._ki_verification, "selection": selection,
                    "checked_at": time.time(), "native_regression": "not_run"})
                meta = {"schema_version": 1, "selection_scope": True, "revision": revision,
                    "source_commit": self._source_commit, "trees": self._component_trees,
                    "requested_models": self.requested, "selected_models": selected,
                    "content_sha256": content, "windows_overlay": kept_overlay,
                    "publication_acceptance": envelope}
                ki_updates._atomic_json(target / ki_updates.SNAPSHOT_MANIFEST, meta)
                destination = home / "scoped-snapshots" / revision
                destination.parent.mkdir(parents=True, exist_ok=True)
                self._progress("activate")
                if destination.exists():
                    require_selection(revision)
                    # Only our generated, direct-child staging tree is removed.
                    if target.resolve().parent != home.resolve() or target.name != ".incoming-selection-" + self.job_id:
                        raise ValueError("Selection staging path changed")
                    shutil.rmtree(target)
                else:
                    target.replace(destination)
                root, checked = require_selection(revision)
                catalog = Catalog(root / "models", data_dir=ki_updates.data_ki_root(root))
                enrolled = ki_guard.enroll_catalogue(catalog)
                if enrolled.get("errors"):
                    raise ValueError("Selected catalogue integrity could not be established")
                components = ki_updates.component_sources(root)
                if not (root / "kiss/data_kis").is_dir():
                    components["data_kis"] = {"state": "not_in_source" if self._component_trees.get("data_kis") is None else "not_selected", "tree_sha": None,
                        "source_commit": None, "upstream_tree_sha": self._component_trees.get("data_kis")}
                self._set(state="ready", scope_id=revision, models=selected, root=str(root),
                    components=components, progress=None,
                    summary="Checked KI selection is ready for a new setup or project. Global library unchanged.",
                    finished_at=time.time())
        except Exception as error:
            self._set(state="error", error=str(error)[:3000], progress=None, scope_id=None,
                      finished_at=time.time())
        return self.status()


def start(current_library_root: Path, names: list[str], *, expected_commit: str | None = None) -> dict:
    with _LOCK:
        if any(worker.is_alive() for worker in _JOBS.values()):
            raise ValueError("An official KI selection check is already running")
        builder = _Builder(current_library_root, names, expected_commit)
        worker = threading.Thread(target=builder.build, name="KI-selection-" + builder.job_id, daemon=True)
        # Completed results stay on disk; retain only a bounded thread index.
        while len(_JOBS) >= 32:
            _JOBS.pop(next(iter(_JOBS)))
        _JOBS[builder.job_id] = worker
        worker.start()
    return builder.status()
