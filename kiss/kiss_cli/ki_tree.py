"""Bounded KI file trees with explicit, same-tree terminal aliases.

Canonical directories are walked once. Links never expand the tool inventory:
their identity is the alias path and normalized terminal target, whose bytes
already belong to the canonical inventory. Link chains are deliberately not
supported in this first contract. This module grants no adoption authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat


POLICY = "ki-internal-alias-tree-v1"
MAX_ENTRIES = 20_000
MAX_BYTES = 2 * 1024 * 1024 * 1024


class TreeError(ValueError):
    """A KI tree cannot be represented safely by the current contract."""


@dataclass(frozen=True)
class TreeEntry:
    relative: str
    kind: str
    size: int
    mtime_ns: int
    target: str | None = None


@dataclass(frozen=True)
class TreeInventory:
    root: Path
    entries: tuple[TreeEntry, ...]


def _reparse(info) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) &
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _target(relative: str, raw: str) -> str:
    windows = PureWindowsPath(raw)
    if (not raw or "\0" in raw or windows.drive or windows.root
            or PurePosixPath(raw).is_absolute()):
        raise TreeError(f"KI alias has an absolute, drive-qualified or invalid target: {relative}")
    # Archives spell relative links with '/', while Windows link objects must
    # use '\\'. Both encode the same logical target in the signed identity.
    pieces = list(PurePosixPath(relative).parent.parts)
    for part in PurePosixPath(raw.replace("\\", "/")).parts:
        if part == "..":
            if not pieces:
                raise TreeError(f"KI alias escapes its root: {relative}")
            pieces.pop()
        elif part != ".":
            pieces.append(part)
    return "/".join(pieces)


def scan(root: Path, *, max_entries: int = MAX_ENTRIES,
         max_bytes: int = MAX_BYTES) -> TreeInventory:
    """Validate a physical tree without following links or junctions.

    Link targets must be existing canonical files/directories inside this KI.
    Ancestor/self directory aliases and aliases through other aliases fail.
    """
    if (type(max_entries) is not int or max_entries < 0
            or type(max_bytes) is not int or max_bytes < 0):
        raise TreeError("tree limits must be nonnegative integers")
    root = Path(root).absolute()
    root_info = root.lstat()
    if (stat.S_ISLNK(root_info.st_mode) or _reparse(root_info)
            or not stat.S_ISDIR(root_info.st_mode)):
        raise TreeError("KI root must be a real directory, not a link or reparse point")
    entries: dict[str, TreeEntry] = {}
    raw_targets: dict[str, str] = {}
    pending = [root]
    total = 0
    while pending:
        parent = pending.pop()
        parent_info = parent.lstat()
        if (stat.S_ISLNK(parent_info.st_mode) or _reparse(parent_info)
                or not stat.S_ISDIR(parent_info.st_mode)):
            raise TreeError("KI directory changed while inspecting the tree")
        with os.scandir(parent) as children:
            for child in children:
                path = parent / child.name
                relative = path.relative_to(root).as_posix()
                if len(entries) >= max_entries:
                    raise TreeError(f"candidate has more than {max_entries} entries")
                info = child.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    tag = getattr(info, "st_reparse_tag", None)
                    if tag not in (None, 0, getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C)):
                        raise TreeError(f"KI contains an unsupported reparse point: {relative}")
                    raw_targets[relative] = os.readlink(path)
                    entry = TreeEntry(relative, "link", 0, info.st_mtime_ns,
                                      _target(relative, raw_targets[relative]))
                elif _reparse(info):
                    raise TreeError(f"KI contains an unsupported reparse point: {relative}")
                elif stat.S_ISDIR(info.st_mode):
                    entry = TreeEntry(relative, "directory", 0, info.st_mtime_ns)
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    total += info.st_size
                    if total > max_bytes:
                        raise TreeError(f"candidate is larger than {max_bytes} bytes")
                    entry = TreeEntry(relative, "file", info.st_size, info.st_mtime_ns)
                else:
                    raise TreeError(f"KI contains an unsupported file type: {relative}")
                entries[relative] = entry
    directories = {"": []}
    for entry in entries.values():
        if entry.kind == "directory":
            directories[entry.relative] = []
    for entry in entries.values():
        if entry.kind == "directory":
            parent = PurePosixPath(entry.relative).parent.as_posix()
            directories["" if parent == "." else parent].append(entry.relative)
    for entry in entries.values():
        if entry.kind != "link":
            continue
        target = entry.target
        # Check every path component before collapsing '..'. A prefix alias
        # or a missing/non-directory prefix must not acquire a safe-looking
        # lexical target by being cancelled out by a later parent segment.
        parts = list(PurePosixPath(entry.relative).parent.parts)
        for component in raw_targets[entry.relative].replace("\\", "/").split("/"):
            current = "/".join(parts)
            if current not in directories:
                raise TreeError(f"KI alias has a non-directory target prefix: {entry.relative}")
            if component == "..":
                parts.pop()  # _target already proved no root escape.
            elif component not in ("", "."):
                parts.append(component)
                prefix = entries.get("/".join(parts))
                if prefix is None:
                    raise TreeError(f"KI alias target is missing: {entry.relative} -> {target}")
                if prefix.kind == "link":
                    raise TreeError(f"KI alias chains are not supported: {entry.relative}")
        terminal = entries.get(target)
        if not target or (terminal is not None and terminal.kind == "directory"
                          and PurePosixPath(entry.relative).is_relative_to(PurePosixPath(target))):
            raise TreeError(f"KI alias targets itself or an ancestor directory: {entry.relative}")
        if terminal is None:
            raise TreeError(f"KI alias target is missing: {entry.relative} -> {target}")
        # Logical slash normalization is portable, but cannot bless a broken
        # link object on this host. Windows extraction/copy creates native
        # target spelling; POSIX backslashes remain literal filenames.
        alias_path = root / entry.relative
        terminal_path = root / target
        try:
            actual = alias_path.stat()
            canonical = terminal_path.stat()
        except OSError as error:
            raise TreeError(f"KI alias is not traversable on this host: {entry.relative}") from error
        expected_type = stat.S_ISDIR if terminal.kind == "directory" else stat.S_ISREG
        if (not expected_type(actual.st_mode) or not expected_type(canonical.st_mode)
                or not os.path.samestat(actual, canonical)):
            raise TreeError(f"KI alias does not reach its canonical target: {entry.relative}")
        if terminal.kind == "directory":
            parent = PurePosixPath(entry.relative).parent.as_posix()
            directories["" if parent == "." else parent].append(target)
    # Canonical containment edges plus directory alias edges must be acyclic.
    # This also rejects sibling directories that point back into each other.
    indegree = dict.fromkeys(directories, 0)
    for children in directories.values():
        for child in children:
            indegree[child] += 1
    ready = [path for path, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        path = ready.pop()
        visited += 1
        for child in directories[path]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(directories):
        raise TreeError("KI directory aliases form a traversal cycle")
    # Match the preexisting kdtstudio ordering exactly for link-free trees.
    ordered = tuple(sorted(entries.values(), key=lambda item: str(Path(item.relative))))
    return TreeInventory(root, ordered)


def digest(root: Path, *, max_entries: int = MAX_ENTRIES,
           max_bytes: int = MAX_BYTES) -> str | None:
    """Keep legacy plain-tree hashes; bind valid aliases in a separate domain."""
    try:
        inventory = scan(root, max_entries=max_entries, max_bytes=max_bytes)
        value = hashlib.sha256()
        aliases = []
        bytes_read = 0
        for entry in inventory.entries:
            if entry.kind == "link":
                aliases.append([entry.relative, entry.target])
            elif entry.kind == "file":
                value.update(entry.relative.encode("utf-8"))
                value.update(b"\0")
                with (inventory.root / entry.relative).open("rb") as handle:
                    for block in iter(lambda: handle.read(1 << 20), b""):
                        bytes_read += len(block)
                        if bytes_read > max_bytes:
                            raise TreeError(f"candidate is larger than {max_bytes} bytes")
                        value.update(block)
        # Catch ordinary concurrent replacements/edits, including retargeting a
        # link during hashing. This is not an OS sandbox against the same user.
        # NTFS can publish a directory's final write timestamp lazily after a
        # child link was created. Directory names/kinds are part of the scan,
        # but directory timestamps do not describe any hashed bytes.
        def stable(rows):
            return [(row.relative, row.kind, row.size,
                     0 if row.kind == "directory" else row.mtime_ns, row.target)
                    for row in rows]
        after = scan(root, max_entries=max_entries, max_bytes=max_bytes)
        if stable(after.entries) != stable(inventory.entries):
            raise TreeError("KI tree changed while computing its identity")
        if not aliases:
            return value.hexdigest()
        linked = hashlib.sha256(b"\0" + POLICY.encode("ascii") + b"\0")
        linked.update(value.digest())
        linked.update(json.dumps(aliases, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        return linked.hexdigest()
    except (OSError, ValueError, RuntimeError):
        return None


def signature(root: Path, *, max_entries: int = MAX_ENTRIES,
              max_bytes: int = MAX_BYTES) -> list[list[object]] | None:
    """Cheap UI change detector; never an authority substitute for the digest."""
    try:
        inventory = scan(root, max_entries=max_entries, max_bytes=max_bytes)
        return [[entry.relative, entry.size, entry.mtime_ns] if entry.kind == "file"
                else [entry.relative, "link", entry.target, entry.mtime_ns]
                for entry in inventory.entries if entry.kind in {"file", "link"}]
    except (OSError, ValueError, RuntimeError):
        return None
