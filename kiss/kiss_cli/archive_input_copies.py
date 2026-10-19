"""Bounded host byte-equivalence evidence for members of approved input archives.

No extraction, code execution, format conversion or scientific validation occurs
here. The pre-launch input capture is supplied by the host, never tool arguments.
"""
from __future__ import annotations

import gzip
import hashlib
import os
import re
import stat
import struct
import tarfile
import unicodedata
import zipfile
import zlib
from pathlib import Path

MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_MEMBER_BYTES = 512 * 1024**2
MAX_TOTAL_BYTES = 4 * 1024**3
MAX_ENTRIES = 20_000
MAX_METADATA_BYTES = 1024**2
MAX_METADATA_TOTAL = 8 * 1024**2
MAX_METADATA_HEADERS = 2048
MAX_ZIP_DIRECTORY_BYTES = 16 * 1024**2
CHUNK = 1024**2
# The host filesystem determines naming semantics; no tool/plan argument can
# select a more permissive parser. Bound Linux workspaces use native storage.
_WINDOWS_NAMES = os.name == "nt"


def _ordinary(project: Path, path: Path) -> None:
    if not path.is_relative_to(project) or path == project:
        raise ValueError("archive input must be an explicitly granted project file")
    for parent in [path, *path.parents]:
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("archive input cannot traverse a link or reparse point")
        if parent == path:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("archive input must be an ordinary unshared file")
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError("archive input parent must be an ordinary directory")
        if parent == project:
            break


def _hash(stream, limit: int, *, expansion=None) -> tuple[int, str]:
    size, digest = 0, hashlib.sha256()
    while block := stream.read(min(CHUNK, limit - size + 1)):
        size += len(block)
        if size > limit:
            raise ValueError("archive copy exceeds the bounded byte limit")
        if expansion is not None:
            expansion.consume(len(block))
        digest.update(block)
    return size, digest.hexdigest()


class _Budget:
    def __init__(self):
        self.entries = self.bytes = 0
        self.stream_bytes = self.source_bytes = 0

    def consume(self, size):
        self.stream_bytes += size
        if self.stream_bytes > MAX_TOTAL_BYTES + MAX_ZIP_DIRECTORY_BYTES:
            raise ValueError("archive streams exceed the aggregate decompressed byte limit")

    def member(self, size: int):
        self.entries += 1
        if self.entries > MAX_ENTRIES:
            raise ValueError(f"archive copy exceeds {MAX_ENTRIES} entries; approve a smaller input archive")
        if size < 0 or size > MAX_MEMBER_BYTES:
            raise ValueError(f"archive member exceeds {MAX_MEMBER_BYTES} bytes; approve a smaller input archive")
        self.bytes += size
        if self.bytes > MAX_TOTAL_BYTES:
            raise ValueError(f"archive copy exceeds {MAX_TOTAL_BYTES} decompressed bytes; approve smaller inputs")


class _LimitedReader:
    def __init__(self, stream, budget):
        self.stream, self.budget = stream, budget

    def read(self, size=-1):
        # Include TAR headers/padding and gzip expansion, not only file payloads.
        limit = MAX_TOTAL_BYTES + MAX_ZIP_DIRECTORY_BYTES
        size = min(size if size >= 0 else CHUNK, limit - self.budget.stream_bytes + 1)
        block = self.stream.read(size)
        self.budget.consume(len(block))
        return block


