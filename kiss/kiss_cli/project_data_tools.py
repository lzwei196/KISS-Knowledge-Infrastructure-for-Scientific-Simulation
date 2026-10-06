"""Planning-only source authoring for trusted, reviewed local data adapters."""
from __future__ import annotations

import hashlib
import csv
import json
import uuid
from pathlib import Path


def write(project: Path, ki: str, name: str, source: str, purpose: str) -> dict:
    from ki_tools_common.flow import project_tools
    if not isinstance(name, str) or not isinstance(source, str) or purpose not in project_tools.PURPOSES:
        raise ValueError("provide a tool name, Python source and purpose reader, converter or check")
    if not source.strip() or len(source.encode("utf-8")) > 1_000_000:
        raise ValueError("project data source must be nonempty and at most 1 MB")
    project = Path(project).resolve()
    target = project_tools.source_path(project, ki, project_tools.directory(project, ki) / (name + ".py"))
    compile(source, str(target), "exec")
    data = source.encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Recheck after directory creation; never write through an existing link.
    project_tools.source_path(project, ki, target)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"ki": ki, "path": target.relative_to(project).as_posix(), "tool": str(target),
            "project_data_tool": {"version": 1, "purpose": purpose,
                "source_sha256": hashlib.sha256(data).hexdigest(), "arguments": [],
                "cwd": ".", "timeout_seconds": 120},
            "status": "prepared_for_review", "executed": False}


def invocation(flow, ki: str, tool: Path, step_id: str, args: dict) -> tuple[dict, list[str], Path, int]:
    from ki_tools_common.flow import project_tools
    from .flowgate import FlowDenied
    step = flow.check_step_tool(step_id, ki, tool)
    errors = project_tools.step_errors(step, flow.project)
    if errors:
        raise FlowDenied("; ".join(errors))
    binding = step["project_data_tool"]
    for key in ("arguments", "cwd", "timeout_seconds"):
        if key in args and args[key] != binding[key]:
            raise FlowDenied(f"project data {key} differs from the approved plan; revise before running")
    cwd = (flow.project / binding["cwd"]).resolve()
    for token in binding["arguments"]:
        value = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
        if "://" in value:
            raise FlowDenied("project data tools use local acquired files, not network URLs")
        if "/" in value or "\\" in value or Path(value).is_absolute():
            p = Path(value)
            p = (p if p.is_absolute() else cwd / p).resolve()
            if not p.is_relative_to(flow.project.resolve()):
                raise FlowDenied("project data argument path escapes the project")
    return step, list(binding["arguments"]), cwd, binding["timeout_seconds"]


def worker_request(project: Path, tool: Path, step: dict, inventory: dict, arguments: list[str]) -> dict:
    """Read grants come from this step's inventory, not the entire project."""
    project = Path(project).resolve()
    roots = []
    listings = []
    non_executable = []
    for item in inventory.get("items") or []:
        if item.get("id") not in step.get("inputs", []):
            continue
        for value in item.get("local_paths") or []:
            raw = Path(value)
            raw = raw if raw.is_absolute() else project / raw
            p = raw.resolve()
            if not p.is_relative_to(project) or p.parts[len(project.parts):len(project.parts)+1] not in {
                    ("inputs",), ("outputs",), ("artifacts",), ("references",)}:
                files, directory, case_root = _reference_case_inputs(project, step.get("ki"), raw)
                roots.extend(str(f) for f in files)
                if directory is not None:
                    listings.append(str(directory))
                non_executable.append(str(case_root))
                continue
            if not p.exists():
                raise ValueError(f"project data input does not exist: {value}")
            roots.append(str(p))
    if not roots:
        raise ValueError("project data tool needs at least one local input in its approved inventory")
    inputs = set()
    for value in roots:
        p = Path(value)
        for f in ([p] if p.is_file() else p.rglob("*")):
            if f.is_file():
                if not f.resolve().is_relative_to(p if p.is_dir() else p.parent):
                    raise ValueError("project data input directory contains an escaping link")
                inputs.add(str(f.resolve()))
                if len(inputs) > 256:
                    raise ValueError("project data tool input directory has over 256 files; name precise input files")
    if not inputs:
        raise ValueError("project data input directories contain no files")
    writes = [project / name for name in ("outputs", "artifacts")]
    if any(p.resolve() != p or p.is_symlink() for p in writes):
        raise ValueError("project data output directories cannot be links or resolve outside the project")
    return {"source": str(tool), "source_sha256": step["project_data_tool"]["source_sha256"],
            "arguments": arguments, "read_roots": sorted(set(roots)),
            "list_roots": sorted(set(listings)), "non_executable_roots": sorted(set(non_executable)),
            "write_roots": list(map(str, writes)), "input_files": sorted(inputs),
            "project": str(project)}


