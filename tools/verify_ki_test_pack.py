#!/usr/bin/env python3
"""Verify an extracted KI input pack against its published member manifest.

This checks byte delivery only, not scientific suitability or native execution.
Obtain the manifest/ZIP SHA-256 from a trusted pack index before using this check.
No extraction, download, engine invocation or modification of the pack occurs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

SELF_FILES = {"member-manifest.json", "SHA256SUMS.txt"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def verify(pack: Path) -> dict:
    pack = Path(pack).resolve()
    errors = []
    result = {"pack": pack.name, "status": "FAIL", "checked_members": 0,
              "errors": errors, "scientific_validity": "NOT_CHECKED",
              "native_run": "NOT_RUN"}
    try:
        manifest_path = pack / "member-manifest.json"
        if manifest_path.is_symlink():
            raise ValueError("manifest must be a regular file, not a symlink")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
            raise ValueError("unsupported member manifest schema")
        members = manifest.get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("manifest needs a nonempty member list")
        excluded = manifest.get("excluded_self_references", [])
        if not isinstance(excluded, list) or any(x not in SELF_FILES for x in excluded):
            raise ValueError("only the manifest and SHA256SUMS.txt may exclude themselves")
    except (OSError, ValueError, TypeError) as error:
        errors.append("manifest: " + str(error))
        return result

    expected, folded = set(), set()
    for member in members:
        try:
            if not isinstance(member, dict):
                raise ValueError("member must be an object")
            name = member.get("path")
            if (not isinstance(name, str) or not name or "\\" in name or ":" in name
                    or name.startswith("/") or any(p in ("", ".", "..") for p in name.split("/"))
                    or any(p.rstrip(" .") != p for p in name.split("/"))):
                raise ValueError("invalid portable member path")
            if name in SELF_FILES or name.casefold() in folded:
                raise ValueError("self reference or duplicate member path")
            expected.add(name)
            folded.add(name.casefold())
            size, checksum = member.get("bytes"), member.get("sha256")
            if type(size) is not int or size < 0 or not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
                raise ValueError("member needs nonnegative bytes and lowercase SHA-256")
            relative = PurePosixPath(name)
            path = pack.joinpath(*relative.parts)
            if any(pack.joinpath(*relative.parts[:i]).is_symlink() for i in range(1, len(relative.parts) + 1)):
                raise ValueError("symlink member or parent")
            if not path.resolve().is_relative_to(pack):
                raise ValueError("member escapes pack")
            if path.stat().st_size != size or digest(path) != checksum:
                raise ValueError("byte size or SHA-256 mismatch")
            result["checked_members"] += 1
        except (OSError, ValueError, TypeError) as error:
            errors.append(f"{member.get('path', '<unnamed>') if isinstance(member, dict) else '<invalid>'}: {error}")
    for path in sorted(pack.rglob("*")):
        name = path.relative_to(pack).as_posix()
        if path.is_symlink():
            errors.append(f"{name}: symlinks are not pack members")
        elif path.is_file() and name not in expected and name not in SELF_FILES:
            errors.append(f"{name}: unexpected file")
    if not errors:
        result["status"] = "PASS"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path, help="Extracted directory containing member-manifest.json")
    args = parser.parse_args()
    result = verify(args.pack)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
