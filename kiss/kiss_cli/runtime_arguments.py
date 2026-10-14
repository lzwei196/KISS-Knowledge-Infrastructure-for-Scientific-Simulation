"""Constrain tool path arguments and expose a checked native runtime by name.

This is an argument capability for trusted KI tools, not an OS sandbox. A
binding pins the declaration's resolved location, not executable contents.
"""
from __future__ import annotations

import os
from pathlib import Path
import re


def _lexical(path) -> Path:
    return Path(os.path.abspath(Path(path).expanduser()))


def declared_runtime_bindings(ki_root) -> dict[str, str]:
    """Snapshot exact declared native paths, including their external aliases.

    Use the existing shared declaration policy for eligibility. Preserve the
    declaration spelling as well as its target so swapping external aliases
    cannot preserve a set of resolved binaries and silently change a binding.
    """
    from ki_tools_common.flow.tools import declared_binaries, _INTERPRETER
    import yaml

    document = Path(ki_root) / "knowledge_infrastructure.yaml"
    if not document.is_file() or document.is_symlink():
        return {}
    try:
        data = yaml.safe_load(document.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        eligible = declared_binaries(Path(ki_root))
        candidates = []
        for holder in [data, *(v for v in data.values() if isinstance(v, dict))]:
            binary = holder.get("binary")
            if isinstance(binary, dict) and binary.get("path"):
                candidates.append(binary["path"])
            for binary in holder.get("binaries") or []:
                if isinstance(binary, dict) and binary.get("path"):
                    candidates.append(binary["path"])
        result = {}
        for raw in candidates:
            candidate = Path(str(raw).strip("'\""))
            if not candidate.is_absolute() or candidate.suffix.casefold() not in {"", ".exe"}:
                continue
            resolved = candidate.resolve(strict=True)
            if (resolved in eligible and resolved.suffix.casefold() in {"", ".exe"}
                    and not _INTERPRETER.match(resolved.name)):
                result[str(_lexical(candidate))] = str(resolved)
        return result
    except (OSError, ValueError, RuntimeError, TypeError, AttributeError, yaml.YAMLError):
        # A malformed/non-native declaration grants no external path capability.
        return {}


def _runtime_option(option: str, model: str) -> bool:
    model = re.sub(r"[^a-z0-9]+", "_", model.casefold()).strip("_")
    allowed = {"--binary", "--executable", "--exe"}
    if model:
        for spelling in {model, model.replace("_", "-")}:
            for suffix in ("exe", "binary", "executable"):
                allowed.update({f"--{spelling}_{suffix}", f"--{spelling}-{suffix}"})
    return option in allowed


def validate(*, project, ki, ki_root, cfg, arguments, cwd, allow_runtime=False) -> None:
    """Check API and CLI arguments immediately before common dispatch.

    Only an exact named native runtime or declared support-data root can leave
    project/KI confinement. This is a trusted-tool argument capability, not an
    OS read/write sandbox. Neither allowance grants arbitrary parent/subtrees.
    Project-authored data tools never receive this additional capability.
    """
    project, root, cwd = (Path(value).resolve() for value in (project, ki_root, cwd))
    if (not isinstance(arguments, list) or len(arguments) > 100 or
            not all(isinstance(value, str) and len(value) <= 4000 for value in arguments)):
        raise ValueError("arguments must be a list of short strings")
    receipt = None
    for index, token in enumerate(arguments):
        option = ""
        value = token
        if token.startswith("-") and "=" in token:
            option, value = token.split("=", 1)
        elif index and arguments[index - 1].startswith("--") and "=" not in arguments[index - 1]:
            option = arguments[index - 1]
        # Bare filenames can themselves be links; '..' and '~' need the same
        # containment check as strings containing a separator. Non-path scalar
        # values and option names simply resolve below cwd and grant nothing.
        candidate = Path(value).expanduser()
        if candidate.drive and not candidate.is_absolute():
            raise ValueError("tool argument must not use a drive-relative path: " + value)
        candidate = _lexical(candidate if candidate.is_absolute() else cwd / candidate)
        resolved = candidate.resolve()
        if any(resolved == base or base in resolved.parents for base in (project, root)):
            continue
        if allow_runtime and (_runtime_option(option, ki) or option == "--runtime-data"):
            if receipt is None:
                from .catalog import KI
                from . import project_verification, software_verification
                checked = project_verification.status(project, KI(ki, Path(ki_root)))
                if not checked["can_run"]:
                    raise ValueError("External runtime requires current project verification: " + checked["detail"])
                receipt = checked["receipt"]
                if software_verification.runtime_identity(cfg) != receipt["runtime_identity"]:
                    raise ValueError("External runtime launch configuration differs from verified bindings")
            # Verified installers may place an engine under home rather than
            # binaries. Only the exact signed native declaration is usable;
            # neither saved installation role grants its directory tree.
            roles = getattr(cfg, "roles", {}) or {}
            if _runtime_option(option, ki):
                bindings = receipt["declared_runtime_bindings"]
                if (any(roles.get(role) and candidate.is_relative_to(_lexical(roles[role]))
                        for role in ("binaries", "home")) and
                        bindings.get(str(candidate)) == str(resolved) and resolved.is_file()):
                    continue
            elif option == "--runtime-data":
                # status() rechecks the contract, aliases and all actual file
                # hashes. Passing a directory is restricted to this exact
                # declared input root; output flags and descendants stay denied.
                data = receipt.get("runtime_data")
                if (isinstance(data, dict) and data.get("ok") is True and
                        candidate == Path(data["target_root"]) and candidate == resolved and
                        resolved.is_dir()):
                    continue
        raise ValueError("tool argument path escapes the project and KI: " + value)
