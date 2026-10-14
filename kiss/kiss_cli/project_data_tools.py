"""Planning-only source authoring for trusted, reviewed local data adapters."""
from __future__ import annotations

import hashlib
import csv
import json
import uuid
from pathlib import Path


def write(project: Path, ki: str, name: str, source: str, purpose: str, *, output_formats=None) -> dict:
    from ki_tools_common.flow import project_tools
    if not isinstance(name, str) or not isinstance(source, str) or purpose not in project_tools.PURPOSES:
        raise ValueError("provide a tool name, Python source and purpose reader, converter or check")
    if not source.strip() or len(source.encode("utf-8")) > 1_000_000:
        raise ValueError("project data source must be nonempty and at most 1 MB")
    project = Path(project).resolve()
    if output_formats is not None:
        project_tools.output_contracts(project, output_formats)
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
    binding = {"version": 2 if output_formats is not None else 1, "purpose": purpose,
                "source_sha256": hashlib.sha256(data).hexdigest(), "arguments": [],
                "cwd": ".", "timeout_seconds": 120,
                **({"output_formats": output_formats} if output_formats is not None else {})}
    return {"ki": ki, "path": target.relative_to(project).as_posix(), "tool": str(target),
            "project_data_tool": binding, "status": "prepared_for_review", "executed": False,
            "step_template": {"id": f"{ki}:{name}", "ki": ki, "kind": "prepare" if purpose == "converter" else "check",
                "tool": str(target), "project_data_tool": binding, "inputs": [],
                "outputs": [row["output_id"] for row in output_formats or []], "status": "planned"}}


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
    from ki_tools_common.flow import project_tools
    declared_outputs = set()
    inventory_outputs = {}
    for ident in step.get("outputs") or []:
        matches = [item for item in inventory.get("items") or [] if item.get("id") == ident]
        if len(matches) > 1:
            raise ValueError("project data output needs an unambiguous approved inventory item")
        inventory_outputs[ident] = set()
        for value in matches[0].get("local_paths") or [] if matches else []:
            raw = Path(value)
            relative = raw.relative_to(project).as_posix() if raw.is_absolute() else value
            output = project_tools.output_path(project, relative)
            inventory_outputs[ident].add(output)
            declared_outputs.add(output)
    # Explicit v2 format paths are part of the signed step even when an older
    # inventory used only symbolic output IDs. They grant exact files, never roots.
    for contract in step["project_data_tool"].get("output_formats") or []:
        output = project_tools.output_path(project, contract["path"])
        declared = inventory_outputs.get(contract["output_id"])
        if declared and declared != {output}:
            raise ValueError("project data output inventory path differs from its approved format path")
        declared_outputs.add(output)
    for output in declared_outputs:
        if any(output == Path(raw) or Path(raw) in output.parents for raw in roots):
            raise ValueError("an approved project data output cannot replace a consumed input")
    return {"source": str(tool), "source_sha256": step["project_data_tool"]["source_sha256"],
            "arguments": arguments, "read_roots": sorted(set(roots)),
            "list_roots": sorted(set(listings)), "non_executable_roots": sorted(set(non_executable)),
            "write_roots": list(map(str, writes)), "input_files": sorted(inputs),
            "declared_output_files": sorted(map(str, declared_outputs)),
            "project": str(project)}


