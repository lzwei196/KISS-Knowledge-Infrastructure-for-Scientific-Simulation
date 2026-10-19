"""Identity of the trusted service that owns paths, checks and model processes.

A Linux sidecar is a whole native service. Never translate a Windows project's
paths or import its receipts into this service. Startup identity is supplied by
the Desktop supervisor, not by an agent or a model manifest.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import platform
import re
from pathlib import Path


_GUEST_FIELDS = frozenset({"protocol", "uid", "user", "home", "machine_id",
    "kernel", "architecture", "python", "python_realpath", "python_sha256",
    "python_version", "workspace", "workspace_id", "filesystem",
    "workspace_device", "workspace_inode", "marker_sha256"})
_DYNAMIC_GUEST_FIELDS = frozenset({"kernel", "python_sha256", "python_version"})


def guest_digest(value: dict) -> str:
    """The exact worker protocol canonicalization, without transport metadata."""
    if not isinstance(value, dict) or set(value) != _GUEST_FIELDS:
        raise ValueError("Incomplete Linux guest identity")
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def guest_path_digest(value: dict) -> str:
    """Bind location/ownership; readiness separately binds changing runtime bytes."""
    guest_digest(value)  # Reject unknown/missing protocol fields, never discard them.
    stable = {key: item for key, item in value.items() if key not in _DYNAMIC_GUEST_FIELDS}
    raw = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


@functools.lru_cache(maxsize=1)
def _guest_observation(distro, user, workspace, identifier):
    from . import runtime_backend
    selected = runtime_backend.WSLBinding(distro, user, workspace, identifier)
    observed = runtime_backend.LocalExecutor.inspect(selected)
    raw = {key: value for key, value in observed.items() if key not in {"identity_sha256", "transport"}}
    if guest_digest(raw) != observed.get("identity_sha256"):
        raise ValueError("Linux guest identity hash does not match its observed fields")
    return raw


def guest_observation() -> dict:
    """Return startup-checked fields; callers cannot mutate the cached evidence."""
    current = identity()
    if current.get("kind") != "wsl":
        raise ValueError("A bound Linux guest is required")
    value = _guest_observation(current["distro"], current["user"],
                               current["workspace"], current["id"])
    return json.loads(json.dumps(value))


@functools.lru_cache(maxsize=1)
def identity() -> dict:
    raw = os.environ.get("GEOFORGE_RUNTIME_IDENTITY")
    if not raw:
        return {"kind": "native", "platform": platform.system(),
                "machine": platform.machine()}
    value = json.loads(raw)
    fields = {"id", "distro", "user", "workspace", "source_hash", "nonce"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Invalid supervised Linux runtime identity")
    if any(not isinstance(v, str) or not v or "\0" in v for v in value.values()):
        raise ValueError("Incomplete supervised Linux runtime identity")
    if platform.system() != "Linux":
        raise ValueError("A Linux binding must run in Linux")
    if not re.fullmatch(r"[a-f0-9]{64}", value["source_hash"]):
        raise ValueError("Invalid Linux runtime source fingerprint")
    root = Path(value["workspace"])
    if not root.is_absolute() or root.resolve() != root or str(root).startswith("/mnt/"):
        raise ValueError("The Linux workspace must use a native absolute path")
    import pwd
    if os.getuid() == 0 or pwd.getpwuid(os.getuid()).pw_name != value["user"]:
        raise ValueError("Linux runtime user differs from the selected non-root binding")
    _guest_observation.cache_clear()  # Rechecking startup identity must refresh the observation too.
    observed = _guest_observation(value["distro"], value["user"],
                                  value["workspace"], value["id"])
    return {"kind": "wsl", "platform": "Linux", "machine": platform.machine(),
            "guest_identity": guest_digest(observed),
            "guest_path_identity": guest_path_digest(observed), **value}


def binding() -> dict:
    """Stable across a service restart, different after a backend/build change."""
    return {k: v for k, v in identity().items() if k != "nonce"}


def guidance() -> str:
    value = identity()
    if value["kind"] != "wsl":
        return ""
    return ("\nHOST-BOUND LINUX RUNTIME: This entire GeoForge service, its KI "
            "checks and its tools run natively in Linux under the selected WSL "
            f"distribution {value['distro']}, user {value['user']}. Use Linux "
            "paths and dependencies. Windows executables, Windows installation "
            "receipts, old Windows setup attempts, and macOS Homebrew-specific "
            "hints are not applicable. Do not invoke wsl, change the distro, "
            "or modify the GeoForge service/profile. Required native features "
            "must pass the host capability checks; fake libraries, no-op MPI "
            "functions, or disabled netCDF-4 features cannot establish readiness.\n")