class _BoundedTarInfo(tarfile.TarInfo):
    @classmethod
    def frombuf(cls, buf, encoding, errors):
        # stdlib strips directory slashes, which would hide a raw '/' entry.
        if len(buf) == 512 and (buf[:100].startswith(b"/") or buf[345:500].startswith(b"/")):
            raise ValueError("absolute TAR member paths are unsupported")
        return super().frombuf(buf, encoding, errors)

    def _apply_pax_info(self, values, encoding, errors):
        _pax_bound(values)
        if str(values.get("path", "")).startswith("/") or any(k.startswith("GNU.sparse") for k in values):
            raise ValueError("absolute/sparse PAX member paths are unsupported")
        return super()._apply_pax_info(values, encoding, errors)

    def _proc_gnusparse_00(self, *args):
        raise ValueError("sparse PAX members are unsupported")

    _proc_gnusparse_01 = _proc_gnusparse_00
    _proc_gnusparse_10 = _proc_gnusparse_00

    def _proc_gnulong(self, archive):
        original = archive.fileobj
        class Guard:
            first = True
            def read(self, size):
                data = original.read(size)
                if self.first:
                    self.first = False
                    if data.startswith(b"/"):
                        raise ValueError("absolute GNU long-name member paths are unsupported")
                return data
            def __getattr__(self, name):
                return getattr(original, name)
        archive.fileobj = Guard()
        try:
            return super()._proc_gnulong(archive)
        finally:
            archive.fileobj = original

    def _proc_member(self, archive):
        # Bound extension metadata before stdlib allocates a long-name/PAX body.
        if self.type in (tarfile.GNUTYPE_SPARSE, tarfile.GNUTYPE_LONGLINK):
            raise ValueError("sparse/link TAR members are unsupported")
        if self.type in (tarfile.GNUTYPE_LONGNAME, tarfile.XHDTYPE,
                         tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE):
            if self.size < 0 or self.size > MAX_METADATA_BYTES:
                raise ValueError("TAR member metadata exceeds the bounded byte limit")
            archive._copy_metadata_bytes = getattr(archive, "_copy_metadata_bytes", 0) + self.size
            archive._copy_metadata_headers = getattr(archive, "_copy_metadata_headers", 0) + 1
            if (archive._copy_metadata_bytes > MAX_METADATA_TOTAL
                    or archive._copy_metadata_headers > MAX_METADATA_HEADERS):
                raise ValueError("TAR extension metadata exceeds the aggregate limit")
        archive._copy_metadata_depth = getattr(archive, "_copy_metadata_depth", 0) + 1
        try:
            if archive._copy_metadata_depth > 16:
                raise ValueError("TAR extension metadata nesting exceeds the limit")
            result = super()._proc_member(archive)
            for values in (archive.pax_headers, result.pax_headers if result else {}):
                _pax_bound(values)
            # Relevant name/size/type/sparse information has already been applied.
            # Do not retain a copied global PAX dictionary on every member.
            if result is not None:
                result.pax_headers = {}
            return result
        finally:
            archive._copy_metadata_depth -= 1


def _pax_bound(values):
    if (len(values) > 64 or any(len(k) > 128 or len(v) > 4096 for k, v in values.items())
            or sum(len(k) + len(v) for k, v in values.items()) > 8192):
        raise ValueError("TAR PAX metadata exceeds the bounded key/value limit")


def _member_name(raw: str, directory: bool) -> str:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 4096:
        raise ValueError("archive member name exceeds the bounded length")
    if raw.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in raw) or "\\" in raw:
        raise ValueError("unsafe archive member name")
    while raw.startswith("./"):
        raw = raw[2:]
    if re.match(r"^[A-Za-z]:", raw):
        raise ValueError("archive member cannot use a drive path")
    if _WINDOWS_NAMES and ":" in raw:
        raise ValueError("archive member colon is unsupported by Windows paths")
    if directory:
        raw = raw.rstrip("/")
    if directory and raw in ("", "."):
        return ""  # A harmless archive-root directory, never a file grant.
    parts = raw.split("/")
    if len(parts) > 64 or any(p in ("", ".", "..") or p.endswith((".", " "))
                              or len(p.encode("utf-8")) > 255 for p in parts):
        raise ValueError("unsafe or ambiguous archive member path")
    if any(re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p) for p in parts):
        raise ValueError("archive member uses a nonportable reserved path")
    return unicodedata.normalize("NFC", raw)


def _register(names: dict, raw: str, directory: bool) -> str:
    name = _member_name(raw, directory)
    key = name.casefold()
    if key in names:
        raise ValueError("archive contains duplicate or ambiguous member names")
    names[key] = directory
    return name


def _check_parents(names: dict):
    for key in names:
        parts = key.split("/")
        for index in range(1, len(parts)):
            if names.get("/".join(parts[:index])) is False:
                raise ValueError("archive member path conflicts with a regular file")


