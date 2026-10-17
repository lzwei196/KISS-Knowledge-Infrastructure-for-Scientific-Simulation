"""One planning/execution contract for reviewed project-data input grants."""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
import stat

PROJECT_DATA_ROOTS = {"inputs", "outputs", "artifacts", "references"}
CODE_SUFFIXES = {".py", ".pyw", ".pyc", ".pyo", ".pyd", ".exe", ".dll", ".so", ".com",
    ".bat", ".cmd", ".ps1", ".sh", ".bash", ".r", ".rscript", ".jl", ".m", ".pl",
    ".rb", ".js", ".ts", ".jar", ".class", ".wasm"}


def require_input_ids(step: dict) -> None:
    """Project data tools consume declared inputs; acquisition may bind paths later."""
    ids = step.get("inputs")
    if not isinstance(ids, list) or not any(isinstance(value, str) and value.strip() for value in ids):
        raise ValueError("project data tool requires at least one declared input: add each source to the "
                         "inventory and include its ID in step.inputs; zero-input project data tools are not supported")


def _ordinary(path: Path, root: Path, *, data=False) -> None:
    for current in (path, *path.parents):
        info = current.lstat()
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400):
            raise ValueError("KI data inputs must not contain links or reparse points")
        if current == root:
            break
    if data:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("KI data inputs must be existing ordinary unshared files")
        if path.suffix.lower() in CODE_SUFFIXES:
            raise ValueError("KI data grants cover data and metadata, not executable code")
        with path.open("rb") as source:
            prefix = source.read(4)
        if prefix[:2] in {b"MZ", b"#!"} or prefix in {
                b"\x7fELF", b"\x00asm", b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
                b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"}:
            raise ValueError("KI data input has executable content")


def grant(project: Path, ki: str, raw: str | Path, *, selected_ki_root=None,
          authority=None, allow_missing=False) -> tuple[list[Path], Path | None, Path | None]:
    """Return exact reads, optional listing, and a non-executable KI root.

    Outside conventional test_cases, only an individual explicitly named file
    in the current selected project KI is eligible. The host must authenticate
    its immutable projection. A directory name never grants the KI tree.
    """
    from .receipts import _input_path
    project = Path(project).resolve()
    spelling = str(raw)
    if ".." in Path(spelling).parts or ".." in PureWindowsPath(spelling).parts:
        raise ValueError("project data input paths cannot contain traversal")
    path = _input_path(project, spelling)
    relative = path.relative_to(project) if path.is_relative_to(project) else None
    if relative and relative.parts[0] in PROJECT_DATA_ROOTS:
        if not path.exists() and not allow_missing:
            raise ValueError("project data input does not exist: " + spelling)
        return [path], None, None
    if not isinstance(ki, str) or not ki or ki in {".", ".."} or "/" in ki or "\\" in ki:
        raise ValueError("project data input must name one selected KI")
    root = project / "models" / ki / "ki"
    if root.resolve() != root or not path.is_relative_to(root):
        raise ValueError("project data inputs must be project data or explicit data files in the selected project KI")
    case_root = root / "test_cases"
    if path.is_relative_to(case_root):
        parts = path.relative_to(case_root).parts
        if len(parts) < 2:
            raise ValueError("name an explicit case data file or its inputs/ directory")
        directory = path if path.is_dir() else None
        if directory is not None and parts[1] != "inputs":
            raise ValueError("reference case directory grants are limited to a declared case inputs/ directory")
        _ordinary(path, root)
        files = []
        for candidate in path.rglob("*") if directory is not None else [path]:
            _ordinary(candidate, root)
            if candidate.is_dir():
                continue
            _ordinary(candidate, root, data=True)
            files.append(candidate)
            if len(files) > 256:
                raise ValueError("project data input directory has over 256 files; name precise input files")
        if not files:
            raise ValueError("reference case input directory contains no data files")
        return files, directory, case_root
    if selected_ki_root is None or Path(selected_ki_root).absolute() != root:
        raise ValueError("bundled KI data must belong to this project's current selected KI root")
    if not path.is_file():
        raise ValueError("bundled KI data grants require explicit existing files, never directories")
    _ordinary(path, root, data=True)
    if authority is None:
        raise ValueError("bundled KI data requires the host's current signed projection check")
    lineage = authority(project, ki, root)
    if isinstance(lineage, dict) and "unchanged_ki_data_sha256" in lineage:
        from .receipts import sha256_file
        unchanged = lineage["unchanged_ki_data_sha256"]
        if (not isinstance(unchanged, dict)
                or unchanged.get(path.relative_to(root).as_posix()) != sha256_file(path)):
            raise ValueError("bundled KI data changed during maintenance; use an explicitly acquired project input")
    return [path], None, root


def review_errors(plan: dict, inventory: dict, project: Path | None, ki_roots: dict, *, authority=None) -> list[str]:
    errors, authenticated, produced = [], {}, set()
    # The plan validator reports malformed IDs; do not crash its remaining
    # checks by using an unhashable rejected ID as a lookup key.
    items = {item["id"]: item for item in inventory.get("items", [])
             if isinstance(item, dict) and isinstance(item.get("id"), str)}
    def check(project, ki, root):
        if authority is None:
            raise ValueError("bundled KI data requires the host's current signed projection check")
        key = (ki, root)
        if key not in authenticated:
            authenticated[key] = authority(project, ki, root)
        return authenticated[key]
    for step in plan.get("steps", []):
        if not isinstance(step, dict) or step.get("status") == "skipped":
            continue
        if "project_data_tool" in step:
            try:
                require_input_ids(step)
            except ValueError as error:
                errors.append(f"step {step.get('id')!r}: {error}")
        input_ids = step.get("inputs")
        for ident in input_ids if "project_data_tool" in step and isinstance(input_ids, list) else []:
            if not isinstance(ident, str):
                continue
            item = items.get(ident)
            if not item:
                continue
            local_paths = item.get("local_paths")
            for raw in local_paths if isinstance(local_paths, list) else []:
                if not isinstance(raw, str):
                    continue
                try:
                    if project is None:
                        raise ValueError("project context is required for project data input review")
                    grant(project, step.get("ki"), raw, selected_ki_root=ki_roots.get(step.get("ki")),
                          authority=check, allow_missing=ident in produced or item.get("status") != "ready")
                except (OSError, ValueError, TypeError, RuntimeError) as error:
                    errors.append(f"step {step.get('id')!r}, input {ident!r}, path {raw!r}: {error}")
        outputs = step.get("outputs")
        if (step.get("status") != "failed" and isinstance(outputs, list)
                and (step.get("tool") or step.get("kind") == "download")):
            produced.update(ident for ident in outputs if isinstance(ident, str))
    return errors
