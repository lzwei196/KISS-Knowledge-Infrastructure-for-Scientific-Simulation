"""Effective, read-only KI sources for task intake; never runtime bindings.

The catalogue's upstream identity stays stable while an approved portable repair
may supply the files. Project materialisation and verification happen later.
"""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
import tomllib

from . import ki_adaptations, paths


def saved_config(workdir: Path):
    """Read only this installation's saved config, repairing old TOML in memory."""
    workdir = Path(workdir).resolve()
    file = workdir / paths.CONFIG_NAME
    if not file.is_file():
        return None
    if file.stat().st_size > 1024 * 1024:
        raise ValueError("Saved installation config is too large for KI inspection")
    text = file.read_text(encoding="utf-8")
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raw = tomllib.loads(paths._repair_backslash_strings(text))
    settings, roles = raw.get("kiss", {}), raw.get("paths", {})
    if not isinstance(settings, dict) or not isinstance(roles, dict):
        raise ValueError("Invalid saved installation config for KI inspection")
    root = settings.get("root", str(workdir))
    if not isinstance(root, str) or Path(root).expanduser().resolve() != workdir:
        raise ValueError("Saved installation config belongs to another workspace")
    cfg = paths.KissConfig.default(workdir)
    for role, value in roles.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Invalid saved installation path: {role}")
        cfg.roles[role] = Path(value).expanduser()
    for key in ("python", "relocation"):
        if key in settings:
            if not isinstance(settings[key], str) or not settings[key].strip():
                raise ValueError(f"Invalid saved installation {key}")
            setattr(cfg, key, settings[key])
    return cfg


class ReadMap:
    """Host-only inspection authority, separate from FlowSession.ki_roots."""

    def __init__(self, entries, *, checks=None):
        self.entries = dict(entries)
        self._checks = dict(checks or {})
        self._names = {name.casefold(): name for name in self.entries}
        if len(self._names) != len(self.entries):
            raise ValueError("KI catalogue has ambiguous case-insensitive identities")

    def entry(self, name):
        canonical = self._names.get(str(name).casefold())
        if canonical is None:
            raise ValueError(f"Unknown KI for intake inspection: {name!r}")
        view = self.entries[canonical]
        if canonical in self._checks:
            if self._checks[canonical]() != view:
                raise ValueError("KI inspection context changed; refresh intake before reading its effective source")
        else:
            ki_adaptations.require_inspection_current(view)
        return view

    def resolve(self, name, relative):
        """Resolve explicit KI + relative path, or a library-prefixed path."""
        relative = str(relative or ".").replace("\\", "/")
        if (relative.startswith("/") or Path(relative).is_absolute() or PureWindowsPath(relative).drive
                or "\x00" in relative or ".." in relative.split("/")):
            raise ValueError("Intake KI paths must be contained relative paths")
        parts = [part for part in relative.split("/") if part not in {"", "."}]
        if name:
            view = self.entry(name)
            if parts and parts[0].casefold() in self._names:
                raise ValueError("With ki specified, use a path relative to that KI; omit the KI prefix")
        else:
            if not parts:
                raise ValueError("Choose a catalogue KI by name before reading its files")
            view = self.entry(parts.pop(0))
            if parts and parts[0].casefold() in self._names:
                raise ValueError("Use only one KI prefix in a library-relative path")
        root = Path(view["root"]).resolve()
        file = root.joinpath(*parts).resolve()
        if file != root and root not in file.parents:
            raise ValueError("Intake path escapes the effective KI package")
        return file, root

    def diagnostic_roots(self, name=None):
        names = [name] if name else list(self.entries)
        return [(view["model"], Path(view["root"]).resolve())
                for view in (self.entry(item) for item in names)]

    def read_roots(self, catalogue_root):
        """Compact grants: catalogue + exact external KI leaves, never registry parents."""
        base = Path(catalogue_root).resolve()
        roots = [base]
        for view in self.entries.values():
            root = Path(view["root"]).resolve()
            if root != base and base not in root.parents and root not in roots:
                roots.append(root)
        return roots


def build(catalog, *, workdir_for, manifest_for, library_root=None):
    """Resolve only known repairs; do not copy 127 KIs or invent installation config."""
    repaired = {name.casefold() for name in ki_adaptations.inspection_models()}
    entries, checks = {}, {}
    for ki in catalog:
        if ki.name.casefold() in repaired:
            def resolve(ki=ki):
                return ki_adaptations.inspection_source(
                    ki.root, saved_config(workdir_for(ki)), model=ki.name,
                    library_root=library_root, manifest=manifest_for(ki))
            view = resolve()
            checks[ki.name] = resolve
        else:
            view = {"model": ki.name, "source_root": str(ki.root), "root": str(ki.root),
                    "origin": "upstream", "can_run": False,
                    "notice": "Upstream KI for inspection; this view grants no verified readiness."}
        entries[ki.name] = view
    return ReadMap(entries, checks=checks)
