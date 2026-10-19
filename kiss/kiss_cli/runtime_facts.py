"""Read-only provider context from authenticated native dependency evidence.

This does not run probes, grant permission or certify a scientific case. Full
dependency/current-loader admission remains at preflight and execution.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import stat
import tomllib

from . import dependency_capabilities as cap, native_dependency_gate as gate
from . import paths, runtime_context

_PROFILE_TOOLS = {
    "mpi_launcher": "/usr/bin/mpiexec",
    "mpi_fortran_wrapper": "/usr/bin/mpifort",
    "fortran_compiler": "/usr/bin/gfortran",
    "netcdf_fortran_config": "/usr/bin/nf-config",
    "netcdf_format_reader": "/usr/bin/ncdump",
}
# This existing profile explicitly verifies Ubuntu OpenMPI packages. Its
# canonical package entrypoints distinguish tool roles even if an alternatives
# symlink is later redirected to a different, otherwise signed system file.
_ROLE_TARGETS = {
    "mpi_launcher": (r"/usr/bin/orterun", r"openmpi-bin(?::[a-z0-9]+)?"),
    "mpi_fortran_wrapper": (r"/usr/bin/opal_wrapper", r"openmpi-bin(?::[a-z0-9]+)?"),
    "fortran_compiler": (r"/usr/bin/(?:[A-Za-z0-9_-]+-)?gfortran-[0-9]+",
                         r"gfortran-[0-9]+(?:-[a-z0-9-]+)?(?::[a-z0-9]+)?"),
    "netcdf_fortran_config": (r"/usr/bin/nf-config", r"libnetcdff-dev(?::[a-z0-9]+)?"),
    "netcdf_format_reader": (r"/usr/bin/ncdump", r"netcdf-bin(?::[a-z0-9]+)?"),
}
_MAX_RECORD = 4 * 1024 * 1024
_MAX_FILE = 256 * 1024 * 1024


def _ordinary(path):
    path = Path(path).absolute()
    for node in (path, *path.parents):
        row = node.lstat()
        if stat.S_ISLNK(row.st_mode) or getattr(row, "st_file_attributes", 0) & 0x400:
            raise ValueError("runtime context path is linked")
    if not path.is_file():
        raise ValueError("runtime context file is missing")
    return path


def _read(path, limit):
    path = _ordinary(path)
    if path.stat().st_size > limit:
        raise ValueError("runtime context record is too large")
    with path.open("rb") as stream:
        result = stream.read(limit + 1)
    if len(result) > limit:
        raise ValueError("runtime context record grew while reading")
    return result


def _config(root):
    """No ancestor fallback, legacy repair, runtime discovery or file writes."""
    root = Path(root).absolute()
    raw = tomllib.loads(_read(root / paths.CONFIG_NAME, 128 * 1024).decode("utf-8"))
    settings, roles = raw.get("kiss"), raw.get("paths")
    if not isinstance(settings, dict) or not isinstance(roles, dict):
        raise ValueError("saved runtime configuration is incomplete")
    if (not isinstance(settings.get("root"), str) or Path(settings["root"]) != root
            or root.resolve() != root or not isinstance(settings.get("python"), str)
            or not Path(settings["python"]).is_absolute()
            or settings.get("relocation") not in {"none", "sandbox", "port", "symlink"}
            or any(not isinstance(v, str) or not Path(v).is_absolute() for v in roles.values())):
        raise ValueError("saved runtime configuration has unsupported bindings")
    return paths.KissConfig(root=root, python=settings["python"],
        relocation=settings["relocation"], roles={k: Path(v) for k, v in roles.items()})


def _file_matches(path, expected):
    path = _ordinary(path)
    size = expected.get("bytes")
    digest = expected.get("sha256")
    if (type(size) is not int or not 0 < size <= _MAX_FILE or
            not isinstance(digest, str) or len(digest) != 64 or path.stat().st_size != size):
        raise ValueError("recorded runtime file identity changed")
    observed = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            count += len(block)
            if count > size:
                raise ValueError("runtime file grew while reading")
            observed.update(block)
    if count != size or observed.hexdigest() != digest:
        raise ValueError("recorded runtime file bytes changed")


def context(manifest, install_root) -> dict | None:
    """Return bounded facts or explicit unavailability, never readiness.

    The host's current supervised identity was validated at service startup.
    Here it is read from memory; no Linux transport or process is invoked.
    """
    if not cap.profiles_for_manifest(manifest):
        return None
    model = gate._get(manifest, "model")
    unavailable = {"model": model, "state": "unavailable", "model_readiness": False,
                   "detail": "No authenticated, byte-current shared runtime facts are available. "
                             "Do not infer that a KI default executable or MPI path exists; "
                             "ordinary installation verification must establish the binding."}
    try:
        cfg = _config(install_root)
        binding, authority, _backend = gate._context()
        runtime = runtime_context.identity()
        raw = _read(gate._record_path(authority, cfg), _MAX_RECORD)
        saved = json.loads(raw)
        report, binary = saved["capabilities"], saved["binary"]
        from . import flowgate
        receipts = flowgate.load().receipts
        implementation = cap._implementation()
        executable = str(gate._executable(manifest, cfg))
        for document, policy in ((report, cap.POLICY), (binary, cap.BINARY_POLICY)):
            if (not isinstance(document, dict) or not receipts.verify(authority, document)
                    or document.get("policy") != policy or document.get("implementation") != implementation
                    or document.get("binding") != asdict(binding)
                    or document.get("backend_identity") != runtime.get("guest_identity")
                    or document.get("model_readiness") is not False):
                raise ValueError("runtime facts are unauthenticated or stale")
        if (report.get("profile") != cap.PROFILE or binary.get("executable") != executable
                or binary.get("capability_sha256") != cap._hash(cap._json(report))):
            raise ValueError("runtime facts refer to another model/runtime proof")
        evidence, native = report["evidence"], binary["evidence"]
        if native.get("executable") != executable:
            raise ValueError("binary identity differs from the declared executable")
        system = evidence["system_files"]
        if not isinstance(system, dict) or not system or len(system) > 2048:
            raise ValueError("system file evidence is missing or too large")
        checked = {}
        def check(name, row):
            identity = (row.get("bytes"), row.get("sha256"))
            if name in checked:
                if checked[name] != identity:
                    raise ValueError("conflicting signed runtime file identities")
                return
            _file_matches(name, row)
            checked[name] = identity
        for name, row in system.items():
            if row.get("path") != name:
                raise ValueError("system file evidence path differs")
            check(name, row)
        for collection in (native["libraries"], native.get("inspection_tools", {})):
            for name, row in collection.items():
                check(name, row)
        check(executable, native)
        work = Path(evidence["workspace"])
        if (work != Path(binding.workspace) / report["relative"] or
                not work.is_relative_to(Path(binding.workspace)) or work.resolve() != work
                or set(evidence["artifacts"]) != set(cap.ARTIFACTS)):
            raise ValueError("probe artifact inventory differs")
        for name, row in evidence["artifacts"].items():
            # Empty stderr files are legitimate probe evidence.
            file = work / name
            if row.get("bytes") == 0 and row.get("sha256") == hashlib.sha256(b"").hexdigest():
                if _read(file, 1) != b"":
                    raise ValueError("probe artifact changed")
            else:
                check(str(file), row)
        tools = {}
        for role, invoked in _PROFILE_TOOLS.items():
            resolved = str(Path(invoked).resolve(strict=True))
            path_pattern, package_pattern = _ROLE_TARGETS[role]
            candidates = [name for name, row in system.items()
                          if re.fullmatch(path_pattern, Path(name).as_posix())
                          and re.fullmatch(package_pattern, row.get("package", ""))]
            if candidates != [resolved]:
                raise ValueError("profile tool no longer resolves to its verified package entrypoint")
            row = system[resolved]
            tools[role] = {"invoke": invoked, "resolved": resolved, "sha256": row["sha256"],
                           "package": row["package"]}
        return {"model": model, "state": "authenticated_bytes_current", "profile": cap.PROFILE,
                "runtime": {"kind": runtime["kind"], "distro": runtime["distro"], "user": runtime["user"]},
                "evidence_id": hashlib.sha256(raw).hexdigest(), "tools": tools,
                "executable": {"path": executable, "sha256": native["sha256"], "bytes": native["bytes"]},
                "model_readiness": False}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
        # No raw exception text: it may contain a private authority filename.
        return unavailable


def prompt(manifest, install_root) -> str:
    facts = context(manifest, install_root)
    if facts is None:
        return ""
    return ("[AUTHENTICATED SHARED RUNTIME FACTS]\n" + json.dumps(facts, ensure_ascii=False, sort_keys=True)
        + "\nThese are host-owned facts from the last verified dependency profile, with signed evidence "
          "and file hashes rechecked without executing probes. A KI's authored defaults are not evidence "
          "that those paths exist. Use the exact recorded tools; do not substitute guessed MPI/compiler "
          "paths. This block grants no command permission. Current loader/package checks and project "
          "preflight remain execution gates. MPI/NetCDF capability and an executable hash do not prove "
          "that model build options, scientific settings, inputs or an official reference case match. "
          "Inspect the actual case metadata and build evidence before claiming compatibility; keep "
          "unverified choices explicit and use KDT for KI changes.")
