#!/usr/bin/env python3
"""Run the official PyAEZ Module I (Climate Regime, tutorial NB1) Laos example and check it.

Foundation case for the PyAEZ KI. The official Laos demo climate data (monthly, 194 x 169
grid) is copied to a fresh temp dir and Module I is run through the KI's own
tools/run_pyaez.py (--modules 1). The output rasters are then compared with the official
NB1 output rasters that ship in the PyAEZ repo (reference/NB1/) and with expected.json.

Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Engine lookup:
  Python with GDAL: --python -> $PYAEZ_PYTHON -> `which python_with_gdal` -> server default
  pyaez source dir: --pyaez-src -> $PYAEZ_SRC -> server default (dir that holds pyaez/)
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_pyaez.py"
_DEF_PY = "/mnt/disk1/Hydrocraft_server/python_env/bin/python_with_gdal"
_DEF_SRC = "/mnt/disk1/Hydrocraft_server/models/PyAEZ/source/repo"

# our output name -> official NB1 reference file
REF = {
    "thermal_climate": "LAO_ThermalClimate.tif", "thermal_zone": "LAO_ThermalZone.tif",
    "lgpt0": "LAO_LGPt0.tif", "lgpt5": "LAO_LGPt5.tif", "lgpt10": "LAO_LGPt10.tif",
    "tsum0": "LAO_tsum0.tif", "tsum5": "LAO_tsum5.tif", "tsum10": "LAO_tsum10.tif",
    "lgp": "LAO_LGP.tif", "lgp_equv": "LAO_LGPEquivalent.tif",
}


def measure(out_dir):
    """Read Module I rasters (needs GDAL; run under the PyAEZ python). Print JSON."""
    import numpy as np
    from osgeo import gdal
    gdal.UseExceptions()

    def read(fp):
        ds = gdal.Open(str(fp))
        b = ds.GetRasterBand(1)
        a, nd = b.ReadAsArray().astype(float), b.GetNoDataValue()
        ds = None
        ok = np.isfinite(a) & ((a != nd) if nd is not None else True)
        return a, ok

    got = {}
    _, mask_ok = read(Path(out_dir) / "thermal_climate.tif")
    got["mask_cells"] = int(mask_ok.sum())
    for name, ref in REF.items():
        a, ok = read(Path(out_dir) / f"{name}.tif")
        b, okb = read(HERE / "reference" / "NB1" / ref)
        cells = ok & okb
        got[f"{name}_cells"] = int(ok.sum())
        got[f"{name}_cells_missing_in_official"] = int((ok & ~okb).sum())
        got[f"{name}_maxdiff_vs_official"] = float(np.abs(a - b)[cells].max())
        got[f"{name}_ndiff_vs_official"] = int((np.abs(a - b)[cells] > 1e-6).sum())
        got[f"{name}_mean"] = float(a[ok].mean())
        got[f"{name}_min"] = float(a[ok].min())
        got[f"{name}_max"] = float(a[ok].max())
    print("MEASURE_JSON=" + json.dumps(got))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python")
    ap.add_argument("--pyaez-src")
    ap.add_argument("--_measure", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a._measure:
        measure(a._measure)
        return 0

    py = next((c for c in (a.python, os.environ.get("PYAEZ_PYTHON"),
                           shutil.which("python_with_gdal"), _DEF_PY)
               if c and Path(c).is_file()), None)
    src = next((c for c in (a.pyaez_src, os.environ.get("PYAEZ_SRC"), _DEF_SRC)
                if c and (Path(c) / "pyaez" / "ClimateRegime.py").is_file()), None)
    if not py or not src:
        print("MISSING DEPENDENCY: "
              + ("Python with GDAL (set PYAEZ_PYTHON or --python) " if not py else "")
              + ("pyaez source dir with pyaez/ (set PYAEZ_SRC or --pyaez-src) " if not src else "")
              + "NOT run.", file=sys.stderr)
        return 3
    if not RUN_TOOL.is_file():
        print(f"MISSING DEPENDENCY: KI run tool {RUN_TOOL} NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="pyaez_nb1_"))
    env = dict(os.environ, PYTHONPATH=src + (os.pathsep + os.environ["PYTHONPATH"]
                                             if os.environ.get("PYTHONPATH") else ""),
               PYTHONDONTWRITEBYTECODE="1", NUMBA_CACHE_DIR=str(run / "numba_cache"))
    try:
        cp = subprocess.run([py, "-c", "import pyaez.ClimateRegime, numba; from osgeo import gdal"],
                            env=env, cwd=run, capture_output=True, text=True)
        if cp.returncode != 0:
            print(f"MISSING DEPENDENCY: {py} cannot import pyaez/numba/osgeo.gdal "
                  f"({cp.stderr.strip().splitlines()[-1] if cp.stderr.strip() else '?'}). NOT run.",
                  file=sys.stderr)
            return 3

        data = run / "data_input"
        shutil.copytree(HERE / "inputs", data)
        cmd = [py, str(RUN_TOOL), "--data-dir", str(data), "--crop-name", "maiz",
               "--crop-params", "input_crop_TSUM_parameters_maiz_sugar.xlsx",
               "--lat-min", "13.87", "--lat-max", "22.59",
               "--output-dir", str(run / "out"), "--modules", "1"]
        cp = subprocess.run(cmd, env=env, cwd=run, capture_output=True, text=True, timeout=1200)
        print("\n".join("  | " + l for l in cp.stdout.strip().splitlines()))
        fails = []
        ok_line = "All pipeline outputs validated successfully"
        if cp.returncode != 0 or ok_line not in cp.stdout:
            fails.append(f"run_pyaez.py failed (rc={cp.returncode}): {cp.stderr[-600:]}")
        else:
            print(f"  OK finished: rc=0 and '{ok_line}'")
            cp2 = subprocess.run([py, str(Path(__file__).resolve()), "--_measure",
                                  str(run / "out" / "NB1")],
                                 env=env, cwd=run, capture_output=True, text=True)
            line = [l for l in cp2.stdout.splitlines() if l.startswith("MEASURE_JSON=")]
            if not line:
                fails.append(f"reading outputs failed: {cp2.stderr[-600:]}")
            else:
                got = json.loads(line[0].split("=", 1)[1])
                for c in EXP["numeric_checks"]:
                    v = got.get(c["name"])
                    if v is None or abs(v - c["expected"]) > c["tol"]:
                        fails.append(f"{c['name']}: {v} vs {c['expected']}+-{c['tol']}")
                    else:
                        print(f"  OK {c['name']}: {v:.6g}")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: PyAEZ Module I (Laos NB1) reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
