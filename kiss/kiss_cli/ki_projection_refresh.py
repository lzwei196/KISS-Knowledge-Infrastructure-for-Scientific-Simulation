"""Regenerate a repair draft's projected KI files on the host.

``docs/format_spec.yaml`` and ``knowledge_infrastructure.yaml`` are projections:
the KI's generators derive them from ``dag.yaml``, ``diagnostics/triplets.yaml``
and the tool tree, and KDT checks them against those sources. A repair author
can only read and edit files, so it hand-edits projections, which then drift or
stop parsing. After each authoring pass the host reprojects a file that the
pass touched, whose sources changed, or that no longer parses. It uses
GeoForge's bundled projection helpers with the pinned KDT engine's vocabulary,
the same code KDT's own equivalence check imports.

Two server-only inputs are not shipped with GeoForge. The tolerant triplet
reader the helpers import (``candidate_overlay.read_triplets``) is supplied here,
for its documented shapes, only while projecting. The models database behind the
manifest's validation tier and binary exists only on the authoring server, so
those fields are carried over from the draft's baseline unchanged.

This is feedback for the repair author, never acceptance: KDT verification and
adoption stay separate gates.
"""
from __future__ import annotations

import contextlib
import gc
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import types

import yaml

POLICY = "host-projection-refresh-v1"
FORMAT_SPEC = "docs/format_spec.yaml"
MANIFEST = "knowledge_infrastructure.yaml"
SKILL_INDEX = "SKILL.md tool index"
# The generators' own file headers (generate_format_spec.py, generate_ki_manifest.py).
_HEADERS = {
    FORMAT_SPEC: ("# format_spec.yaml — projected from dag.yaml + diagnostics/triplets.yaml\n"
                  "# (format_spec generator, dag-driven + codex-reviewed 2026-08-15)\n\n"),
    MANIFEST: ("# knowledge_infrastructure.yaml — the KI's manifest, PROJECTED from dag.yaml,\n"
               "# the KI contents and the models DB (generate_ki_manifest.py, 2026-08-15).\n\n"),
}
_SOURCES = {
    FORMAT_SPEC: "dag.yaml and diagnostics/triplets.yaml",
    MANIFEST: "dag.yaml, diagnostics/triplets.yaml, the tool tree and the stage docs",
}
_SHARED_MODULES = ("candidate_overlay", "ki_vocabulary", "ki_projection_common")
_MODELS_TABLE = ("create table models (id text, ki_path text, validation_tier text, best_nse real, "
                 "best_kge real, best_r real, n_scorecards integer, binary_path text, binary_type text)")


class ProjectionUnavailable(RuntimeError):
    """The host cannot run the projection helpers; nothing was changed."""


class _Utf8Path(type(Path())):
    """KI text is UTF-8; the helpers' bare read_text() would use the locale codepage on Windows."""

    def read_text(self, encoding="utf-8", errors=None, **kwargs):
        return super().read_text(encoding=encoding, errors=errors, **kwargs)


def read_triplets(doc):
    """Host stand-in for the server's tolerant reader: a list, {triplets} or {diagnostic_triplets}."""
    if doc is None:
        return [], "empty"
    if isinstance(doc, list):
        return [entry for entry in doc if isinstance(entry, dict)], "ok"
    if isinstance(doc, dict):
        for key in ("triplets", "diagnostic_triplets"):
            if isinstance(doc.get(key), list):
                return [entry for entry in doc[key] if isinstance(entry, dict)], "ok"
        return ([], "empty") if not doc else ([], "unreadable")
    return [], "unreadable"


