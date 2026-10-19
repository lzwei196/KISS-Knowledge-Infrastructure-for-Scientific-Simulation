"""Bind machine verification to the effective snapshot and its requirements."""
from __future__ import annotations

from .manifest import document as manifest_document
import hashlib
import json
from pathlib import Path

from . import helper_identity, install, ki_updates, ki_verification, paths


def runtime_binding(cfg) -> dict:
    """Identify checked path bindings, not the contents of an installed runtime.

    Keep launcher and role spelling: following a symlink can erase which
    virtual environment or versioned installation the user selected.
    """
    from . import runtime_context
    return {"schema_version": 2,
               "backend": runtime_context.binding(),
               "root": str(Path(cfg.root).expanduser().resolve()),
               "python": str(cfg.python),
               "roles": {name: str(value) for name, value in cfg.roles.items()},
               "relocation": cfg.relocation}


def runtime_identity(cfg) -> str:
    """Full readiness identity, including the application build and backend."""
    return hashlib.sha256(json.dumps(runtime_binding(cfg), sort_keys=True).encode()).hexdigest()


def projection_binding(cfg) -> dict:
    """Static path provenance; application upgrades still expire readiness.

    Keep exact workspace, machine, ownership and interpreter paths. App build,
    kernel and interpreter content/version still expire full readiness, but
    do not change role substitution. The host separately checks projection
    policy and reproduced KI bytes before renewing older provenance.
    """
    binding = runtime_binding(cfg)
    binding["backend"] = {key: value for key, value in binding["backend"].items()
                          if key != "source_hash"}
    if binding["backend"].get("kind") == "wsl" and "guest_path_identity" in binding["backend"]:
        binding["backend"].pop("guest_identity", None)
    return binding


def identity(ki, man, library_root: Path | None) -> str | None:
    """Bind snapshot readiness to relevant bytes, not an unrelated library update.

    Schema 2 deliberately invalidates older whole-snapshot receipts once. Only
    a fresh verification may establish this narrower identity; this function
    neither migrates a receipt nor grants package/adoption acceptance.
    """
    if library_root is None:
        return None
    root = Path(library_root)
    marker = root / ki_updates.SNAPSHOT_MANIFEST
    if not marker.is_file():
        return None
    try:
        source = Path(ki.root).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        if Path(ki.root).absolute().is_relative_to(root.absolute()):
            raise ValueError("Snapshot KI path escapes its library root")
        # A user-imported or application KI is not part of this snapshot.
        return None
    meta = ki_updates._read_json(marker)
    content = meta.get("content_sha256")
    trees = meta.get("trees")
    helpers = trees.get("shared_tools") if isinstance(trees, dict) else None
    if not content or not helpers:
        raise ValueError("Active KI snapshot lacks its verification identity")
    digest = ki_verification.content_digest(ki.root)
    if not digest:
        raise ValueError("Cannot fingerprint the selected snapshot KI")
    payload = {"schema_version": 2, "ki": source, "ki_content": digest,
               "shared_tools": helper_identity.source_identity(root),
               "effective_manifest": manifest_document(man)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


_REQUIREMENT_PROBE = r'''
import importlib.metadata as metadata
import json, sys
try:
    from packaging.requirements import Requirement
except ImportError:
    from pip._vendor.packaging.requirements import Requirement
failures = []
for value in json.loads(sys.argv[1]):
    try:
        requirement = Requirement(value)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        version = metadata.version(requirement.name)
        if requirement.url:
            failures.append(value + ': direct-source identity requires explicit verification')
        elif requirement.specifier and not requirement.specifier.contains(version, prereleases=True):
            failures.append(value + ': installed ' + version)
    except Exception as error:
        failures.append(str(value) + ': ' + str(error))
print('\n'.join(failures) if failures else 'Declared Python requirements satisfied')
raise SystemExit(bool(failures))
'''


def requirements(man, cfg, *, dependency_check=None) -> install.Step:
    """Check recorded runtime requirements; never install or run the model.

Native dependency profiles compile host-owned synthetic probes in the private
runtime area. Their evidence is separate from scientific model results.
"""
    failures = []
    commands = []
    native_evidence = {}
    from . import native_dependency_gate
    try:
        native_evidence = native_dependency_gate.verify(man, cfg)
    except (OSError, ValueError, RuntimeError) as error:
        failures.append("Native dependency capability check: " + str(error))
    from . import runtime_data
    data_check = runtime_data.check(man, cfg)
    if not data_check.ok:
        failures.append(data_check.detail)
    if man.python_deps:
        argv = [cfg.python, "-c", _REQUIREMENT_PROBE, json.dumps(man.python_deps)]
        env = paths.with_python_runtime(cfg.python, paths.with_ki_tools_common(cfg, {}))
        rc, output = install._run(argv, cwd=cfg.root, timeout=60, env=env)
        commands.append(f"{cfg.python} [declared Python requirement metadata check]")
        if rc:
            failures.append(output.strip()[-3000:] or "Python requirement check failed")
    for name in man.depends_on:
        try:
            ready = dependency_check(name) if dependency_check is not None else False
        except (KeyError, ValueError, OSError):
            ready = False
        if not ready:
            failures.append(f"Coupled KI requires current verification: {name}")
    evidence = {"runtime_data": data_check.evidence} if data_check.evidence else {}
    if native_evidence:
        evidence["native_dependencies"] = native_evidence
    return install.Step("manifest-requirements", not failures,
                        "\n".join(failures) if failures else "Current manifest requirements satisfied",
                        commands=commands, evidence=evidence)
