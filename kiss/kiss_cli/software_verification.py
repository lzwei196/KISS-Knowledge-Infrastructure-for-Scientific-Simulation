"""Bind machine verification to the effective snapshot and its requirements."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from . import install, ki_updates, paths


def identity(ki, man, library_root: Path | None) -> str | None:
    """Bundled legacy installs retain their behavior; snapshots require evidence."""
    if library_root is None:
        return None
    root = Path(library_root)
    marker = root / ki_updates.SNAPSHOT_MANIFEST
    if not marker.is_file():
        return None
    try:
        source = Path(ki.root).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        # A user-imported or application KI is not part of this snapshot.
        return None
    meta = ki_updates._read_json(marker)
    content = meta.get("content_sha256")
    helpers = (meta.get("trees") or {}).get("shared_tools")
    if not content or not helpers:
        raise ValueError("Active KI snapshot lacks its verification identity")
    payload = {"schema_version": 1, "ki": source, "library_content": content,
               "shared_tools": helpers, "effective_manifest": asdict(man)}
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
    """Read-only check in the recorded interpreter; never install or run a model."""
    failures = []
    commands = []
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
    return install.Step("manifest-requirements", not failures,
                        "\n".join(failures) if failures else "Current manifest requirements satisfied",
                        commands=commands)