def _reference_case_inputs(project: Path, ki: str, path: Path) -> tuple[list[Path], Path | None, Path]:
    """Grant explicit retained case data, never the KI tree or its executable code."""
    from .project_paths import _model_home
    root = _model_home(project, ki) / "ki" / "test_cases"
    if (path.resolve() != path or root.resolve() != root or not path.is_relative_to(root)
            or len(path.relative_to(root).parts) < 2):
        raise ValueError("project data inputs must be acquired project files or explicit files in the selected KI's test_cases")
    relative = path.relative_to(root)
    directory = path if path.is_dir() else None
    if directory is not None and relative.parts[1] != "inputs":
        raise ValueError("reference case directory grants are limited to a declared case inputs/ directory")
    files = []
    for candidate in (path.rglob("*") if directory is not None else [path]):
        if candidate.resolve() != candidate or candidate.is_symlink():
            raise ValueError("reference case inputs must not contain links or escape the selected KI")
        if candidate.is_dir():
            continue
        if not candidate.is_file() or candidate.stat().st_nlink != 1:
            raise ValueError("reference case inputs must be existing ordinary unshared files")
        if candidate.suffix.lower() in {
                ".py", ".pyw", ".pyc", ".pyo", ".pyd", ".exe", ".dll", ".so", ".com",
                ".bat", ".cmd", ".ps1", ".sh", ".bash", ".r", ".rscript", ".jl", ".m",
                ".pl", ".rb", ".js", ".ts", ".jar", ".class", ".wasm"}:
            raise ValueError("reference case read grants cover data and metadata, not KI executable code")
        files.append(candidate)
        if len(files) > 256:
            raise ValueError("project data tool input directory has over 256 files; name precise input files")
    if not files:
        raise ValueError("reference case input directory contains no data files")
    return files, directory, root


def validate_outputs(project: Path, outputs: list[Path], exit_code: int | None,
                     *, input_files: list[str] | None = None) -> dict:
    """Validate data artifact structure, not scientific correctness or model readiness.

    Missing observation fields and quality flags are legitimate raw evidence.
    Do not apply the model's positive-flow/no-missing-output rules to a reader.
    """
    checks = [{"check": "data_tool_exit_zero", "ok": exit_code == 0, "level": "fail"},
              {"check": "data_artifacts_present", "ok": bool(outputs), "level": "fail"}]
    def bad_constant(value):
        raise ValueError(f"nonstandard JSON value {value}; represent missing data explicitly with null")
    def digest(path):
        result = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                result.update(block)
        return result.hexdigest()
    copies = {}
    for output in outputs:
        path = Path(output)
        ok, detail = False, ""
        copy_evidence = {}
        try:
            if not any(path.resolve().is_relative_to(Path(project).resolve() / root) for root in ("outputs", "artifacts")):
                raise ValueError("artifact is outside outputs/ or artifacts/")
            if not path.is_file() or not path.stat().st_size:
                raise ValueError("artifact is missing or empty")
            if path.suffix.lower() == ".json":
                if path.stat().st_size > 16_000_000:
                    raise ValueError("JSON report exceeds 16 MB; write tabular observations as CSV")
                doc = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=bad_constant)
                if not isinstance(doc, (dict, list)) or not doc:
                    raise ValueError("JSON report must be a nonempty object or array")
                detail = "parseable JSON; content/scientific claims require independent checks"
            elif path.suffix.lower() in {".csv", ".tsv"}:
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    rows = csv.reader(stream, delimiter="\t" if path.suffix.lower() == ".tsv" else ",", strict=True)
                    header = next(rows, [])
                    if not header or any(not x.strip() for x in header) or len(set(header)) != len(header):
                        raise ValueError("table needs unique nonempty column names")
                    count = 0
                    for row in rows:
                        if len(row) != len(header):
                            raise ValueError("table row width differs from its header")
                        count += 1
                    if not count:
                        raise ValueError("table has no records")
                    detail = f"{count} structurally complete rows; missing fields/flags preserved, scientific checks pending"
            elif path.suffix.lower() in {".txt", ".md"}:
                with path.open(encoding="utf-8") as stream:
                    if "\x00" in stream.read(120000):
                        raise ValueError("report contains binary content")
                detail = "text report only; not independent data or model validation"
            else:
                output_size = path.stat().st_size
                output_hash = digest(path)
                for value in input_files or []:
                    source = Path(value).resolve()
                    if (source == path.resolve() or not source.is_relative_to(Path(project).resolve())
                            or not source.is_file() or source.stat().st_size != output_size):
                        continue
                    if source not in copies:
                        copies[source] = digest(source)
                    if copies[source] == output_hash:
                        copy_evidence = {"scope": "unchanged_input_copy",
                                         "source": source.relative_to(Path(project).resolve()).as_posix(),
                                         "sha256": output_hash, "bytes": output_size}
                        detail = "exact bytes and SHA-256 match an explicitly granted input; no scientific validation"
                        break
                if not copy_evidence:
                    raise ValueError("data artifact format is unsupported; use JSON, CSV, TSV, a text report, or an unchanged copy of an explicitly granted input")
            ok = True
        except (OSError, ValueError, UnicodeError, csv.Error) as exc:
            detail = str(exc)
        checks.append({"check": f"data_artifact_structure:{path.name}", "ok": ok,
                       "detail": detail, "level": "fail", **copy_evidence})
    return {"status": "passed" if all(c["ok"] for c in checks) else "failed", "checks": checks,
            "scope": "data_execution_and_artifact_structure", "scientific_validation": "not_performed",
            "model_ready": False}
