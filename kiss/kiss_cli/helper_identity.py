"""Relevant portable helper bytes, independent of a whole repository revision."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import ki_tree


MARKER = ".geoforge-common.json"


def package_files(root: Path) -> dict[str, str]:
    """Hash a bounded contained tree; generated installation metadata is ignored."""
    root = Path(root)
    inventory = ki_tree.scan(root)
    result = {}
    total = 0
    for entry in inventory.entries:
        name = entry.relative
        if (name == MARKER or any(part == "__pycache__" or part.endswith(".egg-info")
                                  for part in Path(name).parts)
                or name.endswith((".pyc", ".pyo"))):
            continue
        if entry.kind == "link":
            # Preserve the existing cache marker's link spelling contract.
            result[name] = "link:" + os.readlink(root / name)
        elif entry.kind == "file":
            digest = hashlib.sha256()
            with (root / name).open("rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    total += len(chunk)
                    if total > ki_tree.MAX_BYTES:
                        raise ValueError("Shared helpers exceed the tree byte limit")
                    digest.update(chunk)
            result[name] = digest.hexdigest()
    def stable(entries):
        return [(entry.relative, entry.kind, entry.size,
                 0 if entry.kind == "directory" else entry.mtime_ns, entry.target)
                for entry in entries]
    if stable(ki_tree.scan(root).entries) != stable(inventory.entries):
        raise ValueError("Shared helpers changed while computing their identity")
    return result


def source_identity(repo_root: Path) -> str:
    """Return the portable helper identity; missing or unsafe sources fail closed."""
    files = package_files(Path(repo_root) / "ki_tools_common")
    if not files:
        raise ValueError("Shared helper source contains no relevant files")
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def checked_marker(root: Path) -> tuple[dict, dict[str, str], bool]:
    """Validate a local immutable copy; this does not authenticate its publisher."""
    root = Path(root)
    actual = package_files(root)
    try:
        marker = root / MARKER
        if marker.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("marker is too large")
        saved = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            raise ValueError("marker is not an object")
        legacy = "binding" not in saved and "schema_version" not in saved
        binding = ({key: saved.get(key) for key in ("source_commit", "source_tree", "roles")}
                   if legacy else saved.get("binding"))
        if (not isinstance(binding, dict) or not isinstance(saved.get("files"), dict)
                or saved.get("binding_sha256") != hashlib.sha256(
                    json.dumps(binding, sort_keys=True).encode()).hexdigest()
                or saved["files"] != actual
                or (not legacy and saved.get("schema_version") != 2)):
            raise ValueError("marker identity or relevant files differ")
        if not legacy:
            files = binding.get("source_files")
            if not isinstance(files, dict) or not files:
                raise ValueError("portable source inventory is missing")
        return binding, actual, legacy
    except (OSError, ValueError, TypeError) as error:
        raise ValueError(f"Pinned shared helpers changed locally; preserved without overwriting: {root}") from error


def prepared_source_identity(root: Path) -> str | None:
    """Portable source digest from a checked v2 copy; legacy markers lack it.

    These are local consistency checks, not signed upstream provenance. A
    caller granting adoption must also match its trusted source/receipt.
    """
    binding, _, legacy = checked_marker(root)
    if legacy:
        return None
    return hashlib.sha256(json.dumps(binding["source_files"], sort_keys=True).encode()).hexdigest()
