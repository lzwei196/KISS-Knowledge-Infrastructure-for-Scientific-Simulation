"""Join project-owned scenario paths to one KI's shared installation.

``model_config`` is the resolution seam: it never borrows another model's
runtime or private output role. Save its result at ``models/<KI>/kiss.toml``.
The optional project-root config is model-neutral; execution must select a KI
and use ``load_model_config``, not discover a runtime by walking upward.

Resolution does not create directories or save configurations. Existing config
parsing uses KissConfig's compatibility reader (which may repair legacy Windows
TOML quoting). Unsafe saved scenario overrides are ignored when resolving;
loading a saved execution config instead rejects them. Malformed configs are
reported rather than silently throwing away user settings.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

from .paths import CONFIG_NAME, KissConfig


_SCENARIO_ROLES = (
    "data", "forcing", "obs", "static", "outputs", "outputs_disk1",
    "data_ki", "forcing_rechunked",
)
_SOFTWARE_ROLES = ("binaries", "python_env", "ki_tools_common", "home")


def _model_home(project: Path, name: str) -> Path:
    if (not isinstance(name, str) or not name or name in (".", "..") or
            "/" in name or "\\" in name):
        raise ValueError("KI name must be one nonempty directory component")
    home = project / "models" / name
    if home.resolve() != home:
        raise ValueError("KI configuration directory is aliased outside its own model path")
    return home


def _read_exact(folder: Path) -> KissConfig | None:
    config = folder / CONFIG_NAME
    if not config.exists():
        return None
    if not config.resolve().is_relative_to(folder.resolve()):
        raise ValueError("KI/project configuration file points outside its directory")
    # Do NOT use load(folder): its ancestor fallback is precisely what makes a
    # missing model config silently inherit another model's runtime.
    return KissConfig._parse(config)


def _known_models(project: Path) -> set[str]:
    folder = project / "models"
    return {p.name for p in folder.iterdir() if p.is_dir()} if folder.is_dir() else set()


def _owned_path(value: Path, saved_root: Path, project: Path) -> Path | None:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project / path
    elif saved_root.is_absolute() and saved_root != project:
        # A project move must not strand its own absolute roles. External
        # software paths are handled separately and never rebased here.
        try:
            path = project / path.relative_to(saved_root)
        except ValueError:
            pass
    resolved = path.resolve()
    return resolved if resolved.is_relative_to(project) else None


def _foreign_private(path: Path, project: Path, model: str | None,
                     known: set[str], role: str) -> bool:
    parts = path.relative_to(project).parts
    if len(parts) < 2:
        return False
    if parts[0] == "models":
        return parts[1] != model
    if parts[0] == "outputs":
        # Project-wide input roles must not secretly name a KI's private deck.
        # An explicitly saved per-KI custom output name remains valid unless
        # it names a known OTHER KI.
        # Explicitly saved INPUT roles may consume another KI's produced
        # artifact: that is a real coupling, not ownership of its outputs.
        return (model is None or
                (role in ("outputs", "outputs_disk1") and
                 parts[1] in known and parts[1] != model))
    return False


def _overrides(saved: KissConfig, project: Path, model: str | None,
               known: set[str], *, strict: bool = False) -> dict[str, Path]:
    result = {}
    for role in _SCENARIO_ROLES:
        value = saved.roles.get(role)
        if value is None:
            continue
        resolved = _owned_path(value, saved.root, project)
        if resolved is None or _foreign_private(resolved, project, model, known, role):
            if strict:
                raise ValueError(f"{role} is not owned by this project/KI")
            continue
        result[role] = resolved
    return result


def _check_ambiguous_inputs(saved: KissConfig, project: Path, model: str,
                            known: set[str]) -> None:
    """Do not mistake a contaminated saved config for intentional coupling."""
    foreign_namespaces = set()
    for role in ("outputs", "outputs_disk1"):
        value = saved.roles.get(role)
        path = _owned_path(value, saved.root, project) if value is not None else None
        if path is not None and _foreign_private(path, project, model, known, role):
            foreign_namespaces.add(path.relative_to(project).parts[:2])
    if not foreign_namespaces:
        return
    for role in _SCENARIO_ROLES:
        if role in ("outputs", "outputs_disk1"):
            continue
        value = saved.roles.get(role)
        path = _owned_path(value, saved.root, project) if value is not None else None
        if path is not None and path.relative_to(project).parts[:2] in foreign_namespaces:
            raise ValueError(
                f"Ambiguous {model} input/output ownership: {role} and an output role "
                "both point into another KI's private output tree. Please review "
                f"models/{model}/{CONFIG_NAME}, restore this KI's own output roles, "
                "and explicitly confirm any intended upstream input coupling. "
                "No saved bindings have been changed.")


def _base(project: Path, model: str | None = None) -> KissConfig:
    cfg = KissConfig.default(project)
    cfg.relocation = "none"
    cfg.roles.update({
        "data": project / "inputs",
        "forcing": project / "inputs" / "forcing",
        "obs": project / "inputs" / "observations",
        "static": project / "inputs" / "static",
        "data_ki": project / "inputs",
        "forcing_rechunked": project / "inputs" / "forcing" / "rechunked",
        "outputs": project / "outputs" / model if model else project / "outputs",
        "outputs_disk1": project / "outputs" / model if model else project / "outputs",
    })
    for role in _SCENARIO_ROLES:
        resolved = cfg.roles[role].resolve()
        if not resolved.is_relative_to(project):
            raise ValueError(f"default {role} directory points outside the project")
        if model and role in ("outputs", "outputs_disk1") and not resolved.is_relative_to(project / "outputs" / model):
            raise ValueError(f"default {role} directory is aliased outside its model path")
        cfg.roles[role] = resolved
    return cfg


def _is_neutral(saved: KissConfig, project: Path) -> bool:
    # The neutral config carries project/runtime identity, never an install's
    # binaries/home or a model-specific output owner. Python is intentionally
    # supplied by Desktop, not by any KI.
    return all(_owned_path(saved.roles.get(role, Path("/")), saved.root, project) == expected
               for role, expected in (
                   ("binaries", project / "binaries"),
                   ("home", project),
                   ("outputs", project / "outputs"),
                   ("outputs_disk1", project / "outputs")))


def _legacy_owner(saved: KissConfig, project: Path, model: str,
                  shared: KissConfig, known: set[str]) -> bool:
    same_install = (saved.roles.get("binaries") == shared.roles.get("binaries") and
                    saved.roles.get("home") == shared.roles.get("home") and
                    saved.python == shared.python)
    owners = set()
    for role in ("outputs", "outputs_disk1"):
        value = saved.roles.get(role)
        path = _owned_path(value, saved.root, project) if value is not None else None
        if path is not None:
            parts = path.relative_to(project).parts
            if len(parts) >= 2 and parts[0] == "outputs":
                owners.add(parts[1])
    if owners:
        # Old multi-KI globals may already have a first-KI output role and a
        # last-KI runtime. Conflicting identities are not migration authority.
        return owners == {model} and (known == {model} or same_install)
    # Legacy single-KI config may predate materialization or use a custom deck
    # at the project root. Require matching installation identity, not just a
    # shared executable name such as "python3".
    return (not known or known == {model}) and same_install


def model_config(project: Path, model_name: str, shared: KissConfig) -> KissConfig:
    """Resolve one KI; per-KI saved scenario roles win over legacy globals.

    ``shared`` is the current installation registry's config for this exact KI.
    Its Python and software roles always win. Outside-project or known foreign
    model-private scenario overrides do not migrate. No filesystem writes are
    needed except KissConfig's existing legacy-TOML compatibility repair.
    """
    project = Path(project).expanduser().resolve()
    home = _model_home(project, model_name)
    known = _known_models(project) | {model_name}
    cfg = _base(project, model_name)
    saved = _read_exact(home)
    if saved is not None:
        _check_ambiguous_inputs(saved, project, model_name, known)
        cfg.roles.update(_overrides(saved, project, model_name, known))
    else:
        legacy = _read_exact(project)
        if legacy is not None:
            if _is_neutral(legacy, project):
                common = _overrides(legacy, project, None, known)
                cfg.roles.update({k: v for k, v in common.items()
                                  if k not in ("outputs", "outputs_disk1")})
            elif _legacy_owner(legacy, project, model_name, shared, _known_models(project)):
                cfg.roles.update(_overrides(legacy, project, model_name, known))
    cfg.python = shared.python
    for role in _SOFTWARE_ROLES:
        cfg.roles[role] = shared.roles[role]
    return cfg


def project_config(project: Path, *, python: str) -> KissConfig:
    """Return model-neutral project roles with an explicit Desktop interpreter.

    This is NOT a model execution config. Save it at the project root; model
    callers must load their own config. Only already-neutral common input
    overrides survive here, never a legacy KI's private deck/runtime.
    """
    if not isinstance(python, str) or not python.strip():
        raise ValueError("Desktop interpreter must be explicit")
    project = Path(project).expanduser().resolve()
    cfg = _base(project)
    saved = _read_exact(project)
    if saved is not None and _is_neutral(saved, project):
        cfg.roles.update(_overrides(saved, project, None, _known_models(project)))
    cfg.python = python
    return cfg


def can_write_project_config(project: Path, migrated_models) -> bool:
    """Whether neutralizing the root would preserve its legacy KI bindings.

    Call AFTER saving the selected models' exact configs. A legacy config is
    retired only if one selected, captured KI accounts for its output owner,
    installation identity and scenario roles. Unknown/unselected owners or
    conflicting evidence leave the root untouched; it is never execution
    authority for a materialized KI. This predicate writes no registry.
    """
    project = Path(project).expanduser().resolve()
    config = project / CONFIG_NAME
    if not config.exists():
        return not config.is_symlink()
    try:
        legacy = _read_exact(project)
        if legacy is None:
            return False
        known_roles = set(_SCENARIO_ROLES + _SOFTWARE_ROLES + ("ki_root", "server_root"))
        if set(legacy.roles) - known_roles:
            return False  # cannot silently retire unrecognised custom roles
        if _is_neutral(legacy, project):
            # Neutral ownership does not mean every saved binding can be
            # regenerated. Preserve the root if a custom software role or an
            # unsafe/foreign scenario override would be dropped by rewriting.
            neutral = _base(project)
            neutral.roles.update(_overrides(legacy, project, None, _known_models(project)))
            return all(_owned_path(value, legacy.root, project) == neutral.roles.get(role)
                       for role, value in legacy.roles.items())
        owners = set()
        for role in ("outputs", "outputs_disk1"):
            value = legacy.roles.get(role)
            path = _owned_path(value, legacy.root, project) if value is not None else None
            if path is not None:
                parts = path.relative_to(project).parts
                if len(parts) >= 2 and parts[0] == "outputs":
                    owners.add(parts[1])
        captured_owners = []
        for name in set(migrated_models):
            if owners and owners != {name}:
                continue
            captured = _read_exact(_model_home(project, name))
            if captured is None or captured.python != legacy.python:
                continue
            if any(captured.roles.get(role) != legacy.roles.get(role)
                   for role in _SOFTWARE_ROLES):
                continue
            for role in _SCENARIO_ROLES:
                source = legacy.roles.get(role)
                target = captured.roles.get(role)
                if source is None:
                    continue
                before = _owned_path(source, legacy.root, project)
                after = _owned_path(target, captured.root, project) if target is not None else None
                if before is None or before != after:
                    break
            else:
                captured_owners.append(name)
        return len(captured_owners) == 1
    except (OSError, ValueError, TypeError):
        return False  # inability to prove retirement is not permission to erase


def load_model_config(project: Path, model_name: str) -> KissConfig:
    """Load the exact materialized KI config for execution; never use globals.

    Missing, malformed or unsafe configs raise instead of choosing another
    model's interpreter. Call ``model_config`` with the current installation
    first when refreshing a KI; this loader cannot rediscover moved software.
    """
    project = Path(project).expanduser().resolve()
    home = _model_home(project, model_name)
    saved = _read_exact(home)
    if saved is None:
        raise FileNotFoundError(f"no model-specific {CONFIG_NAME} for {model_name}; refresh its project workspace")
    _check_ambiguous_inputs(saved, project, model_name, _known_models(project) | {model_name})
    roles = _overrides(saved, project, model_name, _known_models(project) | {model_name}, strict=True)
    saved.root = project
    saved.roles.update(roles)
    saved.roles["ki_root"] = project / "models"
    saved.roles["server_root"] = project
    return saved


def execution_config(project: Path, model_name: str, ki_root: Path,
                     fallback: KissConfig | None = None) -> KissConfig:
    """Select the runtime for the KI actually being executed.

    Materialized KIs require their exact per-KI config, including when a caller
    supplied a fallback. A legacy non-materialized KI may use an explicitly
    supplied config; the caller must establish that this is a single-KI flow
    before passing it. No project/ancestor config is inferred here. The
    returned config's root remains the project (not its discovery directory).
    """
    project = Path(project).expanduser().resolve()
    home = _model_home(project, model_name)
    expected = home / "ki"
    candidate = Path(ki_root).expanduser()
    if not candidate.is_absolute():
        candidate = project / candidate
    # Normalize '..' without erasing symlink provenance: both the requested
    # namespace and real location matter when deciding if this is materialized.
    candidate = Path(os.path.abspath(candidate))
    real = candidate.resolve()
    namespace = project / "models"
    materialized = candidate.is_relative_to(namespace) or real.is_relative_to(namespace)
    if materialized and (real != expected or
                         (candidate.is_relative_to(namespace) and candidate != expected)):
        raise ValueError("KI root does not match this project's selected model workspace")

    exact = home / CONFIG_NAME
    if materialized or exact.exists() or exact.is_symlink():
        return load_model_config(project, model_name)
    if fallback is None:
        raise FileNotFoundError(f"no model-specific {CONFIG_NAME} for {model_name}; explicit single-KI legacy config required")
    # Do not mutate a caller's install/session config when anchoring execution
    # to the project. Existing explicit role mappings remain the legacy policy.
    cfg = copy.copy(fallback)
    cfg.roles = dict(fallback.roles)
    cfg.root = project
    return cfg
