"""Shared native-dependency admission for setup and every provider's dispatch.

The first profile covers Ubuntu MPI + Fortran netCDF-4. Other combinations
remain explicitly unsupported, not silently certified from a file/version flag.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import threading

from . import dependency_capabilities as capabilities, runtime_backend, runtime_context

_LOCK = threading.RLock()
# The functional profile invokes this exact alias. Other system executables or
# aliases are not implied by membership in the signed package file inventory.
_MPI_LAUNCHER = "/usr/bin/mpiexec"
_MPI_TARGET = "/usr/bin/orterun"


@dataclass(frozen=True)
class VerifiedArguments:
    """In-process result of full currentness checks, never request/plan JSON.

    The JSON strings make the already authenticated reports immutable between
    admission and argument capture. This does not constrain arbitrary child code.
    """
    runtime_identity: str
    executable: str
    capability_json: str
    binary_json: str

    def binding(self, cfg, role: str, candidate: Path) -> tuple[str, str, int, str]:
        from .software_verification import runtime_identity
        if runtime_identity(cfg) != self.runtime_identity:
            raise ValueError("Native argument capability belongs to another runtime")
        report, binary = json.loads(self.capability_json), json.loads(self.binary_json)
        if report.get("profile") != capabilities.PROFILE:
            raise ValueError("Unsupported native argument capability profile")
        if role == "engine":
            alias = self.executable
            row = binary.get("evidence", {})
            if binary.get("executable") != alias or row.get("executable") != alias:
                raise ValueError("Native argument lacks the verified executable identity")
            target = alias
        elif role == "mpi_launcher":
            alias, target = _MPI_LAUNCHER, _MPI_TARGET
            row = report.get("evidence", {}).get("system_files", {}).get(target, {})
            if (row.get("path") != target or not isinstance(row.get("package"), str)
                    or not re.fullmatch(r"openmpi-bin(?::[a-z0-9]+)?", row["package"])):
                raise ValueError("MPI argument lacks the verified launcher role")
        else:
            raise ValueError("Unsupported native argument role")
        if candidate != Path(alias) or candidate.resolve(strict=True) != Path(target):
            raise ValueError(f"Named {role} argument must use its exact verified path: {alias}")
        size, digest = row.get("bytes"), row.get("sha256")
        if (type(size) is not int or not 0 < size <= 256 * 1024 * 1024
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("Native argument lacks an exact verified file hash")
        return alias, target, size, digest


def _context():
    from .firstrun import data_dir
    current = runtime_context.identity()
    if current["kind"] != "wsl":
        raise ValueError("This KI declares MPI and Fortran netCDF capabilities. Select a bound Linux runtime and verify them there; this platform has no supported capability proof yet.")
    binding = runtime_backend.WSLBinding(current["distro"], current["user"],
        current["workspace"], current["id"])
    authority = data_dir() / "dependency-capabilities"
    return binding, authority, runtime_backend.LocalExecutor


def _get(man, key, default=None):
    return man.get(key, default) if isinstance(man, dict) else getattr(man, key, default)


def _executable(man, cfg):
    acquire = _get(man, "acquire")
    produces = _get(acquire, "produces")
    relative = PurePosixPath(produces or "")
    if not produces or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Native dependency verification requires an exact declared model executable")
    return cfg.roles["binaries"] / (_get(man, "install_dir") or _get(man, "model")) / str(relative)


def _record_path(authority, cfg):
    from .software_verification import runtime_identity
    return authority / (runtime_identity(cfg) + ".json")


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def verify(man, cfg) -> dict:
    profiles = capabilities.profiles_for_manifest(man)
    if not profiles:
        return {}
    binding, authority, executor = _context()
    with _LOCK:
        from . import install, setup_jobs
        def stopped():
            install.check_cancelled()
            return False
        report = capabilities.verify(binding, authority=authority, backend=executor, stop=stopped)
        binary = capabilities.verify_binary(report, binding, str(_executable(man, cfg)),
            authority=authority, backend=executor, stop=stopped)
        record = {"capabilities": report, "binary": binary}
        setup_jobs._write(_record_path(authority, cfg), record)
        return {"profiles": list(profiles), "model_readiness": False,
                "evidence_sha256": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()}


def require_current(man, cfg, *, stop=None, environment=None, native_executable=None) -> VerifiedArguments | None:
    if not capabilities.profiles_for_manifest(man):
        return
    binding, authority, executor = _context()
    with _LOCK:
        record = _read(_record_path(authority, cfg))
        if not isinstance(record, dict):
            raise ValueError("Native dependency proof is missing; recheck this exact runtime")
        executable = _executable(man, cfg)
        if native_executable is not None:
            actual = Path(native_executable)
            if not actual.is_absolute() or actual.resolve(strict=True) != executable.resolve(strict=True):
                raise ValueError("Direct native launch differs from the dependency-verified executable")
        capabilities.require_current(record.get("capabilities"), binding,
            authority=authority, backend=executor, stop=stop)
        capabilities.require_binary_current(record.get("binary"), record.get("capabilities"), binding,
            str(executable), authority=authority, backend=executor, stop=stop)
        if environment is not None:
            capabilities.validate_loader_environment(record["capabilities"], environment)
        from .software_verification import runtime_identity
        return VerifiedArguments(runtime_identity(cfg), str(executable),
            json.dumps(record["capabilities"], sort_keys=True),
            json.dumps(record["binary"], sort_keys=True))
