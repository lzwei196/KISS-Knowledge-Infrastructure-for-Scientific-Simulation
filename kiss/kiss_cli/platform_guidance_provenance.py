"""Authenticate selected Windows guidance, without enrolling any source KI.

The official HTTPS commit response anchors a Git tree. Local Git objects are
only a byte store: their hashes and each path's tree membership are verified.
The resulting host receipt attests to these inputs, not an entire checkout.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path, PurePosixPath

from . import ki_platform_overlay, published_acceptance, published_kdt

POLICY = "official-windows-guidance-inputs-v1"
SCOPE = "official_windows_guidance_inputs"
SOURCE_URL = ("https://api.github.com/repos/lzwei196/"
              "KISS---Knowledge-Infrastructure-for-Scientific-Simulation/commits/windows-version")
MAX_INPUTS = 512
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_OBJECT_BYTES = 4 * 1024 * 1024
MAX_OBJECT_TOTAL_BYTES = 32 * 1024 * 1024


class GuidanceProvenanceError(ValueError):
    """Selected local guidance has no current, exact official-source binding."""


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()


def _implementation() -> str:
    return published_kdt._module_identity(sys.modules[__name__])


def _allowed(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if (not path or "\\" in path or ":" in path or PurePosixPath(path).is_absolute()
            or any(part in ("", ".", "..") for part in parts)
            or PurePosixPath(path).as_posix() != path):
        return False
    if len(parts) == 3 and parts[:2] == ("kiss", "manifests"):
        return parts[2].endswith(".yaml")
    if len(parts) == 4 and parts[0] == "models":
        return parts[2:] == ("docs", "install.windows.md")
    if len(parts) == 3 and parts[0] == "models":
        return parts[2] == "kiss.yaml" or bool(re.fullmatch(
            r"kiss\.windows(?:\.[A-Za-z0-9_-]+)?\.yaml", parts[2]))
    return False


def _inputs(root: Path, overlay: dict) -> tuple[dict, dict]:
    records = {}
    rows = overlay.get("files") if isinstance(overlay, dict) else None
    if not isinstance(rows, list) or not rows:
        raise GuidanceProvenanceError("No selected platform guidance inputs")
    for row in rows:
        if not isinstance(row, dict):
            raise GuidanceProvenanceError("Invalid platform overlay record")
        for key in ("source", "base_generic", "excluded_platform_duplicate"):
            record = row.get(key)
            if record is None:
                if key == "source":
                    raise GuidanceProvenanceError("Platform overlay source record is missing")
                continue
            if not isinstance(record, dict):
                raise GuidanceProvenanceError("Invalid platform guidance input record")
            name = record.get("path")
            if (not isinstance(name, str) or not _allowed(name)
                    or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))
                    or type(record.get("bytes")) is not int or record["bytes"] < 0):
                raise GuidanceProvenanceError("Platform guidance input is outside the allowed metadata paths")
            selected = {k: record[k] for k in ("path", "sha256", "bytes")}
            if name in records and records[name] != selected:
                raise GuidanceProvenanceError("Conflicting hashes for a selected guidance input")
            records[name] = selected
    if len(records) > MAX_INPUTS:
        raise GuidanceProvenanceError("Too many selected guidance inputs")
    bodies, total = {}, 0
    for name, record in sorted(records.items()):
        try:
            body = ki_platform_overlay._read(root, root.joinpath(*PurePosixPath(name).parts))
            body.decode("utf-8")
        except (OSError, UnicodeError, ValueError) as error:
            raise GuidanceProvenanceError(f"Cannot read selected guidance {name}: {error}") from error
        total += len(body)
        if total > MAX_TOTAL_BYTES:
            raise GuidanceProvenanceError("Selected guidance exceeds the total byte limit")
        if len(body) != record["bytes"] or hashlib.sha256(body).hexdigest() != record["sha256"]:
            raise GuidanceProvenanceError(f"Selected guidance changed: {name}")
        bodies[name] = body
    return records, bodies


def _git(root: Path, *args: str) -> bytes:
    executable = shutil.which("git")
    if not executable:
        raise GuidanceProvenanceError("Git is required to authenticate development-checkout guidance")
    try:
        result = subprocess.run([executable, "--no-replace-objects", "-C", str(root), *args],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                                check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GuidanceProvenanceError("Cannot read the official guidance Git objects") from error
    if result.returncode:
        raise GuidanceProvenanceError("Official guidance Git object is unavailable locally")
    return result.stdout


def has_git_object_store(root: Path) -> bool:
    """Identify a local Git byte store; this grants no source trust."""
    try:
        return bool(_git(Path(root), "rev-parse", "--git-dir").strip())
    except GuidanceProvenanceError:
        return False


class _Objects:
    def __init__(self, root):
        self.root = root
        self.cache = {}
        self.total = 0

    def read(self, kind, oid):
        if not isinstance(oid, str) or not re.fullmatch(r"[0-9a-f]{40}", oid):
            raise GuidanceProvenanceError("Invalid official Git object identity")
        key = kind, oid
        if key not in self.cache:
            # Transport/object-store failures are already meaningful provenance
            # errors. Only conversion of a successful size response belongs in
            # this handler (GuidanceProvenanceError itself subclasses ValueError).
            raw_size = _git(self.root, "cat-file", "-s", oid).strip()
            try:
                size = int(raw_size)
            except ValueError as error:
                raise GuidanceProvenanceError("Invalid Git object size") from error
            if not 0 <= size <= MAX_OBJECT_BYTES:
                raise GuidanceProvenanceError("Official guidance Git object exceeds the byte limit")
            if self.total + size > MAX_OBJECT_TOTAL_BYTES:
                raise GuidanceProvenanceError("Official guidance Git objects exceed the total byte limit")
            body = _git(self.root, "cat-file", kind, oid)
            calculated = hashlib.sha1(kind.encode() + b" " + str(len(body)).encode() + b"\0" + body).hexdigest()
            if len(body) != size or calculated != oid:
                raise GuidanceProvenanceError("Local Git object bytes do not match their official identity")
            self.cache[key] = body
            self.total += len(body)
        return self.cache[key]

    def blob_at(self, tree_oid, relative):
        parts = PurePosixPath(relative).parts
        for number, wanted in enumerate(parts):
            raw = self.read("tree", tree_oid)
            pos, entries = 0, {}
            while pos < len(raw):
                try:
                    end = raw.index(b"\0", pos)
                    mode, name = raw[pos:end].split(b" ", 1)
                    name = name.decode("utf-8")
                    oid = raw[end + 1:end + 21]
                except (ValueError, UnicodeError) as error:
                    raise GuidanceProvenanceError("Malformed official Git tree") from error
                if len(oid) != 20 or name in entries or "/" in name or name in (".", ".."):
                    raise GuidanceProvenanceError("Malformed or duplicate official Git tree entry")
                entries[name] = mode, oid.hex()
                pos = end + 21
            if wanted not in entries:
                raise GuidanceProvenanceError(f"Selected guidance is absent from official Windows source: {relative}")
            mode, oid = entries[wanted]
            if number == len(parts) - 1:
                if mode not in (b"100644", b"100755"):
                    raise GuidanceProvenanceError(f"Official guidance must be a regular file: {relative}")
                return oid, self.read("blob", oid)
            if mode != b"40000":
                raise GuidanceProvenanceError(f"Official guidance path contains a link or non-directory: {relative}")
            tree_oid = oid


def require_current(root: Path, overlay: dict, evidence: dict) -> dict:
    """Validate only this signed guidance-input proof; never enroll a KI."""
    root = Path(root).resolve()
    records, _ = _inputs(root, overlay)
    if (not published_acceptance._authentic(root, evidence)
            or evidence.get("scope") != SCOPE or evidence.get("policy") != POLICY
            or evidence.get("source_url") != SOURCE_URL
            or evidence.get("root") != str(root)
            or evidence.get("implementation") != _implementation()
            or evidence.get("inputs") != records):
        raise GuidanceProvenanceError("Selected guidance has no current authentic source proof")
    return evidence


def authenticate(root: Path, overlay: dict, *, request_json, object_root: Path | None = None) -> dict:
    """One official request on a cache miss; selected bytes are always rechecked.

    ``request_json`` is the updater's existing verified HTTPS transport. The
    caller cannot select a URL/branch/repository. A cached signed proof of an
    immutable official commit remains useful when the remote branch advances.
    ``object_root`` is only an untrusted Git byte store for unpacked snapshots;
    every object and selected path still must match the official tree. Selected
    input bytes, the signed proof and cache identity always belong to ``root``.
    """
    root = Path(root).resolve()
    records, bodies = _inputs(root, overlay)
    implementation = _implementation()
    key = _hash({"root": str(root), "inputs": records, "implementation": implementation})[:24]
    cache = published_acceptance._authority(root) / "guidance-provenance" / f"{key}.json"
    if cache.is_file():
        try:
            return require_current(root, overlay, json.loads(cache.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as error:
            # Do not silently replace altered signed evidence with a new proof.
            raise GuidanceProvenanceError("Cached guidance provenance is invalid") from error
    store = Path(object_root).resolve() if object_root is not None else root
    if not has_git_object_store(store):
        raise GuidanceProvenanceError(
            "Cannot authenticate retained Windows guidance: no local Git object store is available. "
            "Use a complete GeoForge source checkout containing the official Windows Git objects, "
            "or restore this snapshot's authenticated guidance proof.")
    try:
        official = request_json(SOURCE_URL)
        commit = official["sha"]
        tree = official["commit"]["tree"]["sha"]
    except Exception as error:
        raise GuidanceProvenanceError("Cannot authenticate the official Windows guidance commit") from error
    if any(not isinstance(oid, str) or not re.fullmatch(r"[0-9a-f]{40}", oid) for oid in (commit, tree)):
        raise GuidanceProvenanceError("Official Windows response has no exact commit/tree identity")
    objects, proofs = _Objects(store), []
    for name, body in sorted(bodies.items()):
        oid, original = objects.blob_at(tree, name)
        try:
            original.decode("utf-8")
        except UnicodeError as error:
            raise GuidanceProvenanceError(f"Official guidance is not UTF-8 text: {name}") from error
        if body == original:
            transform = "exact_bytes"
        elif body.replace(b"\r\n", b"\n") == original.replace(b"\r\n", b"\n"):
            transform = "crlf_lf_only"
        else:
            raise GuidanceProvenanceError(f"Selected guidance differs from official Windows source: {name}")
        proofs.append({"path": name, "blob_sha1": oid,
                       "official_sha256": hashlib.sha256(original).hexdigest(),
                       "input_sha256": records[name]["sha256"], "transform": transform})
    if _implementation() != implementation or _inputs(root, overlay)[0] != records:
        raise GuidanceProvenanceError("Guidance or its verifier changed during authentication")
    evidence = published_acceptance._sign(root, {
        "scope": SCOPE, "policy": POLICY, "root": str(root),
        "source_url": SOURCE_URL, "source_commit": commit, "source_tree": tree,
        "implementation": implementation, "inputs": records, "files": proofs,
        "whole_ki_trusted": False, "authoring_verification": False,
        "native_regression": "not_run"})
    require_current(root, overlay, evidence)
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_name(f".{uuid.uuid4().hex[:12]}.tmp")
    try:
        temporary.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, cache)
    finally:
        temporary.unlink(missing_ok=True)
    return evidence