def preserve_output_preimages(project: Path, request: dict, *, approval_sha256: str, step_id: str) -> dict | None:
    """Keep original bytes before granting an exact approved replacement write.

    The request is host-derived from the current signed plan, never a model
    argument. Failed attempts retain their original preimages as well as any
    partial result; no file is deleted, relabelled as input, or silently restored.
    """
    from . import artifact_archive
    from ki_tools_common.flow import project_tools, receipts
    project = Path(project).resolve()
    if not approval_sha256 or not step_id:
        raise ValueError("output replacement requires the current signed approval and step")
    existing = []
    for raw in request.get("declared_output_files") or []:
        path = project_tools.output_path(project, Path(raw).relative_to(project).as_posix())
        if any(path == Path(value) or Path(value) in path.parents for value in request["read_roots"]):
            raise ValueError("an approved project data output cannot replace a consumed input")
        if path.exists():
            existing.append((path, artifact_archive._hash(path)))
    if not existing:
        return None
    directory = project / ".geoforge" / "output-preimages" / uuid.uuid4().hex
    for parent in (directory.parent, directory):
        artifact_archive._ordinary(parent.parent, directory=True)
        parent.mkdir(exist_ok=True)
        artifact_archive._ordinary(parent, directory=True)
    rows = []
    for index, (path, (digest, size, fingerprint)) in enumerate(existing):
        saved = directory / f"{index:04d}.bin"
        with artifact_archive._open_read(path) as source, saved.open("xb") as target:
            remaining = size
            while remaining:
                block = source.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError("approved output changed while preserving its preimage")
                target.write(block)
                remaining -= len(block)
            if source.read(1):
                raise ValueError("approved output grew while preserving its preimage")
        if (artifact_archive._hash(path) != (digest, size, fingerprint)
                or artifact_archive._hash(saved)[:2] != (digest, size)):
            raise ValueError("approved output changed while preserving its preimage")
        rows.append({"path": path.relative_to(project).as_posix(), "bytes": size, "sha256": digest,
                     "preimage_path": saved.relative_to(project).as_posix()})
    manifest = directory / "manifest.json"
    doc = receipts.sign(project, {"schema_version": "1.0", "kind": "project_data_output_preimages",
        "approval_sha256": approval_sha256, "plan_step_id": step_id,
        "source_sha256": request["source_sha256"], "outputs": rows})
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(doc, stream, ensure_ascii=False, indent=2)
    return {"manifest": manifest.relative_to(project).as_posix(),
            "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(), "outputs": rows}


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
                     *, input_files: list[str] | None = None, step: dict | None = None) -> dict:
    """Validate data artifact structure, not scientific correctness or model readiness.

    Missing observation fields and quality flags are legitimate raw evidence.
    Do not apply the model's positive-flow/no-missing-output rules to a reader.
    """
    checks = [{"check": "data_tool_exit_zero", "ok": exit_code == 0, "level": "fail"},
              {"check": "data_artifacts_present", "ok": bool(outputs), "level": "fail"}]
    typed, contracts_by_path = None, {}
    if (isinstance(step, dict) and isinstance(step.get("project_data_tool"), dict)
            and step["project_data_tool"].get("version") == 2):
        from ki_tools_common.flow import project_data_formats, project_tools
        try:
            if errors := project_tools.step_errors(step, project):
                raise ValueError("; ".join(errors))
            contracts = step["project_data_tool"]["output_formats"]
            typed = {**project_tools.output_validation_binding(step), "outputs": []}
            contracts_by_path = {project_tools.output_path(project, contract["path"]): contract
                                 for contract in contracts}
            actual = [Path(path).absolute() for path in outputs]
            if len(set(actual)) != len(actual):
                raise ValueError("captured output paths are duplicated")
            for contract in contracts:
                path = project_tools.output_path(project, contract["path"], require_file=True)
                if path not in actual:
                    raise ValueError("declared typed output was not freshly captured: " + contract["path"])
                report = project_data_formats.validate_output(path, contract)
                typed["outputs"].append(report)
                checks.append({"check": "typed_output:" + contract["output_id"],
                               "ok": isinstance(report, dict) and report.get("ok") is True,
                               "detail": report.get("detail", "") if isinstance(report, dict) else "invalid format report",
                               "level": "fail"})
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            checks.append({"check": "typed_output_contract", "ok": False, "detail": str(exc), "level": "fail"})
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
        if path.absolute() in contracts_by_path:
            # An explicit format never falls back to extension-based acceptance,
            # including when its typed parser rejected the file.
            continue
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
    if typed is not None:
        try:
            current = project_tools.output_validation_binding(step)
            unchanged = all(typed.get(key) == value for key, value in current.items())
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
            unchanged = False
        checks.append({"check": "typed_output_policy_current", "ok": unchanged, "level": "fail"})
    return {"status": "passed" if all(c["ok"] for c in checks) else "failed", "checks": checks,
            "scope": "data_execution_and_artifact_structure", "scientific_validation": "not_performed",
            "model_ready": False, **({"typed_outputs": typed} if typed is not None else {})}
