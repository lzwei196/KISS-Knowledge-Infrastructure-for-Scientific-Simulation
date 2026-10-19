"""Safe, declarative per-chat project views.

Agents describe a view in ``artifacts/project-view.json``.  GeoForge owns the
renderer and never evaluates JavaScript or HTML supplied by a model or KI.
Existing projects still get a useful view because displayable outputs and
artifacts are discovered automatically when no manifest has been published.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import stat
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

# Model tools commonly write these display files beside their native results.
# Keep active/document/3-D formats outside this additional output-media scope.
OUTPUT_ASSET_MIMES = {suffix: ASSET_MIMES[suffix] for suffix in
                      (".png", ".jpg", ".jpeg", ".gif", ".webp", ".csv", ".mp4", ".webm")}

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
    if str(value).startswith("outputs/"):
        return _safe_output_media(project, value)
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
    if str(relative).startswith("outputs/"):
        if Path(relative).suffix.casefold() == ".json":
            return _safe_report(project, relative), "application/json"
        return _safe_output_media(project, relative)
    return _safe_asset(project, relative, must_exist=True)


def _safe_output_file(project: Path, value: str, extensions: set[str]) -> Path:
    """Only ordinary allowlisted output files, never project internals or aliases."""
    if (not isinstance(value, str) or len(value) > 1600 or "\\" in value or ":" in value
            or any(ord(c) < 32 for c in value)):
        raise ProjectViewError("output links need a literal outputs/ path")
    parts = value.split("/")
    if (len(parts) < 2 or parts[0] != "outputs" or any(
            not part or part.startswith(".") or part.endswith((".", " ")) for part in parts)
            or Path(value).suffix.casefold() not in extensions):
        raise ProjectViewError("output links must name an existing allowlisted outputs/ file")
    root = Path(project).absolute()
    path = root.joinpath(*parts)
    try:
        if path.resolve() != path or not path.resolve().is_relative_to(root):
            raise ProjectViewError("output links cannot use aliases")
        for item in (path, *path.parents):
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ProjectViewError("output links cannot use linked or reparse-point paths")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ProjectViewError("output links require an ordinary file without hardlinks")
        if info.st_size > MAX_ASSET_BYTES:
            raise ProjectViewError("project output file is larger than 100 MB")
    except OSError as error:
        raise ProjectViewError("project output file is missing or unreadable") from error
    return path


def _safe_report(project: Path, value: str) -> Path:
    """Original JSON reports retain their separate file-only contract."""
    return _safe_output_file(project, value, {".json"})


def _safe_output_media(project: Path, value: str) -> tuple[Path, str]:
    path = _safe_output_file(project, value, set(OUTPUT_ASSET_MIMES))
    return path, OUTPUT_ASSET_MIMES[path.suffix.casefold()]


def _output_identity(project: Path, relative: str) -> dict:
    path = _safe_output_file(project, relative, set(OUTPUT_ASSET_MIMES) | {".json"})
    before = path.stat()
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(min(1024 * 1024, before.st_size - total + 1)):
            total += len(chunk)
            if total > before.st_size:
                raise ProjectViewError("project output file changed while being read")
            digest.update(chunk)
    after = _safe_output_file(project, relative, set(OUTPUT_ASSET_MIMES) | {".json"}).stat()
    if (total != before.st_size or
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
        raise ProjectViewError("project output file changed while being read")
    return {"path": relative, "sha256": digest.hexdigest(), "bytes": total,
            "source": "project-output", "scope": "technical-file-association"}


def _report_receipts(project: Path) -> dict:
    """Current latest tool receipt associations, not scientific validation."""
    try:
        from . import flowgate
        flow = flowgate.load()
        flow.states.FlowContext.load(project)  # Reject corrupt/stale host state.
        if flow.approval.check(project) != "OK":
            return {}
        plan, inventory = flow.plan.read_artifacts(project)
        approval = flow.approval.read(project)
        from . import native_stdin
        # The view consumes only current associations. Keep their full checks,
        # but omit old-output hashing and the unused historical display list.
        proof = native_stdin.evidence(flow, project, plan, approval, inventory=inventory,
                                      output_dirs=(), include_history=False)
        statuses = {row["run_id"]: row for row in proof.get("runs", [])}
        latest, writers = {}, {}
        rank = {"passed": 0, "failed": 2}
        docs = [(p, doc) for p, doc, ok in flow.receipts._read_all(project, flow.receipts.RUNS_SUB)
                if ok and doc.get("run_id") in statuses]
        for p, doc in sorted(docs, key=lambda row: (flow.receipts._finished_at(row[1]),
                rank.get(statuses[row[1]["run_id"]].get("validation"), 1))):
            latest[doc.get("plan_step_id")] = (p, doc)
            for entry in doc.get("outputs", []):
                writers[str(entry.get("path"))] = doc["run_id"]
        result = {}
        for step_id, (p, doc) in latest.items():
            if (step_id not in proof.get("steps_passed", []) or step_id in proof.get("stale_steps", [])
                    or statuses[doc["run_id"]].get("validation") != "passed"
                    or doc.get("exit_code") != 0 or doc.get("execution_status") not in (None, "succeeded")):
                continue
            for entry in doc.get("outputs", []):
                if writers.get(str(entry.get("path"))) != doc["run_id"]:
                    continue
                result[str(entry.get("path"))] = {"sha256": entry.get("sha256"), "bytes": entry.get("bytes"),
                    "receipt": {"path": p.relative_to(project).as_posix(), "run_id": doc["run_id"],
                                "plan_step_id": step_id}}
        return result
    except Exception:  # Unknown evidence never promotes an original file to a current receipt.
        return {}


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
        report = (kind == "file" and str(raw.get("path") or "").startswith("outputs/")
                  and Path(str(raw["path"])).suffix.casefold() == ".json")
        if report:
            path = _safe_report(project, str(raw["path"]))
            mime = "application/json"
        else:
            path, mime = _safe_asset(project, str(raw.get("path") or ""))
        relative = path.relative_to(_project_root(project)).as_posix()
        panel["path"] = relative
        panel["mime"] = mime
        if relative.startswith("outputs/"):
            # Association with current exact-byte evidence is technical
            # provenance, never a claim of scientific validation.
            panel["file_provenance"] = _output_identity(project, relative)
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
    panels = _label_panels(project, [_normalize_panel(project, item, index) for index, item in enumerate(raw_panels)])
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


# --- evidence labels (plan v3 B1 item 8 / issue §D) -----------------------------------
# In a flow-managed project a panel is "verified" only when its file is named by a signed
# run/download receipt bound to the current approval whose validation passed; every other
# artifact is shown as experimental / unvalidated. Non-flow projects get no label.

def _receipted_outputs(project: Path) -> dict | None:
    """{rel_path: validation_status} from verified receipts, or None when not flow-managed."""
    if not (project / "runs" / "flow-state.json").is_file():
        return None
    try:
        from . import flowgate
        flow = flowgate.load()
        plan, _inv = flow.plan.read_artifacts(project)
        approval = flow.approval.read(project)
        cur = flow.approval.approval_id(approval or {})
        out: dict = {}
        for sub in (flow.receipts.RUNS_SUB, flow.receipts.DATA_SUB):
            for _p, doc, ok in flow.receipts._read_all(project, sub):
                if not ok or not cur or doc.get("approval_sha256") != cur:
                    continue
                status = (doc.get("validation") or {}).get("status", "passed" if doc.get("kind") == "download" else "not_run")
                for entry in (doc.get("outputs") or []) + (doc.get("raw_files") or []) + (doc.get("processed_files") or []):
                    rel = str(entry.get("path") or "")
                    if rel:
                        out[rel] = status
        return out
    except Exception:  # noqa: BLE001 — labelling must never break publishing; unknown = unvalidated
        return {}


def _label_panels(project: Path, panels: list[dict]) -> list[dict]:
    reports = _report_receipts(project) if any("file_provenance" in p for p in panels) else {}
    receipted = _receipted_outputs(project)
    for panel in panels:
        rel = str(panel.get("path") or "")
        if "file_provenance" in panel:
            provenance = panel["file_provenance"]
            entry = reports.get(rel, {})
            if entry.get("sha256") == provenance["sha256"] and entry.get("bytes") == provenance["bytes"]:
                provenance["receipt"] = entry["receipt"]
                panel["evidence"] = "receipt_bound"
            else:
                panel["evidence"] = "unvalidated"
            panel["revision"] = _panel_revision(project, panel)
            continue
        if receipted is None:
            continue
        status = receipted.get(rel)
        if status == "passed":
            panel["evidence"] = "verified"
        else:
            panel["evidence"] = "unvalidated"
            title = str(panel.get("title") or "")
            if "unvalidated" not in title.casefold():
                panel["title"] = (title + " — experimental / unvalidated")[:160]
    return panels


def publish(project: Path, spec: dict, *, source: str = "agent") -> dict:
    """Validate and atomically publish one project view manifest."""
    normalized = _normalize(Path(project), spec, source=source)
    project = _project_root(project)
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


def displayable_assets(project: Path):
    """Discover allowlisted display files without walking linked directories."""
    project = Path(project).absolute()

    def ordinary_directory(path):
        try:
            info = path.lstat()
            return (stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                    and not getattr(info, "st_file_attributes", 0) & 0x400)
        except OSError:
            return False

    for name, allowed in (("artifacts", ASSET_MIMES), ("outputs", OUTPUT_ASSET_MIMES)):
        root = project / name
        if not ordinary_directory(root):
            continue
        for current, directories, files in os.walk(root, followlinks=False):
            directories[:] = [part for part in directories
                              if ordinary_directory(Path(current) / part)
                              and (name != "outputs" or not part.startswith("."))]
            for filename in files:
                path = Path(current) / filename
                if path.suffix.casefold() not in allowed:
                    continue
                try:
                    yield resolve_asset(project, path.relative_to(project).as_posix())
                except (OSError, ValueError):
                    continue


def _automatic(project: Path) -> dict:
    candidates = []
    for path, _mime in displayable_assets(project):
        try:
            candidates.append((path.stat().st_mtime_ns, path))
        except OSError:
            continue
    panels = []
    for _time, path in sorted(candidates, key=lambda item: (item[0], str(item[1])), reverse=True):
        try:
            panels.append(_auto_panel(project, path, len(panels)))
        except (OSError, ValueError):
            continue
        if len(panels) >= MAX_PANELS:
            break
    panels = _label_panels(project, panels)
    state = {
        "version": 1,
        "title": "Project view",
        "summary": "Automatically assembled from this conversation's project outputs and artifacts.",
        "layout": "grid",
        "skills": [],
        "kis": [],
        "panels": panels,
        "source": "automatic",
        "available": bool(panels),
        "customized": False,
    }
    state["revision"] = _revision(project, state)
    if panels:
        try:
            latest = max((Path(project) / panel["path"]).stat().st_mtime for panel in panels)
            state["updated_at"] = datetime.fromtimestamp(
                latest, timezone.utc).isoformat()
        except OSError:
            pass
    return state


def load(project: Path) -> dict:
    """Load a published view, or safely assemble one from existing artifacts."""
    supplied_project = Path(project)
    project = _project_root(project)
    manifest = _artifacts_root(project) / MANIFEST_NAME
    if not manifest.is_file():
        return _automatic(supplied_project)
    try:
        if manifest.stat().st_size > MAX_MANIFEST_BYTES:
            raise ProjectViewError("project view manifest is larger than 256 KB")
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        result = _normalize(supplied_project, raw, source=_text(raw.get("source") or "agent", 40))
        result["updated_at"] = _text(raw.get("updated_at"), 80)
        result["customized"] = True
        return result
    except (OSError, json.JSONDecodeError, ProjectViewError) as exc:
        fallback = _automatic(supplied_project)
        fallback["error"] = f"The saved project view could not be loaded: {exc}"
        return fallback
