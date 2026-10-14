"""Declared, versioned runtime support files; acquisition is an explicit setup action.

This is not a forcing/observation downloader. Reuse the installer's pinned Git
transport, without build commands, and materialize only declared missing files.
Checks never fetch, repair files, run the model, or grant scientific readiness.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import threading
from urllib.parse import urlsplit

POLICY = "declared-runtime-data-v1"
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
_LOCK = threading.RLock()


def _hash(doc) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _relative(value) -> str:
    if not isinstance(value, str) or not value or len(value) > 512 \
            or any(c in value for c in "\\\0\r\n:$"):
        raise ValueError("Runtime data paths must be ordinary relative POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(p in (".", "..") for p in path.parts) \
            or not path.parts or any(p.endswith((".", " ")) for p in path.parts):
        raise ValueError("Runtime data path is not canonical and relative")
    return value


def validate_contract(value) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"version", "source", "target", "files"} \
            or type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("runtime_data requires version 1, source, target and files")
    source, target, files = value["source"], value["target"], value["files"]
    if not isinstance(source, dict) or set(source) != {"repo", "commit"}:
        raise ValueError("Runtime data source requires repo and commit")
    repo = source["repo"]
    if not isinstance(repo, str) or len(repo) > 2048:
        raise ValueError("Runtime data repository must be an explicit HTTPS URL")
    parsed = urlsplit(repo)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password \
            or parsed.query or parsed.fragment or not parsed.path or any(c.isspace() for c in repo):
        raise ValueError("Runtime data repository must be HTTPS without credentials, query or fragment")
    if not isinstance(source["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", source["commit"]):
        raise ValueError("Runtime data source requires an exact 40-character commit")
    if not isinstance(target, dict) or set(target) != {"role", "path"} \
            or target["role"] not in ("home", "binaries"):
        raise ValueError("Runtime data target requires a home or binaries role and relative path")
    _relative(target["path"])
    if not isinstance(files, list) or not 1 <= len(files) <= 512:
        raise ValueError("Runtime data must declare 1..512 exact support files")
    destinations, sources, total = set(), set(), 0
    for item in files:
        if not isinstance(item, dict) or set(item) not in (
                {"source", "path", "sha256", "bytes"},
                {"source", "path", "sha256", "bytes", "text_newlines"}):
            raise ValueError("Each runtime data file requires source, path, sha256 and bytes")
        if "text_newlines" in item and item["text_newlines"] != "lf_or_crlf":
            raise ValueError("Runtime data text_newlines supports only explicit lf_or_crlf")
        for name, seen in (("source", sources), ("path", destinations)):
            path = _relative(item[name]).casefold()
            if path in seen:
                raise ValueError("Runtime data file paths must be unique on every supported OS")
            seen.add(path)
        if not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("Runtime data files require an exact SHA256")
        size = item["bytes"]
        if type(size) is not int or not 1 <= size <= MAX_FILE_BYTES:
            raise ValueError("Runtime data file size must be 1..32 MiB")
        total += size
    if total > MAX_TOTAL_BYTES:
        raise ValueError("Declared runtime data exceeds 256 MiB")
    for path in destinations:
        if any(parent.as_posix().casefold() in destinations for parent in PurePosixPath(path).parents
               if parent.as_posix() != "."):
            raise ValueError("A runtime data file cannot also be a parent directory")
    return value


def _ordinary(path: Path, *, directory=False, missing=True) -> None:
    for ancestor in reversed((path, *path.parents)):
        if ancestor.resolve() != ancestor:
            raise ValueError(f"Runtime data path is aliased: {ancestor}")
        if ancestor.exists():
            info = ancestor.stat()
            if ancestor != path and not stat.S_ISDIR(info.st_mode):
                raise ValueError("Runtime data path has a non-directory ancestor")
    if path.exists():
        info = path.stat()
        if directory and not stat.S_ISDIR(info.st_mode) or not directory and not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Runtime data path is not an ordinary {'directory' if directory else 'file'}: {path}")
        if not directory and info.st_nlink != 1:
            raise ValueError(f"Runtime data file is hardlinked: {path}")
    elif not missing:
        raise ValueError(f"Required runtime data is absent: {path}")


def _target(cfg, contract, *, writable=False) -> Path:
    role = cfg.roles.get(contract["target"]["role"])
    if role is None or not Path(role).is_absolute():
        raise ValueError("Runtime data target role must name an absolute configured directory")
    base = Path(os.path.abspath(role))
    target = base / contract["target"]["path"]
    _ordinary(target, directory=True)
    if writable:
        root = Path(cfg.root).resolve()
        if not target.is_relative_to(root) or target == root:
            raise ValueError("Required data preparation writes only inside the selected setup workspace")
        relative = target.relative_to(root)
        if any(part.casefold() in {"ki", "ktc", "ki_tools_common", ".geoforge", "runs", "outputs", "inputs"}
               for part in relative.parts):
            raise ValueError("Runtime support data cannot overwrite KI, helper, host or project-data trees")
    return target


def _file_identity(path: Path, item: dict) -> dict:
    """Pin actual bytes; tolerate only an explicitly declared uniform text representation."""
    size = path.stat().st_size
    text = item.get("text_newlines") == "lf_or_crlf"
    if (not text and size != item["bytes"]) or (text and not item["bytes"] <= size <= 2 * item["bytes"]):
        raise ValueError("size does not match the declared official file")
    with path.open("rb") as stream:
        payload = stream.read(size + 1)
    if len(payload) != size:
        raise ValueError("runtime data changed while being checked")
    canonical = payload
    representation = "git_blob"
    if text:
        canonical = payload.replace(b"\r\n", b"\n")
        if b"\0" in canonical or b"\r" in canonical:
            raise ValueError("Declared text data contains binary NUL or lone CR")
        if b"\r\n" in payload and payload.count(b"\n") != payload.count(b"\r\n"):
            raise ValueError("Declared text data has mixed LF and CRLF representations")
        representation = "crlf" if b"\r\n" in payload else "lf"
    canonical_hash = hashlib.sha256(canonical).hexdigest()
    if len(canonical) != item["bytes"] or canonical_hash != item["sha256"]:
        raise ValueError("content does not match the declared official file")
    return {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": size,
            "canonical_sha256": canonical_hash, "representation": representation}


def inspect(man, cfg) -> dict | None:
    contract = validate_contract(getattr(man, "runtime_data", None))
    if contract is None:
        return None
    target = _target(cfg, contract)
    rows = []
    for item in contract["files"]:
        path = target / item["path"]
        row = {"path": str(path), "source_path": item["source"], "expected_sha256": item["sha256"],
               "expected_bytes": item["bytes"], "state": "missing"}
        try:
            _ordinary(path)
            if path.exists():
                row.update(_file_identity(path, item))
                row["state"] = "present"
        except (OSError, ValueError) as error:
            row.update(state="conflict", detail=str(error))
        rows.append(row)
    return {"policy": POLICY, "policy_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "contract_sha256": _hash(contract), "source": dict(contract["source"]),
            "target_root": str(target), "files": rows,
            "ok": all(row["state"] == "present" for row in rows),
            "model_executed": False, "scientific_validation": False}


def check(man, cfg):
    from .install import Step
    try:
        report = inspect(man, cfg)
    except (OSError, ValueError, TypeError) as error:
        return Step("runtime-data", False, str(error))
    if report is None:
        return Step("runtime-data", True, "No runtime support-data contract declared", skipped=True)
    failures = [f"{row['path']}: {row['state']}" for row in report["files"] if row["state"] != "present"]
    return Step("runtime-data", report["ok"], "\n".join(failures) if failures else
                "Declared runtime support files match their exact version and hashes", evidence=report)


def _git(source: Path, args: list[str]) -> bytes:
    from . import install
    install.check_cancelled()
    result = subprocess.run(["git", "-C", str(source), *args], capture_output=True, timeout=30)
    install.check_cancelled()
    if result.returncode:
        raise ValueError("Pinned runtime-data source could not be read: " +
                         result.stderr.decode("utf-8", "replace")[-1000:])
    return result.stdout


def _source_matches(source: Path, declaration) -> bool:
    if not (source / ".git").is_dir():
        return False
    _ordinary(source, directory=True, missing=False)
    _ordinary(source / ".git", directory=True, missing=False)
    try:
        return (_git(source, ["remote", "get-url", "origin"]).decode().strip() == declaration["repo"]
                and _git(source, ["rev-parse", declaration["commit"] + "^{commit}"]).decode().strip()
                == declaration["commit"])
    except ValueError:
        return False


def prepare(man, cfg, *, allow_acquire: bool, env: dict | None = None):
    """Explicit setup only. Preserve mismatched files and repair only missing declared data."""
    from . import install, obs_access
    from .manifest import Acquire, Manifest
    with _LOCK:
        try:
            contract = validate_contract(getattr(man, "runtime_data", None))
            if contract is None:
                return check(man, cfg)
            before = check(man, cfg)
            if before.ok:
                return before
            if allow_acquire is not True:
                return install.Step("runtime-data", False,
                    "Required support data is missing; use the explicit Prepare required data setup action",
                    evidence=before.evidence)
            target = _target(cfg, contract, writable=True)
            if not before.evidence or any(row["state"] == "conflict" for row in before.evidence["files"]):
                return install.Step("runtime-data", False,
                    "Existing runtime data differs from the declaration; no files were replaced.\n" + before.detail,
                    evidence=before.evidence)
            install.check_cancelled()
            root = Path(cfg.root).resolve()
            source = next((ancestor for ancestor in target.parents
                           if ancestor.is_relative_to(root) and _source_matches(ancestor, contract["source"])), None)
            if source is None:
                source = root / ".geoforge" / "runtime-data-sources" / _hash(contract["source"])[:24]
                _ordinary(source, directory=True)
                if not _source_matches(source, contract["source"]):
                    if source.exists() and any(source.iterdir()):
                        raise ValueError("Runtime-data source cache is not the declared pinned repository")
                    source_manifest = Manifest(model=man.model, acquire=Acquire(strategy="build",
                        repo=contract["source"]["repo"], ref=contract["source"]["commit"], commands=[]))
                    result, _unused = install.acquire(source_manifest, source, cfg.python, env=env)
                    if not result.ok:
                        return install.Step("runtime-data", False, result.detail, commands=result.commands)
                    if not _source_matches(source, contract["source"]):
                        raise ValueError("Acquired runtime-data source does not match its declared repository/commit")
            pending = []
            for item, row in zip(contract["files"], before.evidence["files"]):
                if row["state"] != "missing":
                    continue
                key = contract["source"]["commit"] + ":" + item["source"]
                tree = _git(source, ["ls-tree", contract["source"]["commit"], "--", item["source"]]).decode()
                if not tree.startswith(("100644 blob ", "100755 blob ")) or len(tree.splitlines()) != 1:
                    raise ValueError("Declared runtime-data source is not an ordinary Git blob")
                if int(_git(source, ["cat-file", "-s", key])) != item["bytes"]:
                    raise ValueError("Pinned source size does not match the runtime-data declaration")
                payload = _git(source, ["cat-file", "blob", key])
                if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
                    raise ValueError("Pinned source bytes do not match the runtime-data declaration")
                if item.get("text_newlines") == "lf_or_crlf" and (b"\r" in payload or b"\0" in payload):
                    raise ValueError("Declared LF text source contains CR or binary NUL")
                pending.append((target / item["path"], payload))
            # Verify the entire source selection before publishing any missing file.
            installed = []
            for destination, payload in pending:
                install.check_cancelled()
                _ordinary(destination)
                if destination.exists():
                    raise ValueError("Runtime data destination changed during preparation; no overwrite allowed")
                destination.parent.mkdir(parents=True, exist_ok=True)
                fd, raw = tempfile.mkstemp(prefix=".runtime-data-", dir=destination.parent)
                temporary = Path(raw)
                try:
                    with os.fdopen(fd, "wb") as output:
                        output.write(payload)
                        output.flush()
                        os.fsync(output.fileno())
                    install.check_cancelled()
                    _ordinary(destination)
                    os.link(temporary, destination)  # exclusive publication; never replace user data
                finally:
                    temporary.unlink(missing_ok=True)
                installed.append(str(destination))
            result = check(man, cfg)
            install.check_cancelled()
            result.evidence.update(acquisition={"source_root": str(source), "files_created": installed,
                                                "engine_built": False})
            if result.ok:
                from . import flowgate
                receipt = flowgate.load().receipts.sign(root, dict(result.evidence))
                record = root / ".geoforge" / "runtime-data" / (result.evidence["contract_sha256"] + ".json")
                _ordinary(record)
                obs_access._atomic_json(record, receipt)
            return result
        except install.InstallStopped:
            raise
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
            return install.Step("runtime-data", False, str(error))
