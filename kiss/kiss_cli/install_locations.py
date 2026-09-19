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
import platform
import re
import shutil
import subprocess
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
    # Unique per process: two installs finishing together used to share one
    # ".new" file, and the loser died on the rename with ENOENT.
    pending = path.with_suffix(f"{path.suffix}.{os.getpid()}.new")
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
    selected_mode = installation_mode or previous.get("installation_mode") or "new"
    if selected_mode not in INSTALL_MODES:
        selected_mode = "new"
    selected_existing = (str(existing_path) if existing_path is not None
                         else previous.get("existing_path"))
    value["installation_mode"] = selected_mode
    value["existing_path"] = selected_existing or None
    # A discovery-mode agent may identify the exact candidate it used after
    # inspecting several indexed hits. Preserve that evidence across the
    # deterministic verifier's final record rewrite.
    value["resolved_existing_path"] = previous.get("resolved_existing_path")
    value["discovery_candidates"] = previous.get("discovery_candidates") or []
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
    }


def search_candidates(model: str, hints=(), *, limit: int = 24) -> list[str]:
    """Find plausible existing installations without crawling personal data.

    This is candidate discovery, never verification.  The setup agent still
    has to inspect a hit and make the KI's real preflight pass.  PATH and the
    operating system's indexed search cover normal package managers and apps;
    a user-selected path remains available for private or unindexed builds.
    """
    raw_hints = [str(model), *[str(x) for x in hints if str(x).strip()]]
    names: list[str] = []
    for raw in raw_hints:
        base = Path(raw).name.strip()
        for value in (base, re.sub(r"[^A-Za-z0-9_.+-]", "", base),
                      re.sub(r"[^A-Za-z0-9]", "", base)):
            if len(value) >= 2 and value.casefold() not in {
                    item.casefold() for item in names}:
                names.append(value)

    found: list[Path] = []

    def add(value) -> None:
        if len(found) >= limit:
            return
        try:
            path = Path(value).expanduser().resolve(strict=False)
        except (OSError, RuntimeError):
            return
        if not path.exists() or path == Path.home().resolve() or path == Path(path.anchor):
            return
        if any(path == prior for prior in found):
            return
        found.append(path)

    # Exact executable names on PATH are the highest quality and cheapest hits.
    for name in names:
        hit = shutil.which(name)
        if hit:
            add(hit)

    bin_roots = [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/usr/bin")]
    if platform.system() == "Windows":
        for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            raw = os.environ.get(key)
            if raw:
                bin_roots.append(Path(raw))
    for root in bin_roots:
        if not root.is_dir():
            continue
        for name in names:
            for spelling in (name, name.lower(), name.upper(), name + ".exe"):
                add(root / spelling)

    # Direct application/package matches cover standard GUI installations.
    app_roots = [Path("/Applications"), Path.home() / "Applications"]
    for root in app_roots:
        if not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        tokens = [re.sub(r"[^a-z0-9]", "", n.casefold()) for n in names]
        for child in children:
            compact = re.sub(r"[^a-z0-9]", "", child.name.casefold())
            if any(token and token in compact for token in tokens):
                add(child)

    # Spotlight searches the index instead of recursively opening the user's
    # disk.  Keep the result small and let the agent verify every candidate.
    if platform.system() == "Darwin" and shutil.which("mdfind"):
        for name in names[:6]:
            query = f"kMDItemFSName == '*{name.replace(chr(39), '')}*'cd"
            try:
                result = subprocess.run(
                    ["mdfind", query], capture_output=True, text=True,
                    errors="replace", timeout=8,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            for line in result.stdout.splitlines()[:80]:
                if any(part in line for part in (
                        "/.Trash/", "/Library/Caches/", "/node_modules/")):
                    continue
                add(line)
                if len(found) >= limit:
                    break
            if len(found) >= limit:
                break
    elif platform.system() == "Windows":
        for name in names[:6]:
            try:
                result = subprocess.run(
                    ["where.exe", name], capture_output=True, text=True,
                    errors="replace", timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            for line in result.stdout.splitlines():
                add(line)

    return [str(path) for path in found]


def record_discovery(workspace: Path, candidates: list[str]) -> Path:
    """Save bounded discovery evidence for the setup agent and later audit."""
    workspace = Path(workspace).expanduser().resolve()
    path = workspace / RECORD_FILE
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    value["discovery_candidates"] = [str(Path(item).expanduser().resolve(strict=False))
                                     for item in candidates[:24]]
    value["discovered_at"] = time.time()
    workspace.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path
