"""Safe, declarative per-chat project views.

Agents describe a view in ``artifacts/project-view.json``.  GeoForge owns the
renderer and never evaluates JavaScript or HTML supplied by a model or KI.
Existing projects still get a useful view because displayable artifacts are
discovered automatically when no manifest has been published.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


MANIFEST_NAME = "project-view.json"
MAX_MANIFEST_BYTES = 256_000
MAX_ASSET_BYTES = 100 * 1024 * 1024
MAX_PANELS = 24
MAX_TABLE_ROWS = 100
MAX_TABLE_COLUMNS = 20

ASSET_MIMES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".csv": "text/csv; charset=utf-8",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".pdf": "application/pdf",
}

KINDS = {"metric", "image", "animation", "map", "table", "file", "model3d"}
MEDIA_KINDS = {"image", "animation", "map", "table", "file", "model3d"}
ID_RE = re.compile(r"[^a-zA-Z0-9_-]+")


class ProjectViewError(ValueError):
    pass


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _project_root(project: Path) -> Path:
    return Path(project).expanduser().resolve()


def _artifacts_root(project: Path) -> Path:
    return (_project_root(project) / "artifacts").resolve()


def _safe_asset(project: Path, value: str, *, must_exist: bool = True) -> tuple[Path, str]:
    relative = Path(str(value or ""))
    if relative.is_absolute() or ".." in relative.parts:
        raise ProjectViewError("project view asset paths must be relative")
    project = _project_root(project)
    artifacts = _artifacts_root(project)
    path = (project / relative).resolve()
    if path == artifacts or artifacts not in path.parents:
        raise ProjectViewError("project view assets must stay below artifacts/")
    mime = ASSET_MIMES.get(path.suffix.casefold())
    if not mime:
        raise ProjectViewError(f"unsupported project view asset: {path.suffix or 'no extension'}")
    if must_exist and not path.is_file():
        raise ProjectViewError(f"project view asset does not exist: {relative.as_posix()}")
    if must_exist and path.stat().st_size > MAX_ASSET_BYTES:
        raise ProjectViewError("project view asset is larger than 100 MB")
    return path, mime


def resolve_asset(project: Path, relative: str) -> tuple[Path, str]:
    """Resolve an asset for the HTTP layer without permitting traversal."""
    return _safe_asset(project, relative, must_exist=True)


def _table_preview(path: Path) -> dict:
    rows: list[list[str]] = []
    columns: list[str] = []
    truncated = False
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.reader(handle)
            first = next(reader, None)
            if first is None:
                return {"columns": [], "rows": [], "truncated": False}
            columns = [_text(item, 120) for item in first[:MAX_TABLE_COLUMNS]]
            if len(first) > MAX_TABLE_COLUMNS:
                truncated = True
            for index, row in enumerate(reader):
                if index >= MAX_TABLE_ROWS:
                    truncated = True
                    break
                rows.append([_text(item, 500) for item in row[:MAX_TABLE_COLUMNS]])
    except OSError as exc:
        return {"columns": [], "rows": [], "truncated": False, "error": str(exc)}
    return {"columns": columns, "rows": rows, "truncated": truncated}


def _revision(project: Path, state: dict) -> str:
    """Content identity used to update panels without remounting live media."""
    stable = {
        key: state.get(key) for key in
        ("version", "title", "summary", "layout", "skills", "kis", "source")
    }
    stable["panels"] = [
        {key: value for key, value in panel.items() if key != "table"}
        for panel in state.get("panels") or []
    ]
    digest = hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    root = _project_root(project)
    for panel in state.get("panels") or []:
        relative = panel.get("path")
        if not relative:
            continue
        try:
            stat = (root / relative).stat()
            digest.update(f"{relative}\0{stat.st_mtime_ns}\0{stat.st_size}".encode())
        except OSError:
            digest.update(f"{relative}\0missing".encode())
    return digest.hexdigest()[:20]


def _panel_revision(project: Path, panel: dict) -> str:
    """Identity for one panel so unrelated live panels can keep their state."""
    stable = {
        key: value for key, value in panel.items()
        if key not in {"revision", "table"}
    }
    digest = hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    relative = panel.get("path")
    if relative:
        try:
            stat = (_project_root(project) / relative).stat()
            digest.update(
                f"{relative}\0{stat.st_mtime_ns}\0{stat.st_size}".encode()
            )
        except OSError:
            digest.update(f"{relative}\0missing".encode())
    return digest.hexdigest()[:20]


def _normalize_panel(project: Path, raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ProjectViewError(f"panel {index + 1} must be an object")
    kind = _text(raw.get("kind"), 24).casefold()
    if kind not in KINDS:
        raise ProjectViewError(f"panel {index + 1} has unsupported kind {kind!r}")
    ident = ID_RE.sub("-", _text(raw.get("id") or f"panel-{index + 1}", 80)).strip("-")
    panel = {
        "id": ident or f"panel-{index + 1}",
        "kind": kind,
        "title": _text(raw.get("title") or kind.title(), 160),
    }
    for key, limit in (("caption", 1000), ("status", 80), ("unit", 80), ("renderer", 80)):
        if raw.get(key) is not None:
            panel[key] = _text(raw.get(key), limit)
    if kind == "metric":
        value = raw.get("value")
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ProjectViewError(f"metric panel {panel['id']} needs a string or numeric value")
        panel["value"] = _text(value, 160)
    else:
        path, mime = _safe_asset(project, str(raw.get("path") or ""))
        relative = path.relative_to(_project_root(project)).as_posix()
        panel["path"] = relative
        panel["mime"] = mime
        if kind == "table" and path.suffix.casefold() != ".csv":
            raise ProjectViewError("table panels currently require a CSV artifact")
        if kind == "table":
            panel["table"] = _table_preview(path)
    panel["revision"] = _panel_revision(project, panel)
    return panel


def _normalize(project: Path, raw: dict, *, source: str) -> dict:
    if not isinstance(raw, dict):
        raise ProjectViewError("project view must be a JSON object")
    try:
        version = int(raw.get("version", 1))
    except (TypeError, ValueError):
        raise ProjectViewError("project view version must be an integer")
    if version != 1:
        raise ProjectViewError(f"unsupported project view version: {version}")
    raw_panels = raw.get("panels") or []
    if not isinstance(raw_panels, list) or len(raw_panels) > MAX_PANELS:
        raise ProjectViewError(f"project view supports at most {MAX_PANELS} panels")
    panels = [_normalize_panel(project, item, index) for index, item in enumerate(raw_panels)]
    identifiers = [item["id"] for item in panels]
    if len(set(identifiers)) != len(identifiers):
        raise ProjectViewError("project view panel ids must be unique")
    layout = _text(raw.get("layout") or "grid", 20).casefold()
    if layout not in {"grid", "single"}:
        raise ProjectViewError("project view layout must be grid or single")
    skills = raw.get("skills") or []
    kis = raw.get("kis") or []
    if not isinstance(skills, list) or not isinstance(kis, list):
        raise ProjectViewError("skills and kis must be arrays")
    result = {
        "version": 1,
        "title": _text(raw.get("title") or "Project view", 160),
        "summary": _text(raw.get("summary"), 1200),
        "layout": layout,
        "skills": [_text(item, 120) for item in skills[:20] if _text(item, 120)],
        "kis": [_text(item, 120) for item in kis[:20] if _text(item, 120)],
        "panels": panels,
        "source": source,
        "available": bool(panels),
    }
    result["revision"] = _revision(project, result)
    return result


def publish(project: Path, spec: dict, *, source: str = "agent") -> dict:
    """Validate and atomically publish one project view manifest."""
    project = _project_root(project)
    normalized = _normalize(project, spec, source=source)
    normalized["updated_at"] = datetime.now(timezone.utc).isoformat()
    target = _artifacts_root(project) / MANIFEST_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(normalized, ensure_ascii=False, indent=2).encode("utf-8")
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ProjectViewError("project view manifest is larger than 256 KB")
    temporary = target.with_suffix(".json.tmp")
    temporary.write_bytes(encoded)
    temporary.replace(target)
    result = dict(normalized)
    result["customized"] = True
    return result


def _auto_panel(project: Path, path: Path, index: int) -> dict:
    suffix = path.suffix.casefold()
    if suffix in {".mp4", ".webm", ".gif", ".webp"}:
        kind = "animation"
    elif suffix == ".csv":
        kind = "table"
    elif suffix in {".glb", ".gltf"}:
        kind = "model3d"
    elif suffix in {".png", ".jpg", ".jpeg", ".svg"}:
        kind = "image"
    else:
        kind = "file"
    stable_id = hashlib.sha256(
        path.relative_to(_project_root(project)).as_posix().encode("utf-8")
    ).hexdigest()[:12]
    return _normalize_panel(project, {
        "id": f"artifact-{stable_id}",
        "kind": kind,
        "title": path.stem.replace("_", " ").replace("-", " ").strip().title(),
        "path": path.relative_to(_project_root(project)).as_posix(),
    }, index)


def _automatic(project: Path) -> dict:
    root = _artifacts_root(project)
    paths: list[Path] = []
    if root.is_dir():
        for path in sorted(root.rglob("*"), key=lambda item: item.stat().st_mtime if item.is_file() else 0,
                           reverse=True):
            try:
                if (path.is_file() and path.name != MANIFEST_NAME
                        and path.suffix.casefold() in ASSET_MIMES
                        and path.stat().st_size <= MAX_ASSET_BYTES):
                    paths.append(path)
            except OSError:
                continue
            if len(paths) >= MAX_PANELS:
                break
    panels = [_auto_panel(project, path, index) for index, path in enumerate(paths)]
    state = {
        "version": 1,
        "title": "Project view",
        "summary": "Automatically assembled from this conversation's project artifacts.",
        "layout": "grid",
        "skills": [],
        "kis": [],
        "panels": panels,
        "source": "automatic",
        "available": bool(panels),
        "customized": False,
    }
    state["revision"] = _revision(project, state)
    if paths:
        try:
            latest = max(path.stat().st_mtime for path in paths)
            state["updated_at"] = datetime.fromtimestamp(
                latest, timezone.utc).isoformat()
        except OSError:
            pass
    return state


def load(project: Path) -> dict:
    """Load a published view, or safely assemble one from existing artifacts."""
    project = _project_root(project)
    manifest = _artifacts_root(project) / MANIFEST_NAME
    if not manifest.is_file():
        return _automatic(project)
    try:
        if manifest.stat().st_size > MAX_MANIFEST_BYTES:
            raise ProjectViewError("project view manifest is larger than 256 KB")
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        result = _normalize(project, raw, source=_text(raw.get("source") or "agent", 40))
        result["updated_at"] = _text(raw.get("updated_at"), 80)
        result["customized"] = True
        return result
    except (OSError, json.JSONDecodeError, ProjectViewError) as exc:
        fallback = _automatic(project)
        fallback["error"] = f"The saved project view could not be loaded: {exc}"
        return fallback
