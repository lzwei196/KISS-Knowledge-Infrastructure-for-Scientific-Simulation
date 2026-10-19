"""Run reviewed data source with accident guards, not an OS security sandbox.

This standalone stdlib worker deliberately has no Desktop imports, credential
transport, provider proxy, shell or model runtime. Source is reviewed/trusted.
"""
from __future__ import annotations

import argparse
import calendar
import collections
import csv
import datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import statistics
import sys
from urllib.parse import unquote, urlsplit, parse_qs


MAX_REQUEST_BYTES = 8 * 1024 * 1024
STDIN_REQUEST_MODE = "--request-stdin-v1"


def read_request():
    """Read bounded host-owned bytes without a command-line length dependency."""
    if len(sys.argv) >= 3 and sys.argv[2] == STDIN_REQUEST_MODE:
        if len(sys.argv) != 4 or not re.fullmatch(r"[0-9a-f]{64}", sys.argv[3]):
            raise ValueError("invalid project data request digest")
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("project data request exceeds the byte limit")
        if hashlib.sha256(raw).hexdigest() != sys.argv[3]:
            raise ValueError("project data request bytes changed in transport")
    else:
        # Retain the small legacy invocation for packaged workers and old hosts.
        if len(sys.argv) != 3:
            raise ValueError("invalid project data worker invocation")
        raw = sys.argv[2].encode("utf-8")
        if len(raw) > 20000:
            raise ValueError("large project data requests require stdin transport")
    request = json.loads(raw.decode("utf-8"))
    if not isinstance(request, dict):
        raise ValueError("project data request must be an object")
    return request


