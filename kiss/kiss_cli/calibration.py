"""Connect GeoForge projects to the model-agnostic calibration framework.

The framework has three deliberately separate lifetimes:

* one read-only numerical engine shared by the application;
* one adapter contract per KI (``calibration.yaml`` + ``tools/calib_run.py``);
* one writable calibration workspace per chat project.

Keeping the engine shared avoids copying the same optimizer into every KI and
every session.  Copying the small KI adapter into a project is intentional: it
lets an agent adapt a general KI to one case without mutating the curated KI.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import re
import shlex
import shutil
import sys
import time
import uuid
from pathlib import Path
from dataclasses import dataclass


FRAMEWORK_REPOSITORY = "https://github.com/lzwei196/agent-calibration-framework"
FRAMEWORK_COMMIT = "579162102f71f2fa4619b874a21bd219caaed25e"
MANIFEST = "framework.json"

# These are the dependencies required by the framework's two production
# optimizer families.  Optional research backends (PEST++ and surrogate/torch)
# remain capability-probed by the framework itself; they are not required for
# DDS/SCE-UA/DREAM or NSGA-II/III/MOEA-D.
REQUIRED_DEPENDENCIES = {
    "numpy": "numpy",
    "yaml": "PyYAML",
    "spotpy": "spotpy",
    "pymoo": "pymoo",
}
BACKEND_MODULES = (
    "spotpy.algorithms.dds",
    "spotpy.algorithms.sceua",
    "spotpy.algorithms.dream",
    "spotpy.database.ram",
    "pymoo.algorithms.moo.nsga2",
    "pymoo.algorithms.moo.nsga3",
    "pymoo.algorithms.moo.moead",
    "pymoo.util.ref_dirs",
)
ALGORITHMS = frozenset(("dds", "sceua", "dream", "nsga2", "nsga3", "moead"))


def _valid_framework(path: Path) -> bool:
    return all((path / rel).is_file() for rel in (
        "calibration_kit/__init__.py",
        "calibration_kit/CALIBRATION_YAML_SCHEMA.md",
        "calibration_kit/CALIBRATION_FRAMEWORK_DESIGN.md",
    ))


def framework_root() -> Path | None:
    """Find a pinned/bundled framework without downloading during a chat."""
    candidates: list[Path] = []
    configured = os.environ.get("GEOFORGE_CALIBRATION_FRAMEWORK")
    if configured:
        candidates.append(Path(configured).expanduser())
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        candidates.append(Path(frozen) / "agent-calibration-framework")
    source_root = Path(__file__).resolve().parents[1]
    candidates.extend((
        source_root / "vendor" / "agent-calibration-framework",
        source_root.parent / "agent-calibration-framework",
    ))
    try:
        from .firstrun import data_dir
        candidates.append(data_dir() / "agent-calibration-framework")
    except Exception:
        pass
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in seen and _valid_framework(resolved):
            return resolved
        seen.add(resolved)
    return None


def dependency_status() -> dict[str, dict]:
    """Report imports, not merely installed-package metadata.

    A PyInstaller application can contain distribution metadata while still
    missing a dynamically imported extension module.  Importing each required
    top-level package is the useful proof for the user-facing readiness badge.
    """
    out: dict[str, dict] = {}
    for module_name, distribution in REQUIRED_DEPENDENCIES.items():
        try:
            importlib.import_module(module_name)
            try:
                version = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                version = None
            out[module_name] = {"available": True, "version": version}
        except Exception as exc:
            out[module_name] = {
                "available": False,
                "version": None,
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }
    return out


def backend_module_status() -> dict[str, dict]:
    """Prove that each dynamically loaded production algorithm is frozen.

    Importing only ``spotpy`` or ``pymoo`` is insufficient in a PyInstaller
    build: their algorithm implementations are selected at runtime and can be
    omitted unless they are checked and declared explicitly.
    """
    out: dict[str, dict] = {}
    for module_name in BACKEND_MODULES:
        try:
            importlib.import_module(module_name)
            if module_name == "spotpy.database.ram":
                # SPOTPY discovers its result writer through pkgutil, not only
                # import_module. A frozen app can import every algorithm and
                # still fail on the very first evaluation when RAM is absent.
                database = importlib.import_module("spotpy.database")
                if "ram" not in database.__dir__():
                    raise RuntimeError("SPOTPY cannot discover its RAM result writer")
            out[module_name] = {"available": True}
        except Exception as exc:
            out[module_name] = {
                "available": False,
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }
    return out


def framework_status() -> dict:
    root = framework_root()
    dependencies = dependency_status()
    backend_modules = backend_module_status()
    dependencies_ready = all(item["available"] for item in dependencies.values())
    backends_ready = all(item["available"] for item in backend_modules.values())
    return {
        "available": root is not None,
        "ready": root is not None and dependencies_ready and backends_ready,
        "repository": FRAMEWORK_REPOSITORY,
        "commit": FRAMEWORK_COMMIT,
        "engine_root": str(root) if root else None,
        "mode": "shared-engine",
        "dependencies": dependencies,
        "backend_modules": backend_modules,
    }


def with_framework_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Expose the shared engine to model runners without copying its source."""
    out = dict(os.environ if env is None else env)
    root = framework_root()
    if root is None:
        return out
    existing = out.get("PYTHONPATH", "")
    parts = [part for part in existing.split(os.pathsep) if part]
    if str(root) not in parts:
        # Keep the model's own ki_tools_common first.  calibration_kit has a
        # unique package name, so it does not need to shadow model libraries.
        parts.append(str(root))
    out["PYTHONPATH"] = os.pathsep.join(parts)
    out["GEOFORGE_CALIBRATION_FRAMEWORK"] = str(root)
    out["GEOFORGE_CALIBRATION_COMMIT"] = FRAMEWORK_COMMIT
    return out


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name)).strip("-.")[:100] or "KI"


