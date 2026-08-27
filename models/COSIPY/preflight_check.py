#!/usr/bin/env python3
"""Preflight check for the COSIPY Knowledge Infrastructure.

This script is intentionally self-contained because the KDT gate executes it
before model runs. It verifies the actual HydroCraft Python interpreter, the
current COSIPY source tree, required imports, KI tools, diagnostics, and the
default input/static data needed for a real COSIPY run.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import traceback


MODEL_ID = "COSIPY"
KI_DIR = Path(__file__).resolve().parent
MODEL_ROOT = KI_DIR.parent
SOURCE_DIR = MODEL_ROOT / "source" / "repo"
HYDRO_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
NETCDF_SHIM = KI_DIR / "tools" / "_netcdf_shim"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

CHECKS: list[dict[str, object]] = []


def add_check(kind: str, subject: str, critical: bool, status: str, fix: str = "") -> None:
    CHECKS.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )


def fail_fix(action: str) -> str:
    return f"{action}; then check {TRIPLETS} for matching COSIPY recovery guidance."


def print_result(kind: str, subject: str, status: str, critical: bool, detail: str = "") -> None:
    label = "OK" if status == "pass" else "FAIL"
    crit = "critical" if critical else "noncritical"
    print(f"  {label:<4} {kind:<8} {crit:<11} {subject}")
    if detail:
        print(f"       {detail}")


def emit_report() -> None:
    blockers = [c for c in CHECKS if c["status"] != "pass" and c.get("critical")]
    if blockers:
        print()
        print("  Blockers found. Fix these before running COSIPY:")
        for check in blockers:
            print(f"  - {check['subject']}: {check['fix']}")
    else:
        print()
        print("  STATUS: PREFLIGHT PASSED")

    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": CHECKS}, sort_keys=True))
    sys.exit(1 if blockers else 0)


def run_command(args: list[str], *, cwd: Path | None = None, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    pythonpath = [str(SOURCE_DIR), str(NETCDF_SHIM)]
    if env.get("PYTHONPATH"):
        pythonpath.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def check_python_binary() -> None:
    subject = os.path.realpath(HYDRO_PYTHON)
    if not HYDRO_PYTHON.exists():
        status = "fail"
        fix = fail_fix(f"Restore the HydroCraft Python interpreter at {HYDRO_PYTHON}")
        add_check("binary", subject, True, status, fix)
        print_result("binary", subject, status, True, fix)
        return

    if not os.access(HYDRO_PYTHON, os.X_OK):
        status = "fail"
        fix = fail_fix(f"Make the HydroCraft Python interpreter executable: chmod +x {HYDRO_PYTHON}")
        add_check("binary", subject, True, status, fix)
        print_result("binary", subject, status, True, fix)
        return

    try:
        proc = run_command([str(HYDRO_PYTHON), "-c", "import sys; print(sys.version.split()[0])"], timeout=10)
    except Exception as exc:  # noqa: BLE001
        status = "fail"
        fix = fail_fix(f"Ensure {HYDRO_PYTHON} starts without crashing: {exc}")
        add_check("binary", subject, True, status, fix)
        print_result("binary", subject, status, True, fix)
        return

    status = "pass" if proc.returncode == 0 else "fail"
    detail = (proc.stdout or proc.stderr).strip()
    fix = "" if status == "pass" else fail_fix(f"Fix interpreter startup for {HYDRO_PYTHON}: {proc.stderr.strip()}")
    add_check("binary", subject, True, status, fix)
    print_result("binary", subject, status, True, detail or fix)


def check_file(path: Path, label: str, *, critical: bool = True, executable: bool = False) -> None:
    subject = str(path)
    if not path.is_file():
        status = "fail"
        fix = fail_fix(f"Restore required file {path}")
    elif executable and not os.access(path, os.X_OK):
        status = "fail"
        fix = fail_fix(f"Make required executable file runnable: chmod +x {path}")
    else:
        status = "pass"
        fix = ""
    add_check("data", subject, critical, status, fix)
    print_result("data", f"{label}: {subject}", status, critical, fix)


def check_dir(path: Path, label: str, *, critical: bool = True) -> None:
    subject = str(path)
    if path.is_dir() and any(path.iterdir()):
        status = "pass"
        fix = ""
        detail = f"{len(list(path.iterdir()))} items"
    elif path.is_dir():
        status = "fail"
        fix = fail_fix(f"Populate required directory {path}")
        detail = fix
    else:
        status = "fail"
        fix = fail_fix(f"Restore required directory {path}")
        detail = fix
    add_check("data", subject, critical, status, fix)
    print_result("data", f"{label}: {subject}", status, critical, detail)


def check_imports() -> None:
    modules = [
        "cosipy",
        "COSIPY",
        "numpy",
        "pandas",
        "scipy",
        "xarray",
        "dask",
        "distributed",
        "numba",
        "h5netcdf",
        "netCDF4",
    ]
    code = r"""