def main():
    request = read_request()
    source = Path(request["source"]).resolve()
    if Path(sys.argv[1]).resolve() != source:
        raise RuntimeError("worker source does not match reviewed invocation")
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != request["source_sha256"]:
        raise RuntimeError("project data source changed before launch")
    code = compile(data, str(source), "exec")
    read_roots = [Path(p).resolve() for p in request["read_roots"]]
    list_roots = [Path(p).resolve() for p in request.get("list_roots", [])]
    non_executable_roots = [Path(p).resolve() for p in request.get("non_executable_roots", [])]
    write_roots = [Path(p).resolve() for p in request["write_roots"]]
    library_roots = [Path(sys.base_prefix).resolve() / "Lib", Path(sys.base_prefix).resolve() / "lib",
                     Path(sys.prefix).resolve() / "Lib", Path(sys.prefix).resolve() / "lib"]
    created = set()
    existing_outputs = {Path(row["path"]).absolute(): row
                        for row in request.get("existing_outputs") or []}

    def under(p, roots):
        return any(p == root or root in p.parents for root in roots)

    def readable(p):
        return p == source or under(p, read_roots + write_roots + library_roots)

    def writable(p):
        # A path granted as raw input stays immutable, even if under outputs/.
        return under(p, write_roots) and not under(p, read_roots)

    def path(raw):
        if isinstance(raw, int):
            raise PermissionError("project data scripts cannot open arbitrary file descriptors")
        return Path(os.fsdecode(raw)).resolve()

    def replacement_matches(p, raw):
        # Resolve neither links nor hardlinks into a granted replacement. The
        # host saved these exact old bytes, and concurrent edits must not be lost.
        literal = Path(os.path.abspath(os.fsdecode(raw)))
        if literal != p or literal.is_symlink() or not p.is_file():
            return False
        for candidate in (literal, *literal.parents):
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                return False
        before = p.stat()
        row = existing_outputs[p]
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size != row["bytes"]):
            return False
        digest = hashlib.sha256()
        with p.open("rb") as stream:
            remaining = row["bytes"]
            while remaining:
                block = stream.read(min(1024 * 1024, remaining))
                if not block:
                    return False
                digest.update(block)
                remaining -= len(block)
            if stream.read(1):
                return False
        after = p.stat()
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        return identity(before) == identity(after) and digest.hexdigest() == row["sha256"]

    def audit(event, args):
        if event.startswith(("socket.", "subprocess.", "ctypes.", "os.exec", "os.spawn")) or event in {
                "os.system", "os.fork", "os.forkpty", "os.posix_spawn", "os.startfile",
                "sqlite3.enable_load_extension", "sqlite3.load_extension"}:
            raise PermissionError("project data tools cannot use network, native processes or native extension loading")
        if event == "open":
            p = path(args[0])
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            if writing:
                if (not writable(p) or (p not in created and (
                        (p in existing_outputs and not replacement_matches(p, args[0]))
                        or (p not in existing_outputs and p.exists())))):
                    raise PermissionError("project data writes require fresh or exact approved preserved output files; raw inputs are immutable")
                created.add(p)
            elif not readable(p):
                raise PermissionError("project data read is outside approved inputs and runtime libraries")
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime", "os.truncate"}:
            p = path(args[0])
            if not writable(p) or (event != "os.mkdir" and p not in created):
                raise PermissionError("project data filesystem change is outside fresh outputs")
        elif event in {"os.rename", "os.link", "os.symlink"}:
            raise PermissionError("project data tools cannot rename/link files; write fresh result files directly")
        elif event in {"os.listdir", "os.scandir"}:
            if not readable(path(args[0] or ".")) and not under(path(args[0] or "."), list_roots):
                raise PermissionError("project data listing is outside approved input directories")
        elif event == "exec" and under(path(args[0].co_filename), non_executable_roots):
            raise PermissionError("reference case grants permit data reads, not KI code execution or imports")
        elif event == "sqlite3.connect":
            uri = str(args[0])
            parsed = urlsplit(uri)
            p = path(unquote(parsed.path))
            # Windows file:///D:/... URI paths need their drive prefix restored.
            if os.name == "nt" and re.match(r"^/[A-Za-z]:", unquote(parsed.path)):
                p = path(unquote(parsed.path)[1:])
            if parsed.scheme != "file" or parsed.netloc or parse_qs(parsed.query).get("mode") != ["ro"] or not under(p, read_roots):
                raise PermissionError("SQLite inputs require an approved file URI with mode=ro")

    # SQLite's native I/O bypasses Python open events. Enforce read-only SQL,
    # including ATTACH and extensions, in addition to URI mode=ro.
    original_connect = sqlite3.connect
    def readonly_connect(*args, **kwargs):
        if kwargs.get("uri") is not True or "factory" in kwargs:
            raise PermissionError("SQLite readers must connect with uri=True and no custom factory")
        connection = original_connect(*args, **kwargs)
        connection.execute("PRAGMA query_only=ON")
        denied = {getattr(sqlite3, name) for name in (
            "SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_DELETE", "SQLITE_ATTACH", "SQLITE_DETACH",
            "SQLITE_CREATE_TABLE", "SQLITE_CREATE_INDEX", "SQLITE_CREATE_TRIGGER", "SQLITE_CREATE_VIEW",
            "SQLITE_DROP_TABLE", "SQLITE_DROP_INDEX", "SQLITE_DROP_TRIGGER", "SQLITE_DROP_VIEW", "SQLITE_ALTER_TABLE")}
        def authorize(action, arg1, arg2, db, trigger):
            if action in denied or (action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() == "load_extension"):
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_PRAGMA and arg2 is not None and not (
                    str(arg1).lower() in {"table_info", "table_xinfo", "index_info", "index_xinfo", "index_list", "foreign_key_list"}
                    or (str(arg1).lower() in {"quick_check", "integrity_check"} and str(arg2).isdigit() and 1 <= int(arg2) <= 100)
                    or (str(arg1).lower() == "query_only" and str(arg2).lower() in {"on", "1", "true"})):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        connection.set_authorizer(authorize)
        return connection
    sqlite3.connect = readonly_connect
    sys.addaudithook(audit)
    sys.argv = [str(source), *request["arguments"]]
    exec(code, {"__name__": "__main__", "__file__": str(source), "__package__": None})


if __name__ == "__main__":
    main()