def _copy_once(source: Path, destination: Path) -> bool:
    if not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source, destination)
    return True


def command_prefix() -> list[str]:
    """Command that reaches the calibration engine in this exact runtime."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "calibrate"]
    return [sys.executable, "-m", "kiss_cli", "calibrate"]


def command_example(ki_name: str, ki_path: Path, project: Path) -> str:
    """Short CLI handoff for local coding-agent providers."""
    argv = [
        *command_prefix(),
        "--model", str(ki_name),
        "--ki-path", str(Path(ki_path).resolve()),
        "--project", str(Path(project).resolve()),
        "--plan-step-id", "APPROVED_CALIBRATION_STEP_ID",
        "--obs-shapes-json", '{"OUTPUT_VAR":"point_time_series"}',
    ]
    return shlex.join(argv)


def _adapter(project: Path, ki) -> dict:
    name = str(ki.name)
    source = Path(ki.root)
    destination = project / "calibration" / "kis" / _slug(name)
    # Create the authoring location even when the reusable KI does not have an
    # adapter yet.  The project agent can then add the two small case-specific
    # files without modifying the curated KI package.
    (destination / "tools").mkdir(parents=True, exist_ok=True)
    _copy_once(source / "calibration.yaml",
               destination / "calibration.yaml")
    _copy_once(source / "tools" / "calib_run.py",
               destination / "tools" / "calib_run.py")
    contract = (destination / "calibration.yaml").is_file()
    runner = (destination / "tools" / "calib_run.py").is_file()
    return {
        "ki": name,
        "status": "ready" if contract and runner else "authoring-needed",
        "contract": (destination / "calibration.yaml").relative_to(
            project).as_posix()
        if contract else None,
        "runner": (destination / "tools" / "calib_run.py").relative_to(
            project).as_posix()
        if runner else None,
        "source_has_contract": (source / "calibration.yaml").is_file(),
        "source_has_runner": (source / "tools" / "calib_run.py").is_file(),
    }


def _saved_adapters(root: Path) -> list[dict]:
    """Keep project-owned adapters visible across Auto-KI chat turns."""
    saved: list[dict] = []
    try:
        doc = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("adapters"), list):
            saved = [item for item in doc["adapters"] if isinstance(item, dict)]
    except (OSError, json.JSONDecodeError):
        pass

    by_name = {str(item.get("ki")): dict(item) for item in saved if item.get("ki")}
    adapters_root = root / "kis"
    if adapters_root.is_dir():
        for directory in adapters_root.iterdir():
            if directory.is_dir() and directory.name not in by_name:
                by_name[directory.name] = {"ki": directory.name}

    out = []
    for name, item in by_name.items():
        directory = adapters_root / _slug(name)
        contract = directory / "calibration.yaml"
        runner = directory / "tools" / "calib_run.py"
        item.update({
            "ki": name,
            "status": "ready" if contract.is_file() and runner.is_file()
            else "authoring-needed",
            "contract": contract.relative_to(root.parent).as_posix()
            if contract.is_file() else None,
            "runner": runner.relative_to(root.parent).as_posix()
            if runner.is_file() else None,
        })
        out.append(item)
    return sorted(out, key=lambda item: str(item.get("ki", "")).casefold())


def ensure_project(project: Path, kis=()) -> dict:
    """Create/update the small per-session calibration control plane."""
    project = Path(project).resolve()
    root = project / "calibration"
    for rel in ("cases", "runs", "kis", "runtime"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    # A reusable Auto-KI chat may choose its model only after the first turn.
    # Do not erase that choice when a later prompt is composed with no pinned
    # model. Project adapters intentionally accumulate because one project may
    # calibrate more than one coupled model.
    adapters_by_name = {
        str(item["ki"]): item for item in _saved_adapters(root) if item.get("ki")
    }
    for ki in kis:
        item = _adapter(project, ki)
        adapters_by_name[str(item["ki"])] = item
    adapters = sorted(adapters_by_name.values(),
                      key=lambda item: str(item.get("ki", "")).casefold())
    status = {**framework_status(), "adapters": adapters}
    manifest = root / MANIFEST
    temp = manifest.with_suffix(".tmp")
    temp.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(manifest)
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            """# GeoForge calibration workspace

