"""Compose explicit Windows installation guidance onto a staged upstream KI library.

This module neither activates snapshots nor weakens their validator. Callers must
validate the resulting staging tree, retain this provenance, and include its
overlay_id in the immutable snapshot identity before switching the active pointer.
"""
from __future__ import annotations

import hashlib
import json
import platform as host_platform
from pathlib import Path

import yaml


POLICY_VERSION = "windows-install-overlay-v1"
MAX_GUIDANCE_BYTES = 2 * 1024 * 1024
# These fields describe the Windows executable/install contract, not the
# scientific KI. Treat each whole field atomically; never splice acquire commands
# from one recipe into a different repository or installation strategy.
PLATFORM_FIELDS = frozenset({
    "binary_type", "install_dir", "acquire", "system_deps", "r_package",
    "native_probe", "julia_package", "octave_package", "python_script",
    "reference_case", "startup_marker", "notes", "agent_hint",
})
NEUTRAL_FIELDS = frozenset({"python_deps", "depends_on", "data"})
IDENTITY_FIELDS = frozenset({"kiss_manifest_version", "model"})
_MISSING = object()


class OverlayConflict(ValueError):
    """A platform recipe cannot be composed without an ambiguous substitution."""


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _safe(root: Path, path: Path) -> Path:
    """Reject links and path escapes before reading or creating guidance files."""
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise OverlayConflict(f"Guidance path escapes its library: {path}") from error
    current = root
    for part in relative.parts:
        if part in {".", ".."}:
            raise OverlayConflict(f"Unsafe guidance path: {path}")
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise OverlayConflict(f"Guidance path contains a link: {path}")
    try:
        path.resolve().relative_to(root)
    except ValueError as error:
        raise OverlayConflict(f"Guidance path resolves outside its library: {path}") from error
    return path


def _read(root: Path, path: Path) -> bytes:
    _safe(root, path)
    if not path.is_file() or path.stat().st_size > MAX_GUIDANCE_BYTES:
        raise OverlayConflict(f"Invalid or oversized guidance file: {path}")
    return path.read_bytes()


def _record(root: Path, path: Path, body: bytes) -> dict:
    return {"path": path.relative_to(root).as_posix(), "sha256": _digest(body),
            "bytes": len(body)}


def _manifest(root: Path, path: Path, name: str) -> tuple[dict, bytes]:
    body = _read(root, path)
    try:
        doc = yaml.safe_load(body.decode("utf-8-sig"))
    except (UnicodeError, yaml.YAMLError) as error:
        raise OverlayConflict(f"Invalid platform/generic manifest: {path}") from error
    if (not isinstance(doc, dict) or doc.get("model") != name
            or doc.get("kiss_manifest_version") != 1):
        raise OverlayConflict(f"Manifest identity/schema mismatch for {name}: {path}")
    return doc, body


def _effective_windows(root: Path, name: str, architecture: str) -> Path | None:
    for filename in (f"kiss.windows.{architecture}.yaml", "kiss.windows.yaml"):
        path = _safe(root, root / "models" / name / filename)
        if path.exists():
            if not path.is_file():
                raise OverlayConflict(f"Windows recipe is not a file: {path}")
            return path
    return None


def _generic(root: Path, name: str) -> Path | None:
    for path in (root / "models" / name / "kiss.yaml",
                 root / "kiss" / "manifests" / f"{name}.yaml"):
        _safe(root, path)
        if path.exists():
            if not path.is_file():
                raise OverlayConflict(f"Generic recipe is not a file: {path}")
            return path
    return None


def _independent_generic(base: dict | None, platform: dict) -> bool:
    if base is None or base == platform:
        return False
    # Older Windows releases mirrored their Windows recipe in kiss/manifests.
    # That duplicate is not an ancestor of the canonical generic recipe.
    binary = str(base.get("binary_type", "")).upper()
    produces = str((base.get("acquire") or {}).get("produces", "")).lower()
    return not (binary.startswith("PE") or produces.endswith(".exe"))


def _three_way(base: dict, platform: dict, upstream: dict, name: str) -> dict:
    result = {}
    conflicts = []
    for key in sorted(base.keys() | platform.keys() | upstream.keys()):
        old, local, new = (doc.get(key, _MISSING) for doc in (base, platform, upstream))
        if local == old:
            value = new
        elif new == old or local == new:
            value = local
        else:
            conflicts.append(key)
            continue
        if value is not _MISSING:
            result[key] = value
    if conflicts:
        raise OverlayConflict(f"{name}: concurrent generic/platform changes conflict in "
                              + ", ".join(conflicts))
    return result


