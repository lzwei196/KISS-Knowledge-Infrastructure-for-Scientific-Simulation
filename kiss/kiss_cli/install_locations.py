"""Per-machine installation locations for scientific-model KIs.

The catalogue KI must stay portable, so a researcher's absolute path cannot be
written back into the public package.  GeoForge instead keeps one small index
below its normal work root and writes the same choice into the materialised KI
workspace.  Every caller resolves through this module, which keeps setup,
verification, chat and audit on the same installation.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


INDEX_FILE = "_install-locations.json"
RECORD_FILE = ".geoforge-install.json"
SCHEMA_VERSION = 2
INSTALL_MODES = {"new", "existing"}


def _key(model: str) -> str:
    value = str(model or "").strip()
    if not value:
        raise ValueError("model name is required")
    return value.casefold()


def default_root(workroot: Path, model: str) -> Path:
    return Path(workroot).expanduser().resolve() / str(model).lower()


def _read_index(workroot: Path) -> dict:
    path = Path(workroot).expanduser().resolve() / INDEX_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "models": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("models"), dict):
        return {"schema_version": SCHEMA_VERSION, "models": {}}
    return raw


def _write_index(workroot: Path, value: dict) -> Path:
    root = Path(workroot).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / INDEX_FILE
    pending = path.with_suffix(path.suffix + ".new")
    pending.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    pending.replace(path)
    return path


def configured(workroot: Path, model: str) -> bool:
    return _key(model) in _read_index(workroot).get("models", {})


def resolve(workroot: Path, model: str, *, index: dict | None = None) -> Path:
    source = index if index is not None else _read_index(workroot)
    entry = source.get("models", {}).get(_key(model)) or {}
    raw = entry.get("workspace") if isinstance(entry, dict) else None
    if not raw:
        return default_root(workroot, model)
    candidate = Path(str(raw)).expanduser()
    if not candidate.is_absolute():
        return default_root(workroot, model)
    return candidate.resolve(strict=False)


def _validate_target(value: str | Path) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("choose an installation folder")
    target = Path(raw).expanduser()
    if not target.is_absolute():
        raise ValueError("the installation folder must be an absolute path")
    target = target.resolve(strict=False)
    if target == Path(target.anchor) or target == Path.home().resolve():
        raise ValueError("choose a dedicated model folder, not the disk or home folder")
    if target.exists() and not target.is_dir():
        raise ValueError(f"the installation location is a file: {target}")
    return target


def select(workroot: Path, model: str, value: str | Path) -> Path:
    """Persist and create one user-selected model workspace.

    The target may not exist yet.  Creating it here makes the selection an
    actual, testable location before an agent starts downloading gigabytes.
    """
    workroot = Path(workroot).expanduser().resolve()
    target = _validate_target(value)
    index = _read_index(workroot)
    models = index.setdefault("models", {})
    key = _key(model)
    for other_key, entry in models.items():
        if other_key == key or not isinstance(entry, dict):
            continue
        other = entry.get("workspace")
        if other and Path(str(other)).expanduser().resolve(strict=False) == target:
            raise ValueError(
                f"that folder is already assigned to {entry.get('model') or other_key}")
    target.mkdir(parents=True, exist_ok=True)
    if not os.access(target, os.W_OK):
        raise ValueError(f"the installation folder is not writable: {target}")
    now = time.time()
    previous = models.get(key) if isinstance(models.get(key), dict) else {}
    models[key] = {
        "model": str(model),
        "workspace": str(target),
        "installation_mode": previous.get("installation_mode") or "new",
        "existing_path": previous.get("existing_path"),
        "created_at": previous.get("created_at") or now,
        "updated_at": now,
    }
    index["schema_version"] = SCHEMA_VERSION
    _write_index(workroot, index)
    return target


def select_mode(workroot: Path, model: str, mode: str,
                existing_path: str | Path | None = None) -> dict:
    """Choose whether setup builds a new copy or verifies an existing one.

    The existing software is deliberately *not* used as the writable setup
    workspace.  It may live in /Applications, Homebrew, a shared volume, or a
    read-only source tree.  GeoForge records it as an external read/execute
    binding while keeping its generated KI, logs, links and status below the
    normal model workspace.
    """
    selected = str(mode or "").strip().lower()
    if selected not in INSTALL_MODES:
        raise ValueError("installation mode must be 'new' or 'existing'")
    workroot = Path(workroot).expanduser().resolve()
    index = _read_index(workroot)
    models = index.setdefault("models", {})
    key = _key(model)
    previous = models.get(key) if isinstance(models.get(key), dict) else {}
    workspace = Path(previous.get("workspace") or default_root(workroot, model))
    workspace = workspace.expanduser().resolve(strict=False)
    now = time.time()

    candidate = None
    if selected == "existing":
        raw = str(existing_path or previous.get("existing_path") or "").strip()
        if raw:
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                raise ValueError("the existing installation path must be absolute")
            candidate = candidate.resolve(strict=False)
            if candidate == Path(candidate.anchor) or candidate == Path.home().resolve():
                raise ValueError(
                    "choose the model installation or executable, not the disk or home folder")
            if not candidate.exists():
                raise ValueError(f"the existing installation was not found: {candidate}")

    models[key] = {
        **previous,
        "model": str(model),
        "workspace": str(workspace),
        "installation_mode": selected,
        "existing_path": str(candidate) if candidate else None,
        "created_at": previous.get("created_at") or now,
        "updated_at": now,
    }
    index["schema_version"] = SCHEMA_VERSION
    _write_index(workroot, index)
    return models[key]


def record(model: str, workspace: Path, cfg, *, ki_root: Path | None = None,
           verified: bool | None = None, installation_mode: str | None = None,
           existing_path: str | Path | None = None) -> dict:
    """Write machine state beside the KI without changing accepted KI bytes."""
    workspace = Path(workspace).expanduser().resolve()
    path = workspace / RECORD_FILE
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous = {}
    now = time.time()
    roles = getattr(cfg, "roles", {}) or {}
    live = Path(ki_root or (workspace / "ki")).expanduser().resolve(strict=False)
    value = {
        "schema_version": SCHEMA_VERSION,
        "model": str(model),
        "workspace": str(workspace),
        "ki_root": str(live),
        "binaries": str(roles.get("binaries") or (workspace / "binaries")),
        "python": str(getattr(cfg, "python", "python3")),
        "config": str(workspace / "kiss.toml"),
        "created_at": previous.get("created_at") or now,
        "updated_at": now,
    }
    selected_mode = installation_mode or previous.get("installation_mode") or "new"
    if selected_mode not in INSTALL_MODES:
        selected_mode = "new"
    selected_existing = (str(existing_path) if existing_path is not None
                         else previous.get("existing_path"))
    value["installation_mode"] = selected_mode
    value["existing_path"] = selected_existing or None
    # A discovery-mode agent may identify the exact candidate it used after
    # inspecting several bounded hits. Preserve that evidence across the
    # deterministic verifier's final record rewrite.
    value["resolved_existing_path"] = previous.get("resolved_existing_path")
    value["discovery_candidates"] = previous.get("discovery_candidates") or []
    value["discovery_report"] = previous.get("discovery_report")
    value["discovered_at"] = previous.get("discovered_at")
    if verified is not None:
        value["verified"] = bool(verified)
        value["verified_at"] = now if verified else None
    workspace.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    # Old releases also wrote a copy inside live/. Leave any legacy copy as
    # history; all current readers use the workspace record above. Updating
    # verification timestamps must not look like a KI source edit.
    return value


def invalidate_verification(workspace: Path) -> None:
    """Revoke an existing receipt without claiming a replacement runtime."""
    path = Path(workspace).expanduser().resolve() / RECORD_FILE
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except ValueError:
        value = {}
    if not isinstance(value, dict):
        value = {}
    value.update(verified=False, verified_at=None, updated_at=time.time())
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def info(workroot: Path, model: str) -> dict:
    workspace = resolve(workroot, model)
    entry = _read_index(workroot).get("models", {}).get(_key(model)) or {}
    mode = entry.get("installation_mode") if isinstance(entry, dict) else None
    mode = mode if mode in INSTALL_MODES else "new"
    try:
        local_record = json.loads((workspace / RECORD_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        local_record = {}
    existing_raw = entry.get("existing_path") if isinstance(entry, dict) else None
    if not existing_raw and isinstance(local_record, dict):
        existing_raw = local_record.get("resolved_existing_path")
    existing = (Path(str(existing_raw)).expanduser().resolve(strict=False)
                if existing_raw else None)
    return {
        "path": str(workspace),
        "default_path": str(default_root(workroot, model)),
        "custom": configured(workroot, model),
        "exists": workspace.is_dir(),
        "recorded": (workspace / RECORD_FILE).is_file(),
        "prepared": (workspace / "ki").is_dir(),
        "config_path": str(workspace / "kiss.toml"),
        "record_path": str(workspace / RECORD_FILE),
        "installation_mode": mode,
        "existing_path": str(existing) if existing else None,
        "existing_exists": bool(existing and existing.exists()),
        "existing_kind": ("file" if existing and existing.is_file() else
                          "folder" if existing and existing.is_dir() else None),
        "discovery_candidates": (local_record.get("discovery_candidates") or [])[:24]
        if isinstance(local_record, dict) else [],
        "discovery_report": local_record.get("discovery_report")
        if isinstance(local_record, dict) else None,
    }


def search_candidates(model: str, hints=(), *, limit: int = 24) -> list[str]:
    """Compatibility view of the bounded discovery worker's unverified hits.

    Standalone Setup consumes the full report directly so an incomplete search
    is never presented as proof that the model is absent.
    """
    from . import install, setup_discovery
    with install.scratch_directory("setup-discovery-", None) as temporary:
        report = setup_discovery.discover(model, hints, root=Path(temporary), limit=limit)
    return report["candidates"]


def record_discovery(workspace: Path, candidates: list[str], *, report: dict | None = None) -> Path:
    """Save bounded discovery evidence for the setup agent and later audit."""
    workspace = Path(workspace).expanduser().resolve()
    path = workspace / RECORD_FILE
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    # The supervised worker already canonicalized these candidates. Resolving
    # a network/junction path again here could block the host outside its budget.
    value["discovery_candidates"] = ([str(item) for item in candidates[:24]] if report is not None
        else [str(Path(item).expanduser().resolve(strict=False)) for item in candidates[:24]])
    value["discovered_at"] = time.time()
    if report is not None:
        value["discovery_report"] = report
    workspace.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path
