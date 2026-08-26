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
import functools
import importlib
import importlib.metadata
import io
import json
import os
import re
import shlex
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path


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
    "pymoo.algorithms.moo.nsga2",
    "pymoo.algorithms.moo.nsga3",
    "pymoo.algorithms.moo.moead",
    "pymoo.util.ref_dirs",
)
ALGORITHMS = frozenset(("dds", "sceua", "dream", "nsga2", "nsga3", "moead"))
_RUN_LOCK = threading.Lock()


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


@functools.lru_cache(maxsize=1)
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


@functools.lru_cache(maxsize=1)
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
        "contract": str((destination / "calibration.yaml").relative_to(project))
        if contract else None,
        "runner": str((destination / "tools" / "calib_run.py").relative_to(project))
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
            "contract": str(contract.relative_to(root.parent)) if contract.is_file() else None,
            "runner": str(runner.relative_to(root.parent)) if runner.is_file() else None,
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
                "relative_path": str(path.relative_to(project)),
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            })
        except OSError:
            continue
        if len(files) >= limit:
            break
    return files


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
            found.append((stat.st_mtime, {
                "run_id": str(payload.get("run_id") or report_path.parent.name),
                "ki": payload.get("ki"),
                "algorithm": report.get("algorithm") or payload.get("algorithm"),
                "budget": payload.get("budget"),
                "seed": payload.get("seed"),
                "status": report.get("status") or "unknown",
                "promotable": report.get("promotable") is True,
                "backend": report.get("backend"),
                "best_loss": report.get("best_loss"),
                "best_params": report.get("best_params"),
                "reason": report.get("reason"),
                "holdout": holdout if isinstance(holdout, dict) else None,
                "report_path": str(report_path.relative_to(project)),
                "log_path": str((report_path.parent / "engine.log").relative_to(project)),
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


def _runtime_ki(project: Path, ki_name: str, ki_path: Path) -> Path:
    """Build the engine's KI view from the live model plus project adapter.

    The live KI contains this session's resolved paths.  The adapter under
    ``calibration/kis`` is project-owned and may be refined for this case.  A
    generated runtime copy combines them without mutating either source.
    """
    project = Path(project).resolve()
    source = Path(ki_path).resolve()
    adapter = project / "calibration" / "kis" / _slug(ki_name)
    contract = adapter / "calibration.yaml"
    runner = adapter / "tools" / "calib_run.py"
    if not contract.is_file() or not runner.is_file():
        raise RuntimeError(
            f"{ki_name} has no runnable project calibration adapter; expected "
            f"{contract.relative_to(project)} and {runner.relative_to(project)}")

    parent = project / "calibration" / "runtime"
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / _slug(ki_name)
    staging = parent / f".{_slug(ki_name)}-{uuid.uuid4().hex[:8]}.tmp"
    try:
        shutil.copytree(source, staging, symlinks=False)
        shutil.copy2(contract, staging / "calibration.yaml")
        (staging / "tools").mkdir(parents=True, exist_ok=True)
        shutil.copy2(runner, staging / "tools" / "calib_run.py")
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
                determining_metric: str | None = None) -> dict:
    """Run one real calibration using GeoForge's bundled Python runtime.

    This is deliberately a native harness operation.  API models call it as a
    typed tool, while local CLI agents call the frozen GeoForge executable.  In
    both cases numpy/spotpy/pymoo come from the app rather than the user's Python.
    """
    project = Path(project).resolve()
    ki_path = Path(ki_path).resolve()
    status = framework_status()
    if not status.get("ready"):
        missing = [name for name, item in status.get("dependencies", {}).items()
                   if not item.get("available")]
        reason = "framework source is missing" if not status.get("available") else (
            "bundled dependencies are missing: " + ", ".join(missing))
        raise RuntimeError(reason)
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
    runtime_ki = _runtime_ki(project, ki_name, ki_path)
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
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_dir = project / "calibration" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    report_path = run_dir / "report.json"
    log_path = run_dir / "engine.log"

    root = framework_root()
    assert root is not None
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    engine = importlib.import_module("calibration_kit.calib")

    # The framework currently selects an algorithm through KDT_CALIB_ALGO.
    # Protect that process-global setting from overlapping chat calibrations.
    previous_algorithm = os.environ.get("KDT_CALIB_ALGO")
    stream = io.StringIO()
    try:
        with _RUN_LOCK, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            if algorithm:
                os.environ["KDT_CALIB_ALGO"] = algorithm
            elif previous_algorithm is None:
                os.environ.pop("KDT_CALIB_ALGO", None)
            report = engine.calibrate(
                str(runtime_ki), str(run_dir), shapes,
                budget=int(budget) if budget is not None else None,
                seed=int(seed), determining_metric=determining_metric,
                expected_case_id=expected_case_id,
            )
    except Exception as exc:
        report = {
            "status": "engine_error", "promotable": False,
            "reason": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if previous_algorithm is None:
            os.environ.pop("KDT_CALIB_ALGO", None)
        else:
            os.environ["KDT_CALIB_ALGO"] = previous_algorithm

    log_path.write_text(stream.getvalue(), encoding="utf-8")
    payload = {
        "run_id": run_id,
        "ki": ki_name,
        "framework_commit": FRAMEWORK_COMMIT,
        "algorithm": algorithm,
        "budget": budget,
        "seed": int(seed),
        "obs_shape_by_var": shapes,
        "expected_case_id": expected_case_id,
        "runtime_ki": str(runtime_ki.relative_to(project)),
        "report": report,
    }
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False,
                                      default=str), encoding="utf-8")
    return {
        **payload,
        "report_path": str(report_path.relative_to(project)),
        "log_path": str(log_path.relative_to(project)),
        "log_tail": stream.getvalue()[-12000:],
    }


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
            "The shared numerical engine is not bundled in this build yet. You may",
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
        "Reuse existing project files and prior calibration reports before downloading",
        "or asking the user. Report progress while preparing, optimizing, and validating.",
        "Define an independent holdout and save an honest comparison plot under artifacts/.",
        "Never call a result calibrated/promotable unless the real model ran, candidate",
        "parameters were read back, and the out-of-sample holdout gate passed.",
    ]
    return "\n".join(lines)
