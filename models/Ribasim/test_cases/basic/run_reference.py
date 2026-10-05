#!/usr/bin/env python3
"""Run the official Ribasim test model "basic" and check expected.json.

Foundation case for the Ribasim KI. The inputs are the files written by Ribasim's own
generator (utils/generate-testmodels.py basic -> ribasim_testmodels.basic_model()).
The run goes through the KI's own tools/run_ribasim.py. The end-of-run basin storage is
checked against the values asserted in Ribasim's own Julia test
(core/test/run_models_test.jl, testitem "basic model", atol = 1.5).
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

ribasim lookup: --ribasim-bin -> $RIBASIM_BIN -> which ribasim -> server default.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_ribasim.py"
_DEF = "/mnt/disk1/Hydrocraft_server/models/Ribasim/bin/ribasim"
SOURCES = ["Initial", "LevelBoundary", "FlowBoundary", "UserDemand",
           "Drainage", "Precipitation", "SurfaceRunoff"]


def summarise(res):
    import numpy as np
    import xarray as xr
    o = {}
    with xr.open_dataset(res / "basin.nc") as b:
        o["basin_n_times"] = b.sizes["time"]
        o["basin_n_nodes"] = b.sizes["node_id"]
        # basin.nc storage is at the START of each day; storage_rate is the mean over that
        # day, so storage at the model end time = last storage + last rate * 86400 s.
        end = (b.storage.isel(time=-1) + b.storage_rate.isel(time=-1) * 86400.0)
        for nid in (1, 3, 6, 9):
            o[f"end_storage_basin_{nid}"] = end.sel(node_id=nid).item()
        o["max_abs_balance_error"] = float(np.abs(b.balance_error).max())
        o["max_abs_relative_error"] = float(np.abs(b.relative_error).max())
        o["total_precipitation_m3"] = float(b.precipitation.sum() * 86400.0)
        o["total_evaporation_m3"] = float(b.evaporation.sum() * 86400.0)
        o["max_level_m"] = float(b.level.max())
    with xr.open_dataset(res / "flow.nc") as f:
        o["flow_n_links"] = f.sizes["link_id"]
    with xr.open_dataset(res / "concentration.nc") as c:
        cc = c.concentration
        o["continuity_max_dev"] = float(np.abs(cc.sel(substance="Continuity") - 1).max())
        src = [s for s in SOURCES if s in c.substance.values]
        o["source_sum_max_dev"] = float(np.abs(cc.sel(substance=src).sum("substance") - 1).max())
        o["residence_time_min_positive"] = float(cc.sel(substance="ResidenceTime").min() > 0)
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ribasim-bin")
    a = ap.parse_args()
    b = next((c for c in (a.ribasim_bin, os.environ.get("RIBASIM_BIN"), shutil.which("ribasim"), _DEF)
              if c and Path(c).is_file()), None)
    if not b:
        print("MISSING DEPENDENCY: ribasim engine not found (set RIBASIM_BIN). NOT run.", file=sys.stderr)
        return 3
    try:
        import numpy, xarray, netCDF4  # noqa: F401
    except ImportError as ex:
        print(f"MISSING DEPENDENCY: python package {ex.name} (needed to read results). NOT run.",
              file=sys.stderr)
        return 3
    run = Path(tempfile.mkdtemp(prefix="ribasim_basic_"))
    shutil.copytree(HERE / "inputs", run / "basic")
    toml = run / "basic" / "ribasim.toml"
    fails = []
    try:
        cp = subprocess.run([sys.executable, str(RUN_TOOL), "--toml_path", str(toml),
                             "--ribasim_bin", b, "--timeout", "1200"],
                            capture_output=True, text=True, timeout=1500, cwd=run)
        log = run / "basic" / "results" / "ribasim.log"
        ok_line = log.is_file() and "The model finished successfully" in log.read_text(errors="replace")
        if cp.returncode != 0 or not ok_line:
            fails.append(f"run_ribasim.py failed (rc={cp.returncode}, success line={ok_line}): "
                         f"{(cp.stdout + cp.stderr)[-600:]}")
        else:
            print("  ran ribasim through KI tools/run_ribasim.py (rc=0, 'The model finished successfully')")
            try:
                got = summarise(run / "basic" / "results")
            except Exception as ex:
                got = {}
                fails.append(f"could not read outputs: {ex}")
            for c in EXP["numeric_checks"]:
                v = got.get(c["name"])
                if v is None:
                    fails.append(f"{c['name']}: not computed")
                elif abs(v - c["expected"]) > c["tol"]:
                    fails.append(f"{c['name']}: {v:.10g} vs {c['expected']}+-{c['tol']}")
                else:
                    print(f"  OK {c['name']}: {v:.10g}")
    finally:
        shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: Ribasim basic test model matches the official Ribasim test values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
