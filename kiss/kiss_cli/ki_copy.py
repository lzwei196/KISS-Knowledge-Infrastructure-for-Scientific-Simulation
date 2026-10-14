"""Copy a validated KI without expanding its contained aliases into duplicates."""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from . import ki_tree


def link_target(entry) -> Path:
    """Native relative spelling, independent of source/destination location."""
    return Path(os.path.relpath(entry.target, Path(entry.relative).parent))


def copytree(source: Path, target: Path, *, dirs_exist_ok: bool = False) -> Path:
    """Copy into a fresh (or explicitly empty) destination and prove equivalence.

    This does not grant trust or adopt the copy. Callers still apply the exact
    authoring/publication and integrity gates appropriate to their boundary.
    """
    source, target = Path(source), Path(target)
    inventory = ki_tree.scan(source)
    before = ki_tree.digest(source)
    if not before:
        raise ValueError("Cannot establish the KI tree before copying")
    try:
        target_info = target.lstat()
    except FileNotFoundError:
        target_info = None
    if target_info is not None and (stat.S_ISLNK(target_info.st_mode)
            or getattr(target_info, "st_file_attributes", 0) &
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise ValueError("KI copy destination may not be a link or reparse point")
    source_abs, target_abs = source.resolve(), target.resolve()
    if (source_abs == target_abs or source_abs in target_abs.parents
            or target_abs in source_abs.parents):
        raise ValueError("KI source and destination must be separate trees")
    if target.exists() and (not dirs_exist_ok or not target.is_dir() or any(target.iterdir())):
        raise ValueError("KI copy destination must be new or explicitly empty")
    target.mkdir(parents=True, exist_ok=dirs_exist_ok)
    for entry in inventory.entries:
        destination = target / entry.relative
        if entry.kind == "directory":
            destination.mkdir(parents=True, exist_ok=True)
        elif entry.kind == "file":
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / entry.relative, destination)
    # Targets now exist. Never dereference an alias during the physical copy.
    for entry in inventory.entries:
        if entry.kind != "link":
            continue
        destination = target / entry.relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(link_target(entry), target_is_directory=(target / entry.target).is_dir())
    if ki_tree.digest(source) != before or ki_tree.digest(target) != before:
        raise ValueError("KI changed while copying; nothing was accepted")
    return target
