"""Explicitly reviewed project data tools; never promoted to shipped KI tools."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import stat

PURPOSES = {"reader", "converter", "check"}
FIELDS = {"version", "purpose", "source_sha256", "arguments", "cwd", "timeout_seconds"}
OUTPUT_POLICY = "project-data-output-contracts-v2"
_PLACEHOLDER_RE = re.compile(r"\$\{[^}]*\}")


def _literal_invocation(value: str, field: str) -> None:
    if _PLACEHOLDER_RE.search(value):
        raise ValueError(
            f"project data {field} contains unresolved placeholders; use literal absolute or cwd-relative paths. "
            "${PROJECT}/${KI_ROOT} expansion is supported only in shipped-tool step.env, not adapter arguments/cwd")


def directory(project: Path, ki: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", ki).strip(".") or "KI"
    # Distinct selected names must not share a writable adapter directory.
    slug += "-" + hashlib.sha256(ki.encode()).hexdigest()[:8]
    return Path(project).resolve() / "project_tools" / slug


def source_path(project: Path, ki: str, tool: str | Path) -> Path:
    project = Path(project).resolve()
    p = Path(tool)
    p = p if p.is_absolute() else project / p
    parent = directory(project, ki)
    if p.parent != parent or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}\.py", p.name):
        raise ValueError("project data tool must be a named Python file in its selected KI's project_tools directory")
    if p.resolve() != p or any(x.is_symlink() for x in (p, parent, parent.parent)):
        raise ValueError("project data tool paths must not contain links or escape the project")
    if p.exists() and (not p.is_file() or p.stat().st_nlink != 1):
        raise ValueError("project data tool must be an ordinary unshared file")
    return p


def output_path(project: Path, value: str, *, require_file=False) -> Path:
    """An explicit output path grants nothing beyond the existing worker roots."""
    if not isinstance(value, str) or not value or len(value) > 4000 or "\0" in value:
        raise ValueError("typed output path must be a literal project-relative path")
    _literal_invocation(value, "output path")
    relative = Path(value)
    if (relative.is_absolute() or relative.drive or ".." in relative.parts
            or len(relative.parts) < 2 or relative.parts[0] not in {"outputs", "artifacts"}
            or relative.as_posix() != value):
        raise ValueError("typed output path must use literal outputs/ or artifacts/ paths without aliases or traversal")
    root = Path(project).resolve()
    path = root / relative
    for candidate in (path, *path.parents):
        if candidate == root:
            break
        if candidate.resolve() != candidate or candidate.is_symlink():
            raise ValueError("typed output paths must not contain aliases")
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise ValueError("typed output paths must not contain aliases")
        if candidate == path and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError("typed output must be an ordinary unshared file")
    if require_file and not path.is_file():
        raise ValueError("declared typed output file is missing")
    return path


def output_contracts(project: Path, contracts, output_ids=None) -> list[dict]:
    """Check explicit v2 format contracts; never infer a format from a suffix."""
    from .project_data_formats import validate_contract
    if not isinstance(contracts, list) or not 1 <= len(contracts) <= 100:
        raise ValueError("output_formats must be a nonempty list of at most 100 explicit contracts")
    seen_ids, seen_paths = set(), set()
    for contract in contracts:
        validate_contract(contract)
        ident = contract["output_id"]
        if ident in seen_ids or (output_ids is not None and ident not in output_ids):
            raise ValueError("typed output_id is duplicated or absent from this step's outputs")
        path = output_path(project, contract["path"])
        if path in seen_paths:
            raise ValueError("typed output paths must be distinct")
        seen_ids.add(ident)
        seen_paths.add(path)
    return contracts


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def output_validation_binding(step: dict) -> dict:
    from . import project_data_formats
    return {"policy": OUTPUT_POLICY,
            "binding_policy_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "step_sha256": _digest(step), "binding_sha256": _digest(step["project_data_tool"]),
            "validator_policy": project_data_formats.POLICY,
            "validator_source_sha256": project_data_formats.source_digest(),
            "contracts": step["project_data_tool"]["output_formats"]}


def typed_output_errors(project: Path, step: dict, validation: dict, receipt_outputs: list) -> list[str]:
    """Read-only completion check of signed v2 evidence and current output bytes."""
    try:
        if errors := step_errors(step, project):
            raise ValueError("; ".join(errors))
        checks = validation.get("checks")
        if (validation.get("status") != "passed" or not isinstance(checks, list) or not checks
                or any(not isinstance(check, dict) or check.get("ok") is not True for check in checks)):
            raise ValueError("typed data output validation did not pass every required check")
        if (validation.get("scope") != "data_execution_and_artifact_structure"
                or validation.get("scientific_validation") != "not_performed"
                or validation.get("model_ready") is not False):
            raise ValueError("typed data evidence cannot certify model readiness or scientific results")
        expected = output_validation_binding(step)
        typed = validation.get("typed_outputs")
        if not isinstance(typed, dict) or set(typed) != set(expected) | {"outputs"}:
            raise ValueError("typed output validation evidence is missing or incomplete")
        if any(typed.get(key) != value for key, value in expected.items()):
            raise ValueError("typed output contract or validator policy changed")
        reports = typed["outputs"]
        contracts = expected["contracts"]
        if not isinstance(reports, list) or len(reports) != len(contracts):
            raise ValueError("typed output evidence does not cover every declared format")
        by_path = {}
        for entry in receipt_outputs:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError("receipt output identity is invalid")
            if entry["path"] in by_path:
                raise ValueError("receipt output identities are duplicated")
            by_path[entry["path"]] = entry
        for contract, report in zip(contracts, reports):
            if not isinstance(report, dict):
                raise ValueError("typed output report is missing")
            path = output_path(project, contract["path"], require_file=True)
            size = path.stat().st_size
            recorded = by_path.get(contract["path"], {})
            if report.get("bytes") != size or recorded.get("bytes") != size:
                raise ValueError("typed output size differs from its reviewed evidence")
            hasher, remaining = hashlib.sha256(), size + 1
            with path.open("rb") as stream:
                while remaining:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    hasher.update(block)
                    remaining -= len(block)
            if remaining != 1:
                raise ValueError("typed output changed while its current identity was checked")
            digest = hasher.hexdigest()
            if (report.get("ok") is not True or report.get("policy") != expected["validator_policy"]
                    or report.get("policy_sha256") != expected["validator_source_sha256"]
                    or report.get("scientific_validation") != "not_performed" or report.get("model_ready") is not False
                    or any(report.get(key) != contract[key] for key in ("output_id", "path", "format"))
                    or report.get("sha256") != digest or report.get("bytes") != size
                    or recorded.get("sha256") != digest or recorded.get("bytes") != size
                    or recorded.get("missing")):
                raise ValueError("typed output lacks passing evidence for its exact current file")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
        return [str(exc)]
    return []


def step_errors(step: dict, project: Path | None) -> list[str]:
    try:
        if project is None:
            raise ValueError("project data tool requires the current project")
        binding = step.get("project_data_tool")
        if not isinstance(binding, dict):
            raise ValueError("project_data_tool must be an explicit binding object")
        version = binding.get("version")
        fields = FIELDS | {"output_formats"} if version == 2 else FIELDS
        if set(binding) != fields:
            raise ValueError("project_data_tool must contain version, purpose, source_sha256, arguments, cwd, timeout_seconds; version 2 also requires output_formats")
        if type(version) is not int or version not in {1, 2} or binding["purpose"] not in PURPOSES:
            raise ValueError("unsupported project data tool version or purpose")
        if step.get("kind") not in {"check", "prepare"} or "calibration" in step:
            raise ValueError("project data tools support only check or prepare steps, never model execution/calibration")
        if not Path(str(step.get("tool") or "")).is_absolute():
            raise ValueError("project data tool must be an absolute path for approval")
        if step.get("env"):
            raise ValueError("project data tools use their guarded runtime environment, not model environment overrides")
        p = source_path(project, str(step.get("ki") or ""), step.get("tool") or "")
        if not p.is_file():
            raise ValueError("project data tool source is missing; write_project_data_tool before submitting the plan")
        if binding["source_sha256"] != hashlib.sha256(p.read_bytes()).hexdigest():
            raise ValueError("project data tool source hash differs from the reviewed binding")
        args = binding["arguments"]
        if not isinstance(args, list) or len(args) > 100 or any(not isinstance(a, str) or len(a) > 4000 for a in args):
            raise ValueError("project data arguments must be a list of short strings")
        for argument in args:
            _literal_invocation(argument, "arguments")
        cwd = binding["cwd"]
        if not isinstance(cwd, str) or Path(cwd).is_absolute():
            raise ValueError("project data cwd must be project-relative")
        _literal_invocation(cwd, "cwd")
        resolved = (Path(project).resolve() / cwd).resolve()
        if not resolved.is_relative_to(Path(project).resolve()) or not resolved.is_dir():
            raise ValueError("project data cwd must exist inside the project")
        if type(binding["timeout_seconds"]) is not int or not 1 <= binding["timeout_seconds"] <= 600:
            raise ValueError("project data timeout must be an integer from 1 to 600 seconds")
        if not step.get("outputs"):
            raise ValueError("project data tool must declare its inspection report or converted outputs")
        if version == 2:
            output_contracts(project, binding["output_formats"], step["outputs"])
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        return [str(exc)]
    return []
