#!/usr/bin/env python3
"""Apply narrow stdio/backtrace portability repairs to official VIC sources.

This is not a compiler installer or a model runner. It preserves model physics,
parameters, forcing values, and source version metadata. The caller must retain
the official checkout revision, build it with a real compiler, and run a case.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


INPUT_OLD = "    fflush(gp);\n    start_position = ftell(gp);"
INPUT_NEW = """    // GeoForge Windows portability: flushing an input stream discards unread
    // bytes in the Microsoft CRT. Preserve the cursor before look-ahead reads.
#ifndef _WIN32
    fflush(gp);
#endif
    start_position = ftell(gp);"""
TRACE_OLD = """    for (i = size - 2; i > 0; i--) {
        fprintf(LOG_DEST, "%s\\n", strings[i]);
    }"""
TRACE_NEW = """    // GeoForge portability: a platform without backtrace support may return
    // zero frames or NULL symbols. Do not underflow size_t or hide the error.
    if (strings != NULL && size > 2) {
        for (i = size - 2; i > 0; i--) {
            fprintf(LOG_DEST, "%s\\n", strings[i]);
        }
    }"""
LINE_OLD = r"cmdstr[0] != '#' && cmdstr[0] != '\n' && cmdstr[0] != '\0'"
LINE_NEW = r"cmdstr[0] != '#' && cmdstr[0] != '\n' && cmdstr[0] != '\r' && cmdstr[0] != '\0'"
GLOBAL_OLD = '    filep.globalparam = open_file(filenames.global, "r");'
GLOBAL_NEW = '''    // Binary mode preserves exact seek offsets for both LF and CRLF config.
    filep.globalparam = open_file(filenames.global, "rb");'''
PATCHES = (
    ("vic/drivers/shared_all/src/forcing_utils.c", ((INPUT_OLD, INPUT_NEW, 1), (LINE_OLD, LINE_NEW, 1))),
    ("vic/drivers/shared_all/src/input_tools.c", ((INPUT_OLD, INPUT_NEW, 1), (LINE_OLD, LINE_NEW, 1))),
    ("vic/drivers/shared_all/src/vic_log.c", ((TRACE_OLD, TRACE_NEW, 1),)),
    ("vic/drivers/classic/src/vic_classic.c", ((GLOBAL_OLD, GLOBAL_NEW, 2),)),
    ("vic/drivers/classic/src/get_global_param.c", ((LINE_OLD, LINE_NEW, 1),)),
    ("vic/drivers/classic/src/parse_output_info.c", ((LINE_OLD, LINE_NEW, 1),)),
)


def apply(source_root: Path, *, check_only: bool = False) -> dict:
    """Validate every target before editing; reject source drift and escapes."""
    root = Path(source_root).resolve(strict=True)
    changes = []
    pending = []
    for relative, edits in PATCHES:
        path = root / relative
        resolved = path.resolve(strict=True)
        if path.is_symlink() or not resolved.is_relative_to(root):
            raise ValueError(f"source file must stay within the checkout: {relative}")
        before = path.read_bytes()
        text = before.decode("utf-8")
        newline = "\r\n" if "\r\n" in text else "\n"
        normalized = text.replace("\r\n", "\n")
        changed = False
        for old, new, expected in edits:
            if normalized.count(new) == expected and normalized.count(old) == 0:
                continue
            if normalized.count(old) != expected or normalized.count(new) != 0:
                raise ValueError(f"unrecognized upstream source at {relative}; inspect it before patching")
            normalized = normalized.replace(old, new)
            changed = True
        status = ("would_patch" if check_only else "patched") if changed else "already_patched"
        after = normalized.replace("\n", newline).encode("utf-8") if changed else before
        if changed:
            pending.append((path, after))
        changes.append({"path": relative, "status": status,
                        "before_sha256": hashlib.sha256(before).hexdigest(),
                        "after_sha256": hashlib.sha256(after).hexdigest()})
    if not check_only:
        for path, contents in pending:
            path.write_bytes(contents)
    return {"source_root": str(root), "check_only": check_only,
            "scope": "Config seek offsets, LF/CRLF config reading, input-stream cursor preservation, safe diagnostic backtrace",
            "scientific_parameters_or_algorithms_changed": False, "files": changes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--check", action="store_true", help="validate compatibility without writing")
    parser.add_argument("--report", type=Path, help="optional JSON before/after hash record")
    args = parser.parse_args()
    try:
        result = apply(args.source_root, check_only=args.check)
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(1, f"VIC portability patch refused: {error}\n")
    rendered = json.dumps(result, indent=2) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