import importlib
import json
mods = MODS
out = {}
for name in mods:
    try:
        module = importlib.import_module(name)
        out[name] = {"ok": True, "file": getattr(module, "__file__", "")}
    except Exception as exc:
        out[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
print(json.dumps(out, sort_keys=True))
""".replace("MODS", repr(modules))

    try:
        proc = run_command([str(HYDRO_PYTHON), "-c", code], cwd=SOURCE_DIR, timeout=45)
        payload = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    except Exception as exc:  # noqa: BLE001
        payload = {name: {"ok": False, "error": f"import harness failed: {exc}"} for name in modules}

    for module in modules:
        result = payload.get(module, {"ok": False, "error": "no result from import harness"})
        status = "pass" if result.get("ok") else "fail"
        if module in {"cosipy", "COSIPY"}:
            fix = fail_fix(
                f"Run from {SOURCE_DIR} or add it to PYTHONPATH when using {HYDRO_PYTHON}"
            )
        else:
            fix = fail_fix(f"Install missing dependency into KISSPATH_PYTHON_ENV: {module}")
        add_check("import", f"{module} via {HYDRO_PYTHON}", True, status, "" if status == "pass" else fix)
        detail = str(result.get("file") or result.get("error") or "")
        print_result("import", f"{module} via {HYDRO_PYTHON}", status, True, detail)


def load_toml(path: Path) -> dict:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore[no-redef]

    with path.open("rb") as handle:
        return tomllib.load(handle)


def check_default_config_data() -> None:
    config_path = SOURCE_DIR / "config.toml"
    constants_path = SOURCE_DIR / "constants.toml"
    check_file(config_path, "default config.toml")
    check_file(constants_path, "default constants.toml")
    if not config_path.is_file():
        return

    try:
        cfg = load_toml(config_path)
        data_path = Path(cfg.get("FILENAMES", {}).get("data_path", "./data/"))
        if not data_path.is_absolute():
            data_path = SOURCE_DIR / data_path
        input_netcdf = cfg.get("FILENAMES", {}).get("input_netcdf", "")
        forcing_path = data_path / "input" / input_netcdf
    except Exception as exc:  # noqa: BLE001
        subject = str(config_path)
        fix = fail_fix(f"Repair parseable TOML in {config_path}: {exc}")
        add_check("data", subject, True, "fail", fix)
        print_result("data", f"default config parse: {subject}", "fail", True, fix)
        return

    check_file(forcing_path, "default forcing netCDF")
    check_file(SOURCE_DIR / "data" / "static" / "Zhadang_static.nc", "default static netCDF")
    check_file(SOURCE_DIR / "data" / "static" / "DEM" / "n30_e090_3arc_v2.tif", "default DEM")
    check_file(SOURCE_DIR / "data" / "static" / "Shapefiles" / "Zhadang_RGI6.shp", "default shapefile")

    inspect_netcdf(forcing_path, ["T2", "RH2", "U2", "G", "PRES", "RRR"], "forcing variables")
    inspect_netcdf(SOURCE_DIR / "data" / "static" / "Zhadang_static.nc", ["HGT", "ASPECT", "SLOPE", "MASK"], "static variables")


def inspect_netcdf(path: Path, variables: list[str], label: str) -> None:
    subject = f"{path} variables {','.join(variables)}"
    if not path.is_file():
        fix = fail_fix(f"Restore netCDF file {path}")
        add_check("data", subject, True, "fail", fix)
        print_result("data", label, "fail", True, fix)
        return

    code = r"""
import json
import xarray as xr
path = PATH
wanted = WANTED
last = None
for engine in (None, "h5netcdf", "netcdf4"):
    try:
        ds = xr.open_dataset(path) if engine is None else xr.open_dataset(path, engine=engine)
        present = set(ds.data_vars) | set(ds.coords)
        missing = [v for v in wanted if v not in present]
        print(json.dumps({"ok": not missing, "missing": missing, "engine": engine or "default"}))
        ds.close()
        break
    except Exception as exc:
        last = f"{type(exc).__name__}: {exc}"
else:
    print(json.dumps({"ok": False, "missing": wanted, "error": last}))
""".replace("PATH", repr(str(path))).replace("WANTED", repr(variables))

    try:
        proc = run_command([str(HYDRO_PYTHON), "-c", code], cwd=SOURCE_DIR, timeout=30)
        result = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {"ok": False, "error": proc.stderr}
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": str(exc)}

    status = "pass" if result.get("ok") else "fail"
    fix = "" if status == "pass" else fail_fix(f"Repair {path}; missing/unreadable {label}: {result}")
    add_check("data", subject, True, status, fix)
    detail = f"engine={result.get('engine')}" if status == "pass" else fix
    print_result("data", label, status, True, detail)


def main() -> None:
    print("=" * 60)
    print("  PREFLIGHT CHECK: COSIPY")
    print("=" * 60)
    print()

    try:
        check_python_binary()
        check_dir(SOURCE_DIR, "COSIPY source repository")
        check_file(SOURCE_DIR / "COSIPY.py", "COSIPY entry point")
        check_dir(KI_DIR / "tools", "KI tools")
        for tool in ("run_cosipy.py", "convert_forcing.py", "convert_static.py", "parse_output.py"):
            check_file(KI_DIR / "tools" / tool, f"KI tool {tool}")
        check_file(NETCDF_SHIM / "sitecustomize.py", "netCDF shim", critical=False)
        check_file(TRIPLETS, "diagnostic triplets", critical=False)
        check_imports()
        check_default_config_data()
    except Exception:  # noqa: BLE001
        subject = "preflight_check.py internal error"
        fix = fail_fix("Repair preflight_check.py so it completes without crashing")
        add_check("run", subject, True, "fail", fix)
        print_result("run", subject, "fail", True, traceback.format_exc())

    emit_report()


if __name__ == "__main__":
    main()