This project uses one shared, fixed calibration engine and keeps only the
case-specific work here.

- `framework.json` records the exact engine version and KI adapter readiness.
- `kis/` contains editable copies of this project's KI calibration adapters.
- `cases/` contains observations, parameter choices, and holdout definitions.
- `runs/` contains optimizer logs, checkpoints, metrics, and promotion verdicts.
- `runtime/` is a generated, materialised KI copy used by the bundled engine.

The scientific model must run through its KI. Calibration may wrap that run;
it must not replace the model with a simplified calculation. A result is not
promotable until the framework's out-of-sample holdout gate passes.
""", encoding="utf-8")
    return status


def _case_files(project: Path, limit: int = 200) -> list[dict]:
    root = Path(project).resolve() / "calibration" / "cases"
    files: list[dict] = []
    if not root.is_dir():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            stat = path.stat()
            files.append({
                "name": path.name,
                "relative_path": path.relative_to(project).as_posix(),
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            })
        except OSError:
            continue
        if len(files) >= limit:
            break
    return files


def _recorded_count(value) -> int | None:
    """A missing execution count is unknown, not zero or an optimizer estimate."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _objective_checks(holdout: dict | None) -> list[dict]:
    """Expose saved gate evidence without reconstructing criteria from today's engine.

    Older reports only record the generic magnitude backstop when it fails.
    Absence of a threshold therefore means unrecorded, not that no absolute
    criterion was applied. Preserve each original comparison alongside this
    explicit availability marker.
    """
    checks = holdout.get("per_objective") if isinstance(holdout, dict) else None
    if not isinstance(checks, list):
        return []
    out = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        criterion = {"available": None, "source": None, "max_loss": None}
        for key in ("band_ceiling", "mag_backstop"):
            value = item.get(key)
            if (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value) and value >= 0):
                criterion = {"available": True, "source": key, "max_loss": value}
                break
        out.append({**item, "absolute_criterion": criterion})
    return out


def _run_summaries(project: Path, limit: int = 20) -> list[dict]:
    root = Path(project).resolve() / "calibration" / "runs"
    found: list[tuple[float, dict]] = []
    if not root.is_dir():
        return []
    for report_path in root.glob("*/report.json"):
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            report = payload.get("report")
            report = report if isinstance(report, dict) else {}
            stat = report_path.stat()
            holdout = report.get("holdout")
            train_metrics = report.get("train_metrics")
            found.append((stat.st_mtime, {
                "run_id": str(payload.get("run_id") or report_path.parent.name),
                "ki": payload.get("ki"),
                "algorithm": report.get("algorithm") or payload.get("algorithm"),
                "budget": payload.get("budget"),
                "requested_optimizer_budget": _recorded_count(payload.get("budget")),
                "optimizer_evaluations": _recorded_count(report.get("n_evaluations")),
                # Never derive native launches from evaluations: probes, cache
                # hits and holdout checks make these different quantities.
                "native_launch_count": _recorded_count(report.get("native_launch_count")),
                "seed": payload.get("seed"),
                "status": report.get("status") or "unknown",
                "promotable": report.get("promotable") is True,
                "backend": report.get("backend"),
                "best_loss": report.get("best_loss"),
                "best_params": report.get("best_params"),
                "reason": report.get("reason"),
                "train_metrics": train_metrics if isinstance(train_metrics, dict) else None,
                "holdout": holdout if isinstance(holdout, dict) else None,
                "objective_checks": _objective_checks(holdout),
                "report_path": report_path.relative_to(project).as_posix(),
                "log_path": (report_path.parent / "engine.log").relative_to(
                    project).as_posix(),
                "modified_at": stat.st_mtime,
            }))
        except (OSError, json.JSONDecodeError):
            continue
    found.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in found[:limit]]


def project_state(project: Path, kis=()) -> dict:
    """User-facing readiness and honest run history for one chat project."""
    project = Path(project).resolve()
    status = ensure_project(project, kis)
    cases = _case_files(project)
    runs = _run_summaries(project)
    ready = [item for item in status.get("adapters", [])
             if item.get("status") == "ready"]
    return {
        **status,
        "ready_adapter_count": len(ready),
        "case_files": cases,
        "case_count": len(cases),
        "runs": runs,
        "run_count": len(runs),
        "latest_run": runs[0] if runs else None,
    }