def _tar(path: Path, budget: _Budget) -> list[dict]:
    rows, names = [], {}
    with path.open("rb") as source:
        compressed = path.name.lower().endswith((".tar.gz", ".tgz"))
        stream = gzip.GzipFile(fileobj=source) if compressed else source
        try:
            limited = _LimitedReader(stream, budget)
            with tarfile.open(fileobj=limited, mode="r|", tarinfo=_BoundedTarInfo) as archive:
                for member in archive:
                    if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE) or member.sparse is not None:
                        raise ValueError("archive contains links, sparse files or special members")
                    if member.isdir() and member.size != 0:
                        raise ValueError("archive directory has a payload")
                    budget.member(member.size)
                    name = _register(names, member.name, member.isdir())
                    if member.isfile():
                        with archive.extractfile(member) as content:
                            size, digest = _hash(content, min(MAX_MEMBER_BYTES, member.size))
                        if size != member.size:
                            raise ValueError("archive member size differs from its actual bytes")
                        rows.append({"member": member.name, "normalized_member": name,
                                     "bytes": size, "sha256": digest})
                # Do not accept a second hidden archive or data after TAR EOF.
                while tail := archive.fileobj.read(CHUNK):
                    if any(tail):
                        raise ValueError("archive has non-padding data after TAR EOF")
        finally:
            if compressed:
                stream.close()
    _check_parents(names)
    return rows


def _zip_directory_bound(path: Path):
    with path.open("rb") as stream:
        size = path.stat().st_size
        stream.seek(max(0, size - 65557))
        tail = stream.read(65557)
    offset = tail.rfind(b"PK\x05\x06")
    if offset < 0 or len(tail) - offset < 22:
        raise ValueError("ZIP end directory is missing")
    _, disk, start_disk, here, count, length, start, comment = struct.unpack_from("<4s4H2LH", tail, offset)
    if disk or start_disk or here != count or count == 65535 or length == 0xffffffff or start == 0xffffffff:
        raise ValueError("multi-disk/ZIP64 archives are unsupported by bounded input copying")
    if count > MAX_ENTRIES or length > MAX_ZIP_DIRECTORY_BYTES:
        raise ValueError("ZIP directory exceeds the bounded entry/metadata limit")
    if offset + 22 + comment != len(tail) or start + length != size - len(tail) + offset:
        raise ValueError("ZIP directory is ambiguous or has an unsupported preamble")
    # EOCD's declared entry count is not authoritative: ZipFile parses all
    # central records. Check actual record boundaries/count before allocation.
    with path.open("rb") as stream:
        stream.seek(start)
        used = actual = 0
        while used < length:
            header = stream.read(46)
            if len(header) != 46 or header[:4] != b"PK\x01\x02":
                raise ValueError("ZIP central directory is malformed")
            name_size, extra_size, comment_size = struct.unpack_from("<3H", header, 28)
            used += 46 + name_size + extra_size + comment_size
            actual += 1
            if used > length or actual > MAX_ENTRIES:
                raise ValueError("ZIP actual central-directory entry count/size exceeds its limit")
            stream.seek(name_size + extra_size + comment_size, 1)
        if used != length or actual != count:
            raise ValueError("ZIP declared and actual central-directory entry counts differ")


def _zip(path: Path, budget: _Budget) -> list[dict]:
    _zip_directory_bound(path)  # Before ZipFile allocates the central directory.
    rows, names = [], {}
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            mode = member.external_attr >> 16
            directory = member.is_dir()
            kind = stat.S_IFMT(mode)
            if (member.flag_bits & 1 or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    or kind not in (0, stat.S_IFDIR if directory else stat.S_IFREG)):
                raise ValueError("ZIP contains encrypted, linked, special or unsupported compressed members")
            if member.orig_filename != member.filename or (directory and member.file_size):
                raise ValueError("ZIP contains an ambiguous name or directory payload")
            budget.member(member.file_size)
            name = _register(names, member.filename, directory)
            if not directory:
                with archive.open(member) as content:
                    size, digest = _hash(content, min(MAX_MEMBER_BYTES, member.file_size), expansion=budget)
                if size != member.file_size:
                    raise ValueError("archive member size differs from its actual bytes")
                rows.append({"member": member.filename, "normalized_member": name,
                             "bytes": size, "sha256": digest})
    _check_parents(names)
    return rows


