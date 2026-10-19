"""Planning-only source authoring for trusted, reviewed local data adapters."""
from __future__ import annotations

import hashlib
import csv
import json
import uuid
from pathlib import Path


MAX_WORKER_REQUEST_BYTES = 8 * 1024 * 1024


def encode_worker_request(request: dict) -> bytes:
    """Transport exact grants via a bounded private stream, not argv."""
    raw = json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_WORKER_REQUEST_BYTES:
        raise ValueError("project data invocation exceeds the 8 MiB request limit")
    return raw


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


def _declared_output_paths(project: Path, step: dict, inventory: dict) -> dict[str, set[Path]]:
    """Use the review resolver without invalidating already signed symbolic plans."""
    from ki_tools_common.flow.plan import project_data_output_paths
    return project_data_output_paths(step, inventory, project, allow_legacy_symbolic=True)


def require_ki_data_source(project: Path, ki: str, root: Path) -> dict:
    """Authenticate current immutable case bytes; never enroll or repair a KI."""
    from . import ki_adaptations, ki_data_lineage, ki_guard, project_paths
    expected = project_paths._model_home(Path(project).resolve(), ki) / "ki"
    if Path(root).absolute() != expected:
        raise ValueError("bundled data does not belong to the selected project KI")
    try:
        cfg = project_paths.load_model_config(project, ki)
        ki_guard.require_intact(root, required=True)
        proof = ki_data_lineage.require_projection(project, ki, root, cfg)
    except (ki_guard.KIIntegrityError, ki_adaptations.AdaptationError) as error:
        raise ValueError(str(error)) from error
    if proof is None:
        raise ValueError("bundled KI data requires a current signed project projection; refresh its workspace")
    return proof


def worker_request(project: Path, tool: Path, step: dict, inventory: dict, arguments: list[str],
                   *, selected_ki_root: Path | None = None) -> dict:
    """Read grants come from this step's inventory, not the entire project."""
    project = Path(project).resolve()
    roots = []
    listings = []
    non_executable = []
    from ki_tools_common.flow import project_inputs
    project_inputs.require_input_ids(step)
    authenticated = {}
    def authority(project, ki, root):
        if root not in authenticated:
            authenticated[root] = require_ki_data_source(project, ki, root)
        return authenticated[root]
    for item in inventory.get("items") or []:
        if item.get("id") not in step.get("inputs", []):
            continue
        for value in item.get("local_paths") or []:
            files, directory, case_root = project_inputs.grant(project, step.get("ki"), value,
                selected_ki_root=selected_ki_root, authority=authority)
            roots.extend(str(f) for f in files)
            if directory is not None:
                listings.append(str(directory))
            if case_root is not None:
                non_executable.append(str(case_root))
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
    resolved_outputs = _declared_output_paths(project, step, inventory)
    declared_outputs = {path for paths in resolved_outputs.values() for path in paths}
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
    """Legacy helper delegates to the same planning/runtime input predicate."""
    from ki_tools_common.flow import project_inputs
    return project_inputs.grant(project, ki, path)


def validate_outputs(project: Path, outputs: list[Path], exit_code: int | None,
                     *, input_files: list[str] | None = None, step: dict | None = None,
                     inventory: dict | None = None, input_snapshot: dict | None = None) -> dict:
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
    archive_copies = None
    empty_archive_outputs = set()
    has_archives = any(str(value).lower().endswith((".tar", ".tar.gz", ".tgz", ".zip"))
                       for value in input_files or [])
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
            if not path.is_file():
                raise ValueError("artifact is missing")
            output_size = path.stat().st_size
            output_hash = None
            basic = path.suffix.lower() in {".json", ".csv", ".tsv", ".txt", ".md"}
            if not basic and output_size:
                # Preserve the existing whole-input copy route and its evidence.
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
            if not copy_evidence and has_archives:
                from .archive_input_copies import ArchiveCopies
                if archive_copies is None:
                    archive_copies = ArchiveCopies(project, input_files or [], input_snapshot)
                copy_evidence = archive_copies.match(output_size, output_hash or digest(path), output=path) or {}
                if copy_evidence:
                    detail = ("exact bytes and SHA-256 match a regular member of an approved input archive; "
                              "input preparation only, no scientific validation")
                    if output_size == 0:
                        empty_archive_outputs.add(path.absolute())
            if copy_evidence:
                pass  # Raw preservation, even if the original JSON/CSV is not parseable.
            elif not output_size:
                raise ValueError("artifact is empty without an exact path-bound approved archive member")
            elif path.suffix.lower() == ".json":
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
                raise ValueError("data artifact format is unsupported; use JSON, CSV, TSV, a text report, "
                                 "or an unchanged copy of an explicitly granted input or approved archive member")
            ok = True
        except (OSError, ValueError, UnicodeError, csv.Error) as exc:
            detail = str(exc)
        checks.append({"check": f"data_artifact_structure:{path.name}", "ok": ok,
                       "detail": detail, "level": "fail", **copy_evidence})
    if inventory is not None and isinstance(step, dict) and "project_data_tool" in step:
        try:
            declared = _declared_output_paths(project, step, inventory)
            actual = {Path(path).absolute() for path in outputs}
            for ident, paths in declared.items():
                for path in sorted(paths):
                    checks.append({"check": "declared_data_output_fresh:" + ident,
                        "ok": path in actual and path.is_file()
                              and (path.stat().st_size > 0 or path in empty_archive_outputs),
                        "detail": f"{ident}: {path.relative_to(Path(project).resolve()).as_posix()} "
                                  "must be freshly captured and nonempty, or an exact path-bound empty archive member",
                        "level": "fail"})
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            checks.append({"check": "declared_data_output_contract", "ok": False,
                           "detail": str(exc), "level": "fail"})
    if archive_copies is not None:
        try:
            archive_copies.require_current()
            checks.append({"check": "archive_copy_inputs_current", "ok": True, "level": "fail"})
        except (OSError, ValueError) as exc:
            checks.append({"check": "archive_copy_inputs_current", "ok": False,
                           "detail": str(exc), "level": "fail"})
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
