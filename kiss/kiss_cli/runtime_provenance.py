"""Observational app/backend provenance, separate from readiness authority.

Freeze at service startup, retain at real checks, and never fill an old record
with today's build. A portable payload fingerprint includes its library; it
does not establish which model binary ran or why files changed.
"""
from __future__ import annotations

import copy
import functools
import hashlib
import json
import re
import stat
import sys
import tomllib
from pathlib import Path

from . import runtime_context

_BACKEND_FIELDS = frozenset({"kind", "platform", "machine", "id", "distro", "user",
    "workspace", "guest_identity", "guest_path_identity"})
_SCHEMES = frozenset({"supervised-portable-payload-sha256-v1",
    "python-application-tree-sha256-v1", "frozen-executable-sha256-v1", "unknown"})
_CODE_SUFFIXES = frozenset({".py", ".html", ".js", ".css", ".svg"})


def _ordinary(path: Path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(info, "st_file_attributes", 0) & 0x400
            or path.resolve() != path.absolute()):
        raise ValueError("Application provenance requires ordinary files")
    return info


def _version(package: Path) -> tuple[str | None, str]:
    # The sidecar carries this exact source-project metadata in its checked
    # payload. Do not use unrelated installed wheel metadata for source code.
    path = package.parent / "pyproject.toml"
    try:
        if _ordinary(path).st_size > 256 * 1024:
            return None, "unknown"
        project = tomllib.loads(path.read_text(encoding="utf-8")).get("project", {})
        if not isinstance(project, dict):
            return None, "unknown"
        version = project.get("version")
        if (project.get("name") == "kiss-ki" and isinstance(version, str)
                and re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,79}", version)):
            return version, "source-project-metadata"
    except (OSError, ValueError, TypeError):
        pass
    return None, "unknown"


def _source_build(package: Path) -> dict:
    import ki_tools_common
    common = Path(ki_tools_common.__file__).absolute().parent
    rows = {}
    for folder, prefix in ((package, "kiss_cli"), (common, "ki_tools_common")):
        total = 0
        for path in sorted(folder.rglob("*")):
            relative = path.relative_to(folder)
            if (path.suffix.lower() not in _CODE_SUFFIXES or
                    any(p in {"tests", "test", "__pycache__", ".git"} for p in relative.parts)):
                continue
            info = _ordinary(path)
            total += info.st_size
            if total > 64 * 1024 * 1024 or len(rows) > 10000:
                raise ValueError("Application provenance exceeds its bounded source scan")
            rows[prefix + "/" + relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not rows:
        raise ValueError("No application source files are available")
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"scheme": "python-application-tree-sha256-v1", "sha256": digest}


@functools.lru_cache(maxsize=1)
def _startup() -> dict:
    runtime = runtime_context.identity()
    package = Path(__file__).absolute().parent
    version, version_source = _version(package)
    if runtime.get("kind") == "wsl":
        build = {"scheme": "supervised-portable-payload-sha256-v1",
                 "sha256": runtime.get("source_hash")}
    elif getattr(sys, "frozen", False):
        try:
            executable = Path(sys.executable).absolute()
            _ordinary(executable)
            with executable.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            build = {"scheme": "frozen-executable-sha256-v1", "sha256": digest}
        except (OSError, ValueError):
            build = {"scheme": "unknown", "sha256": None}
    else:
        try:
            build = _source_build(package)
        except (OSError, ValueError, TypeError):
            build = {"scheme": "unknown", "sha256": None}
    return validate({"schema_version": 1, "application": {
        "name": "GeoForge", "version": version, "version_source": version_source,
        "build": build}, "backend": {key: runtime[key] for key in _BACKEND_FIELDS if key in runtime}})


def capture() -> dict:
    """Copy the startup observation; no readiness checks, writes or key creation."""
    return copy.deepcopy(_startup())


def validate(value) -> dict:
    """Strictly validate signed retained data; never substitute current facts."""
    if (not isinstance(value, dict) or set(value) != {"schema_version", "application", "backend"}
            or type(value.get("schema_version")) is not int or value["schema_version"] != 1):
        raise ValueError("Invalid runtime provenance schema")
    app, backend = value.get("application"), value.get("backend")
    if not isinstance(app, dict) or set(app) != {"name", "version", "version_source", "build"} or app.get("name") != "GeoForge":
        raise ValueError("Invalid application provenance")
    version = app.get("version")
    if version is not None and (not isinstance(version, str) or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,79}", version)):
        raise ValueError("Invalid declared application version")
    if app.get("version_source") not in {"source-project-metadata", "unknown"} or (version is None) != (app.get("version_source") == "unknown"):
        raise ValueError("Invalid application version source")
    build = app.get("build")
    if not isinstance(build, dict) or set(build) != {"scheme", "sha256"} or build.get("scheme") not in _SCHEMES:
        raise ValueError("Invalid application build scheme")
    digest = build.get("sha256")
    if build["scheme"] == "unknown":
        if digest is not None:
            raise ValueError("Unknown build cannot claim a digest")
    elif not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid application build fingerprint")
    if (not isinstance(backend, dict) or not set(backend).issubset(_BACKEND_FIELDS)
            or backend.get("kind") not in {"native", "wsl"}
            or not isinstance(backend.get("platform"), str) or not backend["platform"]):
        raise ValueError("Invalid backend provenance")
    expected = _BACKEND_FIELDS if backend["kind"] == "wsl" else {"kind", "platform", "machine"}
    if set(backend) != expected:
        raise ValueError("Incomplete backend provenance")
    if ((build["scheme"] == "supervised-portable-payload-sha256-v1" and backend["kind"] != "wsl")
            or (backend["kind"] == "wsl" and build["scheme"] not in {"supervised-portable-payload-sha256-v1", "unknown"})):
        raise ValueError("Build fingerprint scheme differs from its backend")
    for item in backend.values():
        if not isinstance(item, str) or not item or len(item) > 2048 or any(ord(c) < 32 for c in item):
            raise ValueError("Invalid backend provenance field")
    if backend["kind"] == "wsl" and any(not re.fullmatch(r"[0-9a-f]{64}", backend[key])
                                       for key in ("guest_identity", "guest_path_identity")):
        raise ValueError("Invalid guest identity fingerprint")
    return copy.deepcopy(value)


def compare(saved, current=None) -> dict:
    """Field comparisons, never a verdict about model runs or readiness."""
    now = validate(current if current is not None else capture())
    if saved is None:
        return {"build": "unknown", "backend": "unknown", "declared_version": "unknown",
                "reason": "legacy_record_has_no_runtime_provenance"}
    old = validate(saved)
    a, b = old["application"], now["application"]
    one, two = a["build"], b["build"]
    build = ("unknown" if one["scheme"] == "unknown" or one["scheme"] != two["scheme"] else
             "same" if one["sha256"] == two["sha256"] else "different")
    return {"build": build, "backend": "same" if old["backend"] == now["backend"] else "different",
            "declared_version": ("unknown" if a["version"] is None or b["version"] is None else
                                 "same" if a["version"] == b["version"] else "different"),
            "reason": "observations_only_not_readiness_or_model_execution"}