class ArchiveCopies:
    """One validation-call cache; all archive members are checked before matching."""
    def __init__(self, project: Path, input_files: list[str], snapshot: dict | None):
        self.project = Path(project).resolve()
        self.inputs, self.snapshot = input_files, snapshot or {}
        self.cache, self.budget = {}, _Budget()

    def _load(self, path):
        _ordinary(self.project, path)
        relative = path.relative_to(self.project).as_posix()
        rows = [row for row in self.snapshot.get("inputs", []) if row.get("path") == relative]
        if (len(rows) != 1 or relative not in self.snapshot.get("input_coverage", {}).get("files", [])
                or type(rows[0].get("bytes")) is not int or rows[0]["bytes"] <= 0
                or not re.fullmatch("[0-9a-f]{64}", str(rows[0].get("sha256", "")))):
            raise ValueError("archive copy requires the exact approved pre-launch input SHA-256 and size")
        if rows[0]["bytes"] > MAX_ARCHIVE_BYTES:
            raise ValueError(f"approved archive exceeds {MAX_ARCHIVE_BYTES} bytes; approve a smaller input archive")
        self.budget.source_bytes += rows[0]["bytes"]
        if self.budget.source_bytes > MAX_TOTAL_BYTES:
            raise ValueError("approved archives exceed the aggregate source byte limit; approve smaller inputs")
        expected = (rows[0]["bytes"], rows[0]["sha256"])
        with path.open("rb") as stream:
            before = _hash(stream, MAX_ARCHIVE_BYTES)
        if before != expected:
            raise ValueError("approved archive input changed since pre-launch capture")
        try:
            members = (_zip if path.suffix.lower() == ".zip" else _tar)(path, self.budget)
        except (tarfile.TarError, zipfile.BadZipFile, EOFError, RuntimeError, zlib.error) as exc:
            raise ValueError("cannot validate complete input archive: " + str(exc)) from exc
        _ordinary(self.project, path)
        with path.open("rb") as stream:
            after = _hash(stream, MAX_ARCHIVE_BYTES)
        if after != expected:
            raise ValueError("approved archive input changed during member validation")
        return relative, expected, members

    def require_current(self):
        """Recheck each cached source once at final validation, never re-decompress."""
        for path, value in self.cache.items():
            if isinstance(value, Exception):
                continue  # Its output check already failed; never promote it.
            _ordinary(self.project, path)
            with path.open("rb") as stream:
                current = _hash(stream, MAX_ARCHIVE_BYTES)
            if current != value[1]:
                raise ValueError("approved archive input changed before output validation completed")

    def match(self, size: int, digest: str, *, output: Path | None = None) -> dict | None:
        matches = []
        for raw in sorted(set(self.inputs)):
            path = Path(raw).absolute()
            if not path.name.lower().endswith((".tar", ".tar.gz", ".tgz", ".zip")):
                continue
            if path not in self.cache:
                try:
                    self.cache[path] = self._load(path)
                except (OSError, ValueError) as exc:
                    self.cache[path] = exc
            if isinstance(self.cache[path], Exception):
                raise ValueError(str(self.cache[path]))
            relative, expected, members = self.cache[path]
            for member in members:
                if (member["bytes"], member["sha256"]) == (size, digest):
                    if size == 0:
                        if output is None:
                            continue
                        output_parts = Path(output).absolute().relative_to(self.project).parts
                        member_parts = tuple(member["normalized_member"].split("/"))
                        if output_parts[-len(member_parts):] != member_parts:
                            continue
                    matches.append({"scope": "unchanged_archive_member_copy",
                        "preparation_scope": "input_preparation_only", "scientific_validation": "not_performed",
                        "source": relative, "source_sha256": expected[1], "source_bytes": expected[0],
                        **member})
        # Equal content at different safe names proves equivalence to each;
        # choose a deterministic exact witness, not an inferred extraction path.
        if size == 0 and len(matches) != 1:
            return None  # Empty hashes alone cannot select an ancillary member.
        return min(matches, key=lambda row: (row["source"], row["member"])) if matches else None
