"""Immutable, authenticated raw Windows metadata; never a trusted model KI.

An official HTTPS commit anchors a Git tree. Git is an optional byte cache.
Packaged installations can reconstruct that tree from one bounded recursive
response and obtain only selected metadata from immutable HTTPS raw URLs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from . import ki_platform_overlay, ki_tree, platform_guidance_provenance as provenance
from . import published_acceptance, published_kdt

POLICY = "raw-official-windows-guidance-v1"
SCOPE = "raw_official_windows_guidance"
REPOSITORY = published_acceptance.REPOSITORY
SOURCE_URL = provenance.SOURCE_URL
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
RAW_ROOT = f"https://raw.githubusercontent.com/{REPOSITORY}"
MANIFEST = ".geoforge-windows-guidance.json"
MAX_MODELS = 512
MAX_FILES = 1024
MAX_TREE_ENTRIES = 100_000
MAX_TREE_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = ki_platform_overlay.MAX_GUIDANCE_BYTES
MAX_PROOF_BYTES = 2 * 1024 * 1024


class RawGuidanceError(ValueError):
    """Raw guidance is unavailable, unsafe, changed or unauthenticated."""


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()


def _implementation():
    return _hash({"raw": published_kdt._module_identity(sys.modules[__name__]),
                  "objects": provenance._implementation(),
                  "tree": published_kdt._module_identity(ki_tree)})


def _oid(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _name(value):
    return (isinstance(value, str) and 0 < len(value) <= 180
            and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", value) is not None
            and not value.endswith(".")
            and value.split(".", 1)[0].upper() not in
                {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                 *(f"LPT{i}" for i in range(1, 10))})


def _git_hash(kind, body):
    return hashlib.sha1(kind.encode() + b" " + str(len(body)).encode() + b"\0" + body).hexdigest()


def _parse_tree(body):
    entries, position = {}, 0
    while position < len(body):
        try:
            end = body.index(b"\0", position)
            mode, name = body[position:end].split(b" ", 1)
            name = name.decode("utf-8")
            oid = body[end + 1:end + 21]
        except (ValueError, UnicodeError) as error:
            raise RawGuidanceError("Malformed official Windows Git tree") from error
        if (len(oid) != 20 or name in entries or not name or "/" in name
                or name in (".", "..") or mode not in (b"40000", b"100644", b"100755", b"120000", b"160000")):
            raise RawGuidanceError("Invalid official Windows Git tree entry")
        entries[name] = (mode.decode(), oid.hex())
        position = end + 21
    return entries


class _Objects:
    def __init__(self, commit, tree, request_json, request_bytes, object_root):
        self.commit, self.root_tree = commit, tree
        self.request_json, self.request_bytes = request_json, request_bytes
        self.local = (provenance._Objects(Path(object_root)) if object_root is not None
                      and provenance.has_git_object_store(Path(object_root)) else None)
        self.remote_trees = None
        self.cache, self.total = {}, 0

    def _local(self, kind, oid):
        if self.local is None:
            return None
        try:
            return self.local.read(kind, oid)
        except provenance.GuidanceProvenanceError as error:
            # Availability permits HTTPS fallback. Corrupt or oversized objects
            # remain a hard failure and must not be hidden by a second source.
            if str(error) not in {"Official guidance Git object is unavailable locally",
                                  "Git is required to authenticate development-checkout guidance",
                                  "Cannot read the official guidance Git objects"}:
                raise RawGuidanceError(str(error)) from error
            return None

    def _remote_tree_inventory(self):
        try:
            result = self.request_json(f"{API_ROOT}/git/trees/{self.root_tree}?recursive=1")
        except Exception as error:
            raise RawGuidanceError("Cannot download the official Windows guidance tree") from error
        if (not isinstance(result, dict) or result.get("sha") != self.root_tree
                or result.get("truncated") is not False or not isinstance(result.get("tree"), list)
                or len(result["tree"]) > MAX_TREE_ENTRIES
                or len(json.dumps(result, ensure_ascii=False).encode()) > MAX_TREE_RESPONSE_BYTES):
            raise RawGuidanceError("Official Windows tree is incomplete or exceeds its bounds")
        directories, children, seen = {"": self.root_tree}, {}, set()
        for row in result["tree"]:
            if not isinstance(row, dict):
                raise RawGuidanceError("Malformed official Windows tree response")
            name, mode, oid, kind = (row.get(k) for k in ("path", "mode", "sha", "type"))
            if (not isinstance(name, str) or not name or len(name) > 4096
                    or PurePosixPath(name).as_posix() != name or name.startswith("/")
                    or any(p in (".", "..", "") for p in name.split("/")) or "\0" in name
                    or name in seen or not _oid(oid)
                    or (mode, kind) not in {("040000", "tree"), ("100644", "blob"),
                        ("100755", "blob"), ("120000", "blob"), ("160000", "commit")}):
                raise RawGuidanceError("Unsafe or duplicate official Windows tree entry")
            seen.add(name)
            parent, _, leaf = name.rpartition("/")
            children.setdefault(parent, []).append((leaf, mode.lstrip("0"), oid))
            if kind == "tree":
                directories[name] = oid
        if any(parent not in directories for parent in children):
            raise RawGuidanceError("Official Windows tree omits a parent directory")
        trees, total = {}, 0
        for path, expected in directories.items():
            entries = children.get(path, [])
            entries.sort(key=lambda row: row[0].encode("utf-8") + (b"/" if row[1] == "40000" else b""))
            body = b"".join(mode.encode() + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(oid)
                            for name, mode, oid in entries)
            total += len(body)
            if (len(body) > provenance.MAX_OBJECT_BYTES or total > provenance.MAX_OBJECT_TOTAL_BYTES
                    or _git_hash("tree", body) != expected):
                raise RawGuidanceError("Official Windows tree bytes do not match the authenticated root")
            trees[expected] = body
        self.remote_trees = trees

    def read(self, kind, oid, path=None):
        key = kind, oid
        if key in self.cache:
            return self.cache[key]
        body = self._local(kind, oid)
        if body is None and kind == "tree":
            if self.remote_trees is None:
                self._remote_tree_inventory()
            body = self.remote_trees.get(oid)
        if body is None and kind == "blob":
            if self.request_bytes is None:
                raise RawGuidanceError("Windows guidance bytes are unavailable; enable the updater HTTPS download route")
            url = f"{RAW_ROOT}/{self.commit}/{quote(path, safe='/')}"
            try:
                body = self.request_bytes(url, max_bytes=MAX_FILE_BYTES)
            except Exception as error:
                raise RawGuidanceError(f"Cannot download official Windows guidance: {path}") from error
        if (not isinstance(body, bytes) or len(body) > provenance.MAX_OBJECT_BYTES
                or _git_hash(kind, body) != oid):
            raise RawGuidanceError(f"Official Windows {kind} bytes do not match their identity: {path or oid}")
        self.total += len(body)
        if self.total > provenance.MAX_OBJECT_TOTAL_BYTES:
            raise RawGuidanceError("Official Windows guidance objects exceed their total byte limit")
        self.cache[key] = body
        return body

    def tree(self, oid):
        return _parse_tree(self.read("tree", oid))


def _directory(objects, entries, name):
    entry = entries.get(name)
    if entry is None:
        return {}
    if entry[0] != "40000":
        raise RawGuidanceError(f"Official Windows metadata directory is not a directory: {name}")
    return objects.tree(entry[1])


def _inventory(objects, selection):
    top = objects.tree(objects.root_tree)
    models = _directory(objects, top, "models")
    manifests = _directory(objects, _directory(objects, top, "kiss"), "manifests")
    inputs, membership = {}, {}

    def selected(path, entry):
        if not provenance._allowed(path) or entry[0] not in ("100644", "100755"):
            raise RawGuidanceError(f"Official Windows guidance is not an allowed regular metadata file: {path}")
        inputs[path] = entry[1]

    for name, entry in sorted(models.items()):
        if entry[0] != "40000" or (selection is not None and name not in selection):
            continue
        if not _name(name):
            raise RawGuidanceError("Unsafe model name in official Windows guidance")
        contents = objects.tree(entry[1])
        skill = contents.get("SKILL.md")
        if skill is None:
            continue
        if skill[0] not in ("100644", "100755"):
            raise RawGuidanceError(f"Official Windows model membership is not a regular file: {name}")
        membership[name] = {"path": f"models/{name}/SKILL.md", "blob_sha1": skill[1]}
        if len(membership) > MAX_MODELS:
            raise RawGuidanceError("Official Windows guidance exceeds model inventory bounds")
        for filename, record in contents.items():
            path = f"models/{name}/{filename}"
            if provenance._allowed(path):
                selected(path, record)
        docs = _directory(objects, contents, "docs")
        if "install.windows.md" in docs:
            selected(f"models/{name}/docs/install.windows.md", docs["install.windows.md"])
        if name + ".yaml" in manifests:
            selected(f"kiss/manifests/{name}.yaml", manifests[name + ".yaml"])
    if (not membership or len(membership) > MAX_MODELS or len(inputs) > MAX_FILES
            or (selection is not None and set(membership) != set(selection))):
        raise RawGuidanceError("Official Windows guidance has missing models or exceeds inventory bounds")
    if len({name.casefold() for name in membership}) != len(membership):
        raise RawGuidanceError("Official Windows model names collide on Windows")
    if len({name.casefold() for name in inputs}) != len(inputs):
        raise RawGuidanceError("Official Windows metadata paths collide on Windows")
    return inputs, membership


def _component_id(evidence):
    return _hash({key: evidence[key] for key in ("policy", "implementation", "source_commit",
        "source_tree", "models", "inputs", "membership")})


def _no_link(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or ki_tree._reparse(info):
        raise RawGuidanceError("Windows guidance component contains a link or reparse point")
    return info


def _safe_input(root, parts):
    _no_link(root)
    path = root
    for part in parts:
        path = path / part
        _no_link(path)
    if not path.resolve().is_relative_to(root):
        raise RawGuidanceError("Windows guidance input escapes its component")
    return path


def _read_proof(root):
    _no_link(root)
    path = root / MANIFEST
    info = _no_link(path)
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_PROOF_BYTES:
        raise RawGuidanceError("Windows guidance component proof is missing or oversized")
    with path.open("rb") as handle:
        body = handle.read(MAX_PROOF_BYTES + 1)
    if len(body) > MAX_PROOF_BYTES:
        raise RawGuidanceError("Windows guidance component proof exceeds its size limit")
    return json.loads(body.decode("utf-8"))


def _check_inventory(root, inputs):
    expected = set(inputs) | {MANIFEST}
    directories = {""}
    for name in inputs:
        directories.update(parent.as_posix() for parent in PurePosixPath(name).parents if parent.as_posix() != ".")
    pending, actual, count = [root], set(), 0
    while pending:
        directory = pending.pop()
        if not stat.S_ISDIR(_no_link(directory).st_mode):
            raise RawGuidanceError("Windows guidance directory changed during inspection")
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > MAX_FILES * 5 + 1:
                    raise RawGuidanceError("Windows guidance component inventory exceeds its entry limit")
                path = Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or ki_tree._reparse(info):
                    raise RawGuidanceError("Windows guidance component contains a link or reparse point")
                relative = path.relative_to(root).as_posix()
                if stat.S_ISDIR(info.st_mode):
                    if relative not in directories:
                        raise RawGuidanceError("Windows guidance component has an unexpected directory")
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode) and relative in expected:
                    actual.add(relative)
                else:
                    raise RawGuidanceError("Windows guidance component has an unexpected file")
    if actual != expected:
        raise RawGuidanceError("Windows guidance component inventory changed")


def require_current(root: Path, evidence: dict) -> dict:
    """Recheck exact signed component bytes; authorize metadata composition only."""
    root = Path(root).absolute()
    if not stat.S_ISDIR(_no_link(root).st_mode):
        raise RawGuidanceError("Windows guidance component is not a directory")
    root = root.resolve()
    if (not published_acceptance._authentic(root, evidence)
            or evidence.get("scope") != SCOPE or evidence.get("policy") != POLICY
            or evidence.get("root") != str(root) or evidence.get("source_url") != SOURCE_URL
            or evidence.get("implementation") != _implementation()
            or not _oid(evidence.get("source_commit")) or not _oid(evidence.get("source_tree"))
            or evidence.get("whole_ki_trusted") is not False
            or evidence.get("authoring_verification") is not False
            or evidence.get("native_regression") != "not_run"):
        raise RawGuidanceError("Windows guidance has no current authentic component proof")
    inputs, membership, models = (evidence.get(k) for k in ("inputs", "membership", "models"))
    if (not isinstance(inputs, dict) or len(inputs) > MAX_FILES or not isinstance(membership, dict)
            or not isinstance(models, list) or not 0 < len(models) <= MAX_MODELS
            or any(not _name(name) for name in models) or models != sorted(set(models))
            or set(models) != set(membership)
            or len({name.casefold() for name in models}) != len(models)):
        raise RawGuidanceError("Invalid Windows guidance component inventory")
    for name, row in membership.items():
        if not isinstance(row, dict) or row.get("path") != f"models/{name}/SKILL.md" or not _oid(row.get("blob_sha1")):
            raise RawGuidanceError("Invalid Windows guidance model membership")
    total = 0
    for path, row in inputs.items():
        if (not isinstance(path, str) or not provenance._allowed(path) or not isinstance(row, dict)
                or row.get("path") != path or not _sha(row.get("sha256")) or not _oid(row.get("blob_sha1"))
                or type(row.get("bytes")) is not int or not 0 <= row["bytes"] <= MAX_FILE_BYTES):
            raise RawGuidanceError("Invalid Windows guidance input record")
        parts = PurePosixPath(path).parts
        model = parts[1] if parts[0] == "models" else parts[-1][:-5]
        if model not in membership:
            raise RawGuidanceError("Windows guidance input has no model membership")
        try:
            source = _safe_input(root, parts)
            if not source.is_file() or source.stat().st_size > MAX_FILE_BYTES:
                raise RawGuidanceError("Invalid or oversized Windows guidance input")
            with source.open("rb") as handle:
                body = handle.read(MAX_FILE_BYTES + 1)
            body.decode("utf-8")
        except (OSError, ValueError, UnicodeError) as error:
            raise RawGuidanceError(f"Cannot read authenticated Windows guidance: {path}") from error
        total += len(body)
        if (len(body) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or len(body) != row["bytes"]
                or hashlib.sha256(body).hexdigest() != row["sha256"] or _git_hash("blob", body) != row["blob_sha1"]):
            raise RawGuidanceError(f"Authenticated Windows guidance changed: {path}")
    _check_inventory(root, inputs)
    if (len({name.casefold() for name in inputs}) != len(inputs)
            or evidence.get("content_sha256") != _hash(inputs)
            or evidence.get("component_id") != _component_id(evidence)):
        raise RawGuidanceError("Windows guidance component inventory or identity changed")
    try:
        saved = _read_proof(root)
    except (OSError, ValueError) as error:
        raise RawGuidanceError("Windows guidance component proof is unavailable") from error
    if saved != evidence:
        raise RawGuidanceError("Windows guidance component proof changed")
    return evidence


def prepare(model_names=None, *, request_json, request_bytes=None, object_root=None) -> dict:
    """Fetch current immutable raw metadata through the updater's HTTPS route.

    ``request_bytes(url, *, max_bytes)`` must bound the download while streaming.
    ``request_json(url)`` must likewise cap its response (16 MiB maximum).
    Neither callback chooses the repository, branch or selected metadata paths.
    """
    from . import ki_updates
    if model_names is not None:
        model_names = list(model_names)
        if (not model_names or len(model_names) > MAX_MODELS or any(not _name(n) for n in model_names)
                or len(set(model_names)) != len(model_names)):
            raise RawGuidanceError("Invalid requested Windows model inventory")
        model_names = sorted(model_names)
    implementation = _implementation()
    try:
        official = request_json(SOURCE_URL)
        commit, tree = official["sha"], official["commit"]["tree"]["sha"]
    except Exception as error:
        raise RawGuidanceError("Cannot authenticate the official Windows guidance commit") from error
    if not _oid(commit) or not _oid(tree):
        raise RawGuidanceError("Official Windows response has no exact commit/tree identity")
    key = _hash({"policy": POLICY, "implementation": implementation, "commit": commit,
                 "tree": tree, "selection": model_names})
    cache_home = (ki_updates.update_root() / "windows-guidance").resolve()
    root = cache_home / key
    if root.exists() or root.is_symlink():
        try:
            evidence = _read_proof(root)
            require_current(root, evidence)
        except (OSError, ValueError, TypeError) as error:
            raise RawGuidanceError("Cached raw Windows guidance is invalid; it was not replaced") from error
        if (evidence["source_commit"] != commit or evidence["source_tree"] != tree
                or evidence.get("selection") != model_names):
            raise RawGuidanceError("Cached raw Windows guidance has the wrong source identity")
        return {"root": root, "evidence": evidence}
    objects = _Objects(commit, tree, request_json, request_bytes, object_root)
    selected, membership = _inventory(objects, model_names)
    bodies, inputs, total = {}, {}, 0
    for path, oid in sorted(selected.items()):
        body = objects.read("blob", oid, path)
        try:
            body.decode("utf-8")
        except UnicodeError as error:
            raise RawGuidanceError(f"Official Windows guidance is not UTF-8 text: {path}") from error
        total += len(body)
        if len(body) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise RawGuidanceError("Official Windows guidance exceeds metadata byte limits")
        inputs[path] = {"path": path, "sha256": hashlib.sha256(body).hexdigest(),
                        "bytes": len(body), "blob_sha1": oid}
        bodies[path] = body
    if _implementation() != implementation:
        raise RawGuidanceError("Windows guidance verifier changed during authentication")
    evidence = {"scope": SCOPE, "policy": POLICY, "root": str(root), "source_url": SOURCE_URL,
        "source_commit": commit, "source_tree": tree, "selection": model_names,
        "implementation": implementation, "models": sorted(membership), "membership": membership,
        "inputs": inputs, "content_sha256": _hash(inputs), "whole_ki_trusted": False,
        "authoring_verification": False, "native_regression": "not_run"}
    evidence["component_id"] = _component_id(evidence)
    evidence = published_acceptance._sign(root, evidence)
    cache_home.mkdir(parents=True, exist_ok=True)
    temporary = cache_home / f".incoming-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        for path, body in bodies.items():
            output = temporary.joinpath(*PurePosixPath(path).parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(body)
        (temporary / MANIFEST).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            temporary.rename(root)
        except FileExistsError:
            # Another updater may have published the same immutable component.
            evidence = _read_proof(root)
        require_current(root, evidence)
    finally:
        if temporary.exists() and temporary.resolve().parent == cache_home:
            shutil.rmtree(temporary)
    return {"root": root, "evidence": evidence}