@dataclass(frozen=True)
class AdapterSnapshot:
    """Exact adapter bytes reviewed by the host and subsequently materialized."""

    contract_path: Path
    runner_path: Path
    contract_bytes: bytes
    runner_bytes: bytes


def snapshot_adapter(project: Path, ki_name: str) -> AdapterSnapshot:
    project = Path(project).resolve()
    adapter = project / "calibration" / "kis" / _slug(ki_name)
    contract = adapter / "calibration.yaml"
    runner = adapter / "tools" / "calib_run.py"
    for path in (contract, runner):
        if not path.resolve().is_relative_to(project) or path.resolve() != path:
            raise ValueError("calibration adapter must stay inside this project")
        if not path.is_file():
            raise RuntimeError(
                f"{ki_name} has no runnable project calibration adapter; expected "
                f"{contract.relative_to(project).as_posix()} and "
                f"{runner.relative_to(project).as_posix()}")
    return AdapterSnapshot(contract.resolve(), runner.resolve(),
                           contract.read_bytes(), runner.read_bytes())


def _resolved_invocation(snapshot: AdapterSnapshot, arguments: dict) -> dict:
    import yaml
    doc = yaml.safe_load(snapshot.contract_bytes.decode("utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("calibration.yaml must contain an object")
    parameters = doc.get("parameters")
    if not isinstance(parameters, list) or not parameters:
        raise ValueError("calibration contract must explicitly declare its parameters and bounds")
    names = set()
    for parameter in parameters:
        if not isinstance(parameter, dict):
            raise ValueError("each calibration parameter must be an object")
        name, bounds = parameter.get("name"), parameter.get("range")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("calibration parameter names must be nonempty and unique")
        names.add(name)
        if (not isinstance(bounds, list) or len(bounds) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bounds)
                or bounds[0] >= bounds[1]):
            raise ValueError(f"calibration parameter {name!r} needs finite increasing bounds")
        if "default" in parameter:
            default = parameter["default"]
            if not isinstance(default, (int, float)) or not math.isfinite(default) or not bounds[0] <= default <= bounds[1]:
                raise ValueError(f"calibration parameter {name!r} default is outside its bounds")
    runner = doc.get("runner") or {}
    command = runner.get("command") if isinstance(runner, dict) else None
    if (not isinstance(runner, dict) or runner.get("kind") != "subprocess" or not isinstance(command, list)
            or not all(isinstance(part, str) for part in command)
            or len(command) < 2
            or not re.fullmatch(r"python(?:[23](?:\.\d+)?)?(?:\.exe)?", command[0].replace("\\", "/").rsplit("/", 1)[-1], re.IGNORECASE)
            or command[1].replace("\\", "/") != "{ki_path}/tools/calib_run.py"):
        raise ValueError("approved calibration requires a subprocess runner command beginning with "
                         "a Python interpreter and {ki_path}/tools/calib_run.py; update this project's adapter")
    strategy = doc.get("strategy") or {}
    if not isinstance(strategy, dict):
        raise ValueError("calibration strategy must be an object")
    algorithm = arguments.get("algorithm") or strategy.get("default_algorithm") or "dds"
    if not isinstance(algorithm, str) or algorithm not in ALGORITHMS:
        raise ValueError(f"unknown calibration algorithm {algorithm!r}")
    budget = arguments.get("budget")
    if budget is None:
        budget = strategy.get("max_evaluations", 200)
    if isinstance(budget, bool) or not isinstance(budget, int) or not 1 <= budget <= 10000:
        raise ValueError("calibration budget must be an integer between 1 and 10000 evaluations")
    seed = arguments.get("seed", 0)
    if seed is None:
        seed = 0
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("calibration seed must be an integer from 0 through 4294967295")
    metric = arguments.get("determining_metric")
    if metric is not None and not isinstance(metric, str):
        raise ValueError("determining_metric must be a string or null")
    metric = metric or None
    shapes = arguments.get("obs_shape_by_var")
    if (not isinstance(shapes, dict) or not shapes
            or any(not isinstance(k, str) or not k.strip()
                   or not isinstance(v, str) or not v.strip() for k, v in shapes.items())):
        raise ValueError("obs_shape_by_var must map each calibration target to its observation shape")
    identity = doc.get("identity") or {}
    if not isinstance(identity, dict):
        raise ValueError("calibration identity must be an object")
    case_id = identity.get("case_id")
    if case_id is not None and (not isinstance(case_id, str) or not case_id.strip()):
        raise ValueError("calibration case_id must be a nonempty string")
    return {
        "contract_path": str(snapshot.contract_path),
        "contract_sha256": hashlib.sha256(snapshot.contract_bytes).hexdigest(),
        "runner_sha256": hashlib.sha256(snapshot.runner_bytes).hexdigest(),
        "algorithm": algorithm, "budget": budget, "seed": seed,
        "determining_metric": metric, "obs_shape_by_var": dict(shapes),
        "expected_case_id": case_id,
    }


def prepare_invocation(project: Path, ki_name: str, arguments: dict) -> tuple[dict, AdapterSnapshot]:
    """Resolve a concrete review binding without running the adapter or optimizer."""
    snapshot = snapshot_adapter(project, ki_name)
    return _resolved_invocation(snapshot, arguments), snapshot


def write_adapter(project: Path, ki_name: str, contract: dict, runner_source: str) -> dict:
    """Prepare exactly two project adapter files; never execute submitted code.

    The API admits this operation only while planning for a selected KI. The
    subsequent review binds these bytes before any model or optimizer can run.
    """
    import yaml
    if not isinstance(contract, dict) or not isinstance(runner_source, str):
        raise ValueError("contract must be an object and runner_source must be Python source text")
    if len(runner_source.encode("utf-8")) > 1024 * 1024:
        raise ValueError("calibration runner source exceeds 1 MiB")
    json.dumps(contract, allow_nan=False)
    contract_bytes = yaml.safe_dump(contract, sort_keys=False, allow_unicode=True).encode("utf-8")
    if len(contract_bytes) > 1024 * 1024:
        raise ValueError("calibration contract exceeds 1 MiB")
    project = Path(project).resolve()
    adapter = project / "calibration" / "kis" / _slug(ki_name)
    contract_path = adapter / "calibration.yaml"
    runner_path = adapter / "tools" / "calib_run.py"
    for path in (contract_path, runner_path):
        if not path.resolve().is_relative_to(project) or path.resolve() != path or path.is_symlink():
            raise ValueError("calibration adapter path escapes the current project or is a link")
        if path.exists() and (not path.is_file() or path.stat().st_nlink > 1):
            raise ValueError("calibration adapter must be an ordinary unshared file")
    targets = contract.get("targets")
    if (not isinstance(targets, list) or not targets
            or any(not isinstance(t, dict) or not isinstance(t.get("var"), str) or not t["var"].strip() for t in targets)):
        raise ValueError("calibration contract must explicitly name its target variables")
    snapshot = AdapterSnapshot(contract_path.resolve(), runner_path.resolve(),
                               contract_bytes, runner_source.encode("utf-8"))
    # Validate the adapter entry point/default invocation without inventing any
    # scientific observation shape in the saved contract or future plan.
    _resolved_invocation(snapshot, {"obs_shape_by_var": {t["var"]: "pending-plan-review" for t in targets}})
    compile(runner_source, str(runner_path), "exec")
    pending = []
    try:
        for path, data in ((contract_path, contract_bytes), (runner_path, snapshot.runner_bytes)):
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            temporary.write_bytes(data)
            pending.append((temporary, path))
        for temporary, path in pending:
            temporary.replace(path)
    finally:
        for temporary, _ in pending:
            temporary.unlink(missing_ok=True)
    return {"ki": ki_name, "contract": contract_path.relative_to(project).as_posix(),
            "runner": runner_path.relative_to(project).as_posix(),
            "contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
            "runner_sha256": hashlib.sha256(snapshot.runner_bytes).hexdigest(),
            "status": "prepared_for_review", "executed": False}


def _runtime_ki(project: Path, ki_name: str, ki_path: Path,
                snapshot: AdapterSnapshot | None = None, run_id: str | None = None) -> Path:
    """Build the engine's KI view from the live model plus project adapter.

    The live KI contains this session's resolved paths.  The adapter under
    ``calibration/kis`` is project-owned and may be refined for this case.  A
    generated runtime copy combines them without mutating either source.
    """
    project = Path(project).resolve()
    source = Path(ki_path).resolve()
    snapshot = snapshot or snapshot_adapter(project, ki_name)

    parent = project / "calibration" / "runtime"
    if run_id is not None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise ValueError("invalid calibration runtime run id")
        parent = parent / _slug(ki_name)
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / (run_id or _slug(ki_name))
    if run_id is not None and destination.exists():
        raise FileExistsError("a completed calibration runtime cannot be overwritten")
    staging = parent / f".{_slug(ki_name)}-{uuid.uuid4().hex[:8]}.tmp"
    for path in (destination, staging):
        if not path.resolve().is_relative_to(project):
            raise ValueError("calibration runtime must stay inside this project")
    try:
        shutil.copytree(source, staging, symlinks=False)
        (staging / "calibration.yaml").write_bytes(snapshot.contract_bytes)
        (staging / "tools").mkdir(parents=True, exist_ok=True)
        (staging / "tools" / "calib_run.py").write_bytes(snapshot.runner_bytes)
        if destination.exists():
            shutil.rmtree(destination)
        staging.replace(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return destination


def run_project(*, project: Path, ki_name: str, ki_path: Path,
                obs_shape_by_var: dict[str, str], budget: int | None = None,
                seed: int = 0, algorithm: str | None = None,
                expected_case_id: str | None = None,
                determining_metric: str | None = None,
                stop=None, turn_id=None, adapter_snapshot: AdapterSnapshot | None = None,
                approved_binding: dict | None = None) -> dict:
    """Run one real calibration using GeoForge's bundled Python runtime.

    This is deliberately a native harness operation.  API models call it as a
    typed tool, while local CLI agents call the frozen GeoForge executable.  In
    both cases numpy/spotpy/pymoo come from the app rather than the user's Python.
    """
    project = Path(project).resolve()
    ki_path = Path(ki_path).resolve()
    from . import execution
    # Capture once, before preparation: a new user turn cannot revive this one.
    env = execution.turn_environment(project, turn_id=turn_id)
    def stopped():
        return (stop is not None and stop()) or execution.stop_requested(project, env=env)
    if stopped():
        return {"report": {"status": "stopped", "promotable": False,
                           "reason": "Stopped by the user before calibration started."}}
    status = framework_status()
    if not status.get("ready"):
        missing = [name for name, item in {**status.get("dependencies", {}),
                                         **status.get("backend_modules", {})}.items()
                   if not item.get("available")]
        reason = "framework source is missing" if not status.get("available") else (
            "bundled dependencies are missing: " + ", ".join(missing))
        raise RuntimeError(reason)
    if approved_binding is not None:
        if adapter_snapshot is None:
            raise ValueError("approved calibration requires its reviewed adapter snapshot")
        actual = _resolved_invocation(adapter_snapshot, {
            "obs_shape_by_var": obs_shape_by_var, "algorithm": algorithm,
            "budget": budget, "seed": seed, "determining_metric": determining_metric})
        if actual != approved_binding or expected_case_id != actual["expected_case_id"]:
            raise ValueError("calibration invocation differs from the approved binding")
    if not isinstance(obs_shape_by_var, dict) or not obs_shape_by_var:
        raise ValueError("obs_shape_by_var must map each calibration target to its observation shape")
    shapes = {str(key): str(value) for key, value in obs_shape_by_var.items()
              if str(key).strip() and str(value).strip()}
    if not shapes:
        raise ValueError("obs_shape_by_var contains no usable target mappings")
    if algorithm is not None and algorithm not in ALGORITHMS:
        raise ValueError(f"unknown calibration algorithm {algorithm!r}")
    if budget is not None and not 1 <= int(budget) <= 10000:
        raise ValueError("calibration budget must be between 1 and 10000 evaluations")

    # API callers have already materialised the project adapter.  Do not call
    # ensure_project(project) without that KI here: doing so would overwrite
    # framework.json with an empty adapter list just as a run starts.
    for rel in ("cases", "runs", "kis", "runtime"):
        (project / "calibration" / rel).mkdir(parents=True, exist_ok=True)
    adapter_snapshot = adapter_snapshot or snapshot_adapter(project, ki_name)
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    runtime_ki = _runtime_ki(project, ki_name, ki_path, adapter_snapshot, run_id)
    if expected_case_id is None:
        try:
            import yaml
            contract_doc = yaml.safe_load(
                (runtime_ki / "calibration.yaml").read_text(encoding="utf-8")) or {}
            expected_case_id = str(
                (contract_doc.get("identity") or {}).get("case_id") or ""
            ).strip() or None
        except (OSError, ValueError, TypeError):
            expected_case_id = None
    run_dir = project / "calibration" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    saved_adapter = run_dir / "adapter"
    saved_adapter.mkdir()
    (saved_adapter / "calibration.yaml").write_bytes(adapter_snapshot.contract_bytes)
    (saved_adapter / "calib_run.py").write_bytes(adapter_snapshot.runner_bytes)
    report_path = run_dir / "report.json"
    log_path = run_dir / "engine.log"

    request_path = run_dir / "engine-request.json"
    engine_report = run_dir / "engine-report.json"
    request_path.write_text(json.dumps({
        "project": str(project),
        "runtime_ki": str(runtime_ki), "run_dir": str(run_dir), "shapes": shapes,
        "budget": int(budget) if budget is not None else None, "seed": int(seed),
        "algorithm": algorithm, "determining_metric": determining_metric,
        "expected_case_id": expected_case_id,
    }), encoding="utf-8")
    env = with_framework_env(env)
    if not getattr(sys, "frozen", False):
        package_root = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = package_root + os.pathsep + env.get("PYTHONPATH", "")
    process = execution.run_process(
        worker_command(request_path), cwd=project, env=env, timeout=None,
        project=project, stop=stopped, turn_id=turn_id)
    report = _worker_report(process, engine_report, stopped=stopped())
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    log += process.stdout + process.stderr
    if process.detail:
        log += "\n" + process.detail
    log_path.write_text(log, encoding="utf-8")
    payload = {
        "run_id": run_id,
        "ki": ki_name,
        "framework_commit": FRAMEWORK_COMMIT,
        "algorithm": algorithm,
        "budget": budget,
        "seed": int(seed),
        "obs_shape_by_var": shapes,
        "expected_case_id": expected_case_id,
        "runtime_ki": runtime_ki.relative_to(project).as_posix(),
        "approved_binding": approved_binding,
        "report": report,
    }
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False,
                                      default=str), encoding="utf-8")
    return {
        **payload,
        "report_path": report_path.relative_to(project).as_posix(),
        "log_path": log_path.relative_to(project).as_posix(),
        "log_tail": log[-12000:],
    }


