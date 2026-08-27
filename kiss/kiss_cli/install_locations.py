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
SCHEMA_VERSION = 1


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


def resolve(workroot: Path, model: str) -> Path:
    entry = _read_index(workroot).get("models", {}).get(_key(model)) or {}
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
        "created_at": previous.get("created_at") or now,
        "updated_at": now,
    }
    index["schema_version"] = SCHEMA_VERSION
    _write_index(workroot, index)
    return target


def record(model: str, workspace: Path, cfg, *, ki_root: Path | None = None,
           verified: bool | None = None) -> dict:
    """Write the local path contract beside and inside the materialised KI."""
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
    if verified is not None:
        value["verified"] = bool(verified)
        value["verified_at"] = now if verified else None
    workspace.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    if live.is_dir():
        (live / RECORD_FILE).write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    return value


def info(workroot: Path, model: str) -> dict:
    workspace = resolve(workroot, model)
    return {
        "path": str(workspace),
        "default_path": str(default_root(workroot, model)),
        "custom": configured(workroot, model),
        "exists": workspace.is_dir(),
        "recorded": (workspace / RECORD_FILE).is_file(),
        "prepared": (workspace / "ki").is_dir(),
        "config_path": str(workspace / "kiss.toml"),
        "record_path": str(workspace / RECORD_FILE),
    }