def _platform_contract(platform: dict, upstream: dict, name: str) -> dict:
    """No generic ancestor: apply an explicit ownership policy, never fake a rebase."""
    result = dict(upstream)
    known = PLATFORM_FIELDS | NEUTRAL_FIELDS | IDENTITY_FIELDS | {"verified"}
    for key in sorted(platform.keys() | upstream.keys()):
        local, new = platform.get(key, _MISSING), upstream.get(key, _MISSING)
        if key in PLATFORM_FIELDS:
            if local is not _MISSING:
                result[key] = local
            elif new is not _MISSING:
                # Do not add a generic Linux runtime hook to an old Windows
                # recipe merely because it was not represented there.
                result.pop(key, None)
        elif key in NEUTRAL_FIELDS:
            if new is _MISSING and local is not _MISSING:
                result[key] = local
        elif key not in known:
            if local is not _MISSING and new is not _MISSING and local != new:
                raise OverlayConflict(f"{name}: unclassified manifest field conflicts: {key}")
            if new is _MISSING and local is not _MISSING:
                result[key] = local
    return result


def apply_windows_overlay(before: Path, incoming: Path, *, platform: str = "windows",
                          architecture: str | None = None, upstream_commit: str | None = None,
                          source_identity: str | None = None) -> dict:
    """Prepare all changes, reject conflicts, then write missing staged guidance.

    before is read-only. Existing incoming files are never overwritten. The
    return value is a deterministic provenance manifest, not activation evidence.
    """
    before, incoming = Path(before).resolve(), Path(incoming).resolve()
    if before == incoming or before in incoming.parents or incoming in before.parents:
        raise OverlayConflict("Overlay source and staging libraries must be disjoint")
    architecture = (architecture or host_platform.machine()).lower()
    architecture = {"amd64": "x86_64", "aarch64": "arm64"}.get(architecture, architecture)
    if not architecture or not all(c.isalnum() or c in {"_", "-"} for c in architecture):
        raise OverlayConflict("Invalid platform architecture")
    provenance = {"schema_version": 1, "policy": POLICY_VERSION,
                  "platform": platform, "architecture": architecture,
                  "upstream_commit": upstream_commit, "source_identity": source_identity,
                  "files": [], "setup_reverification_required": False}
    pending: list[tuple[Path, bytes]] = []
    models = _safe(incoming, incoming / "models")
    if platform != "windows" or not models.is_dir():
        provenance["overlay_id"] = _digest(json.dumps(provenance, sort_keys=True).encode())
        return provenance
    for ki in sorted(models.iterdir(), key=lambda path: path.name):
        _safe(incoming, ki)
        name = ki.name
        if not (ki / "SKILL.md").is_file() or not (before / "models" / name / "SKILL.md").is_file():
            continue
        _safe(before, before / "models" / name)
        old_notes = before / "models" / name / "docs" / "install.windows.md"
        new_notes = ki / "docs" / "install.windows.md"
        _safe(before, old_notes); _safe(incoming, new_notes)
        if old_notes.is_file() and not new_notes.exists():
            body = _read(before, old_notes)
            pending.append((new_notes, body))
            provenance["files"].append({"mode": "retained_windows_notes",
                "source": _record(before, old_notes, body),
                "output": _record(incoming, new_notes, body)})
        old_recipe = _effective_windows(before, name, architecture)
        new_recipe = _effective_windows(incoming, name, architecture)
        if old_recipe is None or new_recipe is not None:
            continue
        old, old_body = _manifest(before, old_recipe, name)
        generic = _generic(incoming, name)
        base_path = _generic(before, name)
        base, base_body = (_manifest(before, base_path, name)
                           if base_path is not None else (None, None))
        record = {"source": _record(before, old_recipe, old_body),
                  "setup_reverification_required": True}
        if generic is None:
            mode, body = "retained_windows_recipe", old_body
        else:
            upstream, upstream_body = _manifest(incoming, generic, name)
            record["upstream_generic"] = _record(incoming, generic, upstream_body)
            if _independent_generic(base, old):
                merged = _three_way(base, old, upstream, name)
                mode = "three_way_rebase"
                record["base_generic"] = _record(before, base_path, base_body)
            else:
                merged = _platform_contract(old, upstream, name)
                mode = "platform_contract_overlay"
                record["base_generic_unavailable"] = True
                if base_path is not None:
                    record["excluded_platform_duplicate"] = _record(before, base_path, base_body)
            # The old verified flag refers to a different KI/recipe combination.
            merged["verified"] = "unverified"
            body = yaml.safe_dump(merged, sort_keys=False, allow_unicode=True).encode("utf-8")
            record["retained_platform_fields"] = sorted(k for k in PLATFORM_FIELDS if k in merged and merged.get(k) == old.get(k))
            record["incoming_neutral_fields"] = sorted(k for k in NEUTRAL_FIELDS if k in upstream and merged.get(k) == upstream[k])
        target = _safe(incoming, ki / old_recipe.name)
        if target.exists():
            raise OverlayConflict(f"Overlay would overwrite an upstream file: {target}")
        record.update(mode=mode, output=_record(incoming, target, body))
        provenance["files"].append(record)
        provenance["setup_reverification_required"] = True
        pending.append((target, body))
    # Digest source and resulting bytes, not wall-clock time or temporary paths.
    provenance["overlay_id"] = _digest(json.dumps(provenance, sort_keys=True,
                                                  ensure_ascii=False).encode("utf-8"))
    # A semantic/path conflict above cannot leave partially applied guidance.
    for target, body in pending:
        _safe(incoming, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(body)
    return provenance