def worker_command(request_path: Path) -> list[str]:
    """Use the same bundled executable or source interpreter as the public CLI."""
    prefix = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "kiss_cli"]
    return [*prefix, "_calibration-worker", str(request_path)]


def _worker_report(process, path: Path, *, stopped=False) -> dict:
    # Cancellation wins even when the worker wrote a success just before Stop.
    if stopped or process.status in {"stopped", "interrupted"}:
        return {"status": "stopped", "promotable": False,
                "reason": "Stopped by the user; calibration did not complete."}
    try:
        if process.status != "succeeded":
            raise ValueError(process.detail or f"calibration worker {process.status}")
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not isinstance(report.get("status"), str):
            raise ValueError("calibration worker returned no valid report")
        return report
    except (OSError, ValueError) as exc:
        return {"status": "engine_error", "promotable": False, "reason": str(exc)}


def validate_receipt_result(result: dict, binding: dict) -> dict:
    """Validate the typed optimizer result, separately from raw model file formats.

    Receipt creation still hashes all changed run files. The adapter and its
    contract are approval-bound; configuration numbers or a populated log alone
    are never calibration evidence. A completed but unvalidated experiment is
    retained with a warning and cannot establish scientific completion.
    """
    result = result if isinstance(result, dict) else {}
    report = result.get("report")
    report = report if isinstance(report, dict) else {}
    checks = []
    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
    def finite(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    check("calibration_approved_binding", result.get("approved_binding") == binding)
    check("calibration_completed", report.get("status") == "completed", str(report.get("reason") or ""))
    losses = report.get("best_loss")
    check("calibration_finite_loss", isinstance(losses, list) and bool(losses)
          and all(finite(v) and v >= 0 for v in losses))
    params = report.get("best_params")
    check("calibration_finite_parameters", isinstance(params, dict) and bool(params)
          and all(finite(v) or isinstance(v, bool) for v in params.values()))
    count = report.get("n_evaluations")
    check("calibration_evaluations", isinstance(count, int) and not isinstance(count, bool) and count > 0,
          f"requested optimizer budget={binding.get('budget')}; actual evaluations={count}")
    metrics = report.get("train_metrics")
    def metric_numbers(value):
        if not isinstance(value, dict):
            return []
        return [number for key, item in value.items() if key != "__kdt__"
                for number in (metric_numbers(item) if isinstance(item, dict) else [item]) if finite(number)]
    check("calibration_training_metrics", bool(metric_numbers(metrics)))
    if not all(c["ok"] for c in checks):
        return {"status": "failed", "checks": checks}
    holdout = report.get("holdout") or {}
    objectives = holdout.get("per_objective") if isinstance(holdout, dict) else None
    holdout_ok = (isinstance(holdout, dict) and holdout.get("passed") is True
                  and holdout.get("inconclusive") is False and report.get("holdout_validated") is True
                  and report.get("promotable") is True and isinstance(objectives, list) and bool(objectives)
                  and all(isinstance(o, dict) and o.get("ok") is True
                          and finite(o.get("calibration_loss")) and finite(o.get("holdout_loss"))
                          for o in objectives))
    check("calibration_holdout", holdout_ok,
          "A completed search needs a passing independent holdout before scientific completion.")
    return {"status": "passed" if holdout_ok else "warning", "checks": checks}


@contextlib.contextmanager
def _quiet_evaluation_processes():
    """Apply Desktop's Windows launch policy without modifying the pinned engine.

    A windowed frozen executable has no console to inherit. Unlike a Python
    worker launched with CREATE_NO_WINDOW, its ordinary console children open
    a console for each evaluation. Scope this proxy to the framework runner in
    the isolated worker; unrelated application subprocesses remain untouched.
    """
    if os.name != "nt":
        yield
        return
    try:
        runner = importlib.import_module("calibration_kit.runner")
    except ModuleNotFoundError as error:
        # Minimal worker fixtures have no model runner. Do not hide an actual
        # runner's missing transitive dependency.
        if error.name != "calibration_kit.runner":
            raise
        yield
        return
    original = runner.subprocess
    class HiddenSubprocess:
        def __getattr__(self, name):
            return getattr(original, name)

        def run(self, *args, **kwargs):
            kwargs["creationflags"] = (kwargs.get("creationflags", 0)
                                        | original.CREATE_NO_WINDOW)
            return original.run(*args, **kwargs)
    runner.subprocess = HiddenSubprocess()
    try:
        yield
    finally:
        runner.subprocess = original


def run_worker(request_path: Path) -> int:
    """Private child entry point; all optimizer/model work stays in its process tree."""
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    from . import execution
    if execution.stop_requested(Path(request["project"])):
        return 130
    run_dir = Path(request["run_dir"])
    root = framework_root()
    if root is None:
        raise RuntimeError("calibration framework source is missing")
    sys.path.insert(0, str(root))
    if request.get("algorithm"):
        os.environ["KDT_CALIB_ALGO"] = request["algorithm"]
    else:
        os.environ.pop("KDT_CALIB_ALGO", None)
    with (run_dir / "engine.log").open("w", encoding="utf-8", buffering=1) as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                engine = importlib.import_module("calibration_kit.calib")
                with _quiet_evaluation_processes():
                    report = engine.calibrate(
                        request["runtime_ki"], str(run_dir), request["shapes"],
                        budget=request.get("budget"), seed=request["seed"],
                        determining_metric=request.get("determining_metric"),
                        expected_case_id=request.get("expected_case_id"))
            except Exception as exc:
                report = {"status": "engine_error", "promotable": False,
                          "reason": f"{type(exc).__name__}: {exc}"}
    (run_dir / "engine-report.json").write_text(
        json.dumps(report, default=str), encoding="utf-8")
    return 0


def load_project(project: Path) -> dict:
    path = Path(project) / "calibration" / MANIFEST
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else framework_status()
    except (OSError, json.JSONDecodeError):
        return framework_status()


def prompt_block(project: Path, kis=()) -> str:
    """Tell the AI harness how calibration is exposed in this exact project."""
    status = ensure_project(project, kis)
    adapters = status.get("adapters") or []
    lines = [
        "[CALIBRATION CAPABILITY — USE ONLY WHEN THE USER ASKS TO CALIBRATE]",
        "GeoForge uses the reusable KI as the execution backbone. Calibration is",
        "a project capability, not an adaptive KI and not a replacement model.",
        f"Project calibration workspace: {Path(project) / 'calibration'}",
    ]
    if status.get("ready"):
        lines += [
            f"Shared fixed engine: {status['engine_root']}",
            f"Pinned framework commit: {status['commit']}",
            "The required numpy, PyYAML, SPOTPY, and pymoo runtimes are bundled.",
            "Direct API: call the typed run_calibration tool; do not launch system Python.",
        ]
    else:
        lines += [
            "The shared numerical engine is not ready in this build. You may",
            "prepare a KI adapter and case plan, but do not claim that optimization ran.",
            f"Required pinned source: {status['repository']} at {status['commit']}",
        ]
    for adapter in adapters:
        if adapter["status"] == "ready":
            lines.append(
                f"{adapter['ki']} adapter: {adapter['contract']} + {adapter['runner']}")
            lines.append(
                f"{adapter['ki']} local-CLI command template: "
                f"{command_example(adapter['ki'], Path(project) / 'models' / adapter['ki'] / 'ki', project)}")
        else:
            lines.append(
                f"{adapter['ki']} adapter: authoring needed in calibration/kis/{_slug(adapter['ki'])}/")
    lines += [
        "Never edit the shared engine or curated KI for one project. Put case-specific",
        "contracts, observations, checkpoints, metrics, and results under calibration/.",
        "During PLANNING or REPLAN_REQUIRED, use write_calibration_adapter to prepare",
        "only the selected KI's project contract and runner. This does not execute code.",
        "Before review, declare a kind=calibrate step with tool set to the absolute",
        "project calibration/kis/<KI>/tools/calib_run.py path and a calibration object",
        "containing obs_shape_by_var, algorithm, budget, seed and determining_metric.",
        "The host resolves and shows exact defaults, case identity and adapter/contract",
        "hashes before approval. The contract's subprocess command must call",
        "{ki_path}/tools/calib_run.py. After approval, call run_calibration with that",
        "plan_step_id and the exact reviewed invocation. Changed adapter bytes, bounds,",
        "targets or invocation require a new review. The budget is the requested optimizer",
        "budget; sampler initialization/batches can use additional evaluations, reported",
        "separately. It is not a hard native-model launch cap.",
        "Reuse existing project files and prior calibration reports before downloading",
        "or asking the user. Report progress while preparing, optimizing, and validating.",
        "Define an independent holdout and save an honest comparison plot under artifacts/.",
        "Never call a result calibrated/promotable unless the real model ran, candidate",
        "parameters were read back, and the out-of-sample holdout gate passed.",
    ]
    return "\n".join(lines)