def _load(path: Path, tag: str):
    spec = importlib.util.spec_from_file_location(f"geoforge_projection_{tag}", path)
    if spec is None or spec.loader is None:
        raise ProjectionUnavailable(f"cannot load projection helper {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def _projectors():
    from . import kdtstudio
    tools, engine = kdtstudio._projection_tools_root(), kdtstudio.engine_root()
    if tools is None or not all((tools / name).is_file() for name in
                                ("generate_format_spec.py", "generate_ki_manifest.py",
                                 "ki_projection_common.py")):
        raise ProjectionUnavailable("GeoForge's bundled KI projection helpers are missing")
    if not (engine / "ki_vocabulary.py").is_file():
        raise ProjectionUnavailable("the KDT engine (ki_vocabulary) is not installed")
    overlay = types.ModuleType("candidate_overlay")
    overlay.read_triplets = read_triplets
    # The same lock KDT holds while it changes the import path.
    with kdtstudio._ENGINE_LOCK:
        saved_path = list(sys.path)
        saved_modules = {name: sys.modules.get(name) for name in _SHARED_MODULES}
        sys.path[:0] = [str(engine), str(tools)]
        for name in _SHARED_MODULES:
            sys.modules.pop(name, None)
        sys.modules["candidate_overlay"] = overlay
        try:
            import ki_projection_common as common  # noqa: PLC0415 — resolved from the helper root above
            yield {"common": common,
                   FORMAT_SPEC: _load(tools / "generate_format_spec.py", "format_spec"),
                   MANIFEST: _load(tools / "generate_ki_manifest.py", "manifest")}
        finally:
            sys.path[:] = saved_path
            for name, module in saved_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


def _bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _parsed(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")), True
    except (OSError, UnicodeError, yaml.YAMLError):
        return None, False


def _stages(ki: Path) -> list[str]:
    # The manifest generator's stage rule: docs/sN_*.md or sN_*/ directories.
    return sorted({p.stem for p in (ki / "docs").glob("s[0-9]*_*.md")} |
                  {p.name for p in ki.glob("s[0-9]*_*") if p.is_dir()})


def _reason(target: str, candidate: Path, baseline: Path | None, common) -> str | None:
    if not _parsed(candidate / target)[1]:
        return "it no longer parses"
    if baseline is None or not (baseline / target).is_file():
        return None
    if _bytes(candidate / target) != _bytes(baseline / target):
        return "it was edited by hand in this draft"
    sources = ["dag.yaml", "diagnostics/triplets.yaml"]
    if any(_bytes(candidate / name) != _bytes(baseline / name) for name in sources):
        return "its sources changed"
    if target == MANIFEST and (common.tool_files(_Utf8Path(candidate)) != common.tool_files(_Utf8Path(baseline)) or
                               _stages(candidate) != _stages(baseline)):
        return "its sources changed"
    return None


def _broken_sources(candidate: Path) -> dict[str, str]:
    """Name a source that cannot be parsed; the generators' errors do not say which file."""
    broken = {}
    for name in ("dag.yaml", "diagnostics/triplets.yaml"):
        path = candidate / name
        if path.is_file():
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, yaml.YAMLError) as error:
                broken[name] = str(error).replace('"<unicode string>"', name)[:500]
    return broken


def _carry_db_fields(spec: dict, previous) -> list[str]:
    """Keep the server-database fields the host cannot reproduce."""
    if not isinstance(previous, dict):
        return []
    carried = []
    if "validation" in previous:
        spec["validation"] = previous["validation"]
        carried.append("validation")
    binary = (previous.get("package") or {}).get("binary") if isinstance(previous.get("package"), dict) else None
    if binary is not None and isinstance(spec.get("package"), dict):
        spec["package"]["binary"] = binary
        carried.append("package.binary")
    return carried


def _manifest_spec(module, candidate: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="geoforge-projection-", ignore_cleanup_errors=True) as scratch:
        database = Path(scratch) / "models.db"
        connection = sqlite3.connect(database)
        try:
            connection.execute(_MODELS_TABLE)
            connection.commit()
        finally:
            connection.close()
        original = module.DB
        module.DB = database.as_posix()
        try:
            return module.build(candidate)
        finally:
            module.DB = original
            gc.collect()  # the generator leaves its read-only connection open


def _refresh_tool_index(candidate: Path, result: dict) -> None:
    """Re-list SKILL.md's generated tool index with GeoForge's reviewed tool-inventory projection."""
    from . import ki_maintenance_recipes
    try:
        changes = ki_maintenance_recipes._skill_inventory_changes(candidate)
    except (OSError, UnicodeError, ValueError) as error:
        result["errors"].append({"file": SKILL_INDEX, "reason": "its tool index could not be refreshed",
                                 "error": str(error)[:600]})
        return
    body = changes.get("SKILL.md")
    if body is not None:
        (candidate / "SKILL.md").write_bytes(body)
        result["regenerated"].append({"file": SKILL_INDEX, "reason": "it no longer listed the tool tree",
                                      "sources": "the public files under tools/", "changed": True,
                                      "carried_from_baseline": []})


def refresh(candidate: Path, baseline: Path | None) -> dict:
    """Reproject a draft's stale or hand-edited projections; report what changed."""
    candidate = Path(candidate)
    baseline = Path(baseline) if baseline is not None else None
    result = {"policy": POLICY, "assurance": "feedback_only_not_acceptance",
              "ran": False, "regenerated": [], "errors": []}
    if (candidate / "SKILL.md").is_file():
        _refresh_tool_index(candidate, result)
    targets = [target for target in (FORMAT_SPEC, MANIFEST) if (candidate / target).is_file()]
    if not targets:
        return {**result, "reason": "The draft has no projected YAML files to refresh."}
    try:
        with _projectors() as projectors:
            result["ran"] = True
            broken = _broken_sources(candidate)
            for target in targets:
                reason = _reason(target, candidate, baseline, projectors["common"])
                if reason is None:
                    continue
                if broken:
                    result["errors"].append({"file": target, "reason": reason, "error": "; ".join(
                        f"source {name} does not parse: {error}" for name, error in broken.items())})
                    continue
                try:
                    source = _Utf8Path(candidate)
                    if target == FORMAT_SPEC:
                        spec, carried = projectors[target].build(source), []
                    else:
                        spec = _manifest_spec(projectors[target], source)
                        previous = (_parsed(baseline / MANIFEST)[0]
                                    if baseline is not None and (baseline / MANIFEST).is_file() else None)
                        carried = _carry_db_fields(spec, previous)
                    text = _HEADERS[target] + yaml.safe_dump(spec, sort_keys=False, allow_unicode=True,
                                                             width=100)
                    yaml.safe_load(text)
                except Exception as error:  # noqa: BLE001 — a generator refusing a malformed source
                    result["errors"].append({"file": target, "reason": reason,
                                             "error": f"{type(error).__name__}: {error}"[:600]})
                    continue
                before = _bytes(candidate / target)
                (candidate / target).write_bytes(text.encode("utf-8"))
                result["regenerated"].append({"file": target, "reason": reason, "sources": _SOURCES[target],
                                              "changed": before != text.encode("utf-8"),
                                              "carried_from_baseline": carried})
    except ProjectionUnavailable as error:
        result["reason"] = str(error)
    return result


def feedback(result: dict | None) -> list[str]:
    """Lines telling the repair author what the host reprojected."""
    result = result or {}
    lines = []
    for item in result.get("regenerated") or []:
        carried = item.get("carried_from_baseline") or []
        lines.append(f"The host regenerated {item['file']} because {item['reason']}, from "
                     f"{item['sources']}" + (f"; {', '.join(carried)} kept from the baseline (server "
                                             "database fields)" if carried else "") + ".")
    for item in result.get("errors") or []:
        lines.append(f"The host could not regenerate {item['file']} ({item['reason']}): {item['error']}. "
                     "Fix the source file this names.")
    if lines:
        lines.append("Projected files are host-generated: change dag.yaml, diagnostics/triplets.yaml or "
                     "the tools, not docs/format_spec.yaml, knowledge_infrastructure.yaml or SKILL.md's "
                     "generated tool index.")
    reason = result.get("reason")
    if reason and "no projected" not in reason:
        lines.append("The host could not reproject generated files: " + str(reason))
    return lines
