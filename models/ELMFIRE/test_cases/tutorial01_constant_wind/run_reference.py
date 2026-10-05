#!/usr/bin/env python3
"""Run the official ELMFIRE Tutorial 01 (flat ground, constant wind) and check expected.json.

Foundation case for the ELMFIRE KI. It runs the tutorial exactly as ELMFIRE's own docs say
(`./01-run.sh`): the script builds constant GeoTIFF inputs with GDAL, runs ELMFIRE, turns
the outputs into GeoTIFFs and draws hourly isochrones. Everything happens in a fresh temp dir.

One small change, made ONLY in the temp copy: the official elmfire.data.in says
PATH_TO_GDAL = '/usr/bin'. On this server GDAL lives elsewhere, so the temp copy points
PATH_TO_GDAL at the folder that holds gdal_translate on PATH. This only tells ELMFIRE where
to find gdal_translate (used to turn the input .tif files into .bsq); it does not touch any
model setting.

Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.
Engine lookup: --elmfire-bin -> $ELMFIRE_BIN -> which elmfire_2025.1002 -> server default.
Run with a Python that has osgeo.gdal + numpy (server: /mnt/disk1/Hydrocraft_server/python_env/bin/python).
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
ELMFIRE_VER = "2025.1002"
_DEF = ("/home/server/knowledge-dissection-toolkit/auto_dissect/_work/ELMFIRE/source/repo/"
        f"build/linux/bin/elmfire_{ELMFIRE_VER}")
GDAL_TOOLS = ("gdalwarp", "gdal_calc.py", "gdal_translate", "gdal_contour")
SUCCESS_LINE = "End of simulation reached successfully"
CELL_M2 = 30.0 * 30.0
M2_PER_ACRE = 4046.8564224


def find_engine(arg):
    for c in (arg, os.environ.get("ELMFIRE_BIN"), shutil.which(f"elmfire_{ELMFIRE_VER}"), _DEF):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return str(Path(c).resolve())
    return None


def read_band(fp):
    from osgeo import gdal
    import numpy as np
    gdal.UseExceptions()
    ds = gdal.Open(str(fp))
    b = ds.GetRasterBand(1)
    a = b.ReadAsArray().astype(float)
    nd = b.GetNoDataValue()
    gt = ds.GetGeoTransform()
    ds = None
    valid = np.isfinite(a) & (a > -9998) & ((a != nd) if nd is not None else True)
    return a, valid, gt


def collect(run_case, stdout):
    import numpy as np
    from osgeo import ogr
    ogr.UseExceptions()
    out = run_case / "outputs"
    toa_f = sorted(out.glob("time_of_arrival_*.tif"))
    flin_f = sorted(out.glob("flin_*.tif"))
    vs_f = sorted(out.glob("vs_*.tif"))
    if not (toa_f and flin_f and vs_f):
        raise RuntimeError(f"missing output GeoTIFFs in {out}: {sorted(p.name for p in out.iterdir())}")
    toa, tv, gt = read_band(toa_f[0])
    burned = tv & (toa >= 0)
    flin, fv, _ = read_band(flin_f[0])
    vs, vv, _ = read_band(vs_f[0])
    rows, cols = np.nonzero(burned)
    ys = gt[3] + (rows + 0.5) * gt[5]          # cell-centre northing (m)
    m = re.search(r"Fire area:\s*([\d.]+)\s*acres", stdout)
    shp = ogr.Open(str(out / "hourly_isochrones.shp"))
    n_iso = shp.GetLayer(0).GetFeatureCount() if shp else -1
    shp = None
    return {
        "output_time_s": int(re.search(r"_(\d+)\.tif$", toa_f[0].name).group(1)),
        "stdout_fire_area_acres": float(m.group(1)) if m else -1.0,
        "burned_cells": int(burned.sum()),
        "burned_area_acres_from_toa": float(burned.sum() * CELL_M2 / M2_PER_ACRE),
        "toa_max_s": float(toa[burned].max()),
        "toa_mean_s": float(toa[burned].mean()),
        "flin_max_kw_m": float(flin[fv & burned].max()),
        "flin_mean_kw_m": float(flin[fv & burned].mean()),
        "vs_max_ft_min": float(vs[vv & burned].max()),
        "vs_mean_ft_min": float(vs[vv & burned].mean()),
        "burned_north_edge_y_m": float(ys.max()),
        "burned_south_edge_y_m": float(ys.min()),
        "hourly_isochrone_features": int(n_iso),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elmfire-bin")
    ap.add_argument("--record", action="store_true", help="print measured values as JSON, no checks")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()

    eng = find_engine(a.elmfire_bin)
    if not eng:
        print(f"MISSING DEPENDENCY: ELMFIRE engine elmfire_{ELMFIRE_VER} not found "
              "(use --elmfire-bin or $ELMFIRE_BIN). NOT run.", file=sys.stderr)
        return 3
    missing = [t for t in GDAL_TOOLS + ("bc", "bash") if not shutil.which(t)]
    if missing:
        print(f"MISSING DEPENDENCY: {', '.join(missing)} not on PATH. NOT run.", file=sys.stderr)
        return 3
    try:
        import numpy  # noqa: F401
        from osgeo import gdal, ogr  # noqa: F401
    except ImportError as e:
        print(f"MISSING DEPENDENCY: Python osgeo.gdal/numpy ({e}). Run with "
              "/mnt/disk1/Hydrocraft_server/python_env/bin/python. NOT run.", file=sys.stderr)
        return 3

    tmp = Path(tempfile.mkdtemp(prefix="elmfire_tut01_"))
    shutil.copytree(HERE / "inputs", tmp / "tutorials")
    case = tmp / "tutorials" / "01-constant-wind"
    # Server-only tweak in the temp copy: where gdal_translate lives (see docstring).
    gdal_dir = str(Path(shutil.which("gdal_translate")).parent)
    dat = case / "elmfire.data.in"
    txt = dat.read_text()
    txt2 = re.sub(r"(?m)^PATH_TO_GDAL\s*=.*$", f"PATH_TO_GDAL                   = '{gdal_dir}'", txt)
    assert txt2 != txt or f"'{gdal_dir}'" in txt, "PATH_TO_GDAL line not found"
    dat.write_text(txt2)
    # The tutorial calls `elmfire_$ELMFIRE_VER` from PATH: put the chosen engine first.
    bindir = tmp / "bin"
    bindir.mkdir()
    (bindir / f"elmfire_{ELMFIRE_VER}").symlink_to(eng)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", ELMFIRE_VER=ELMFIRE_VER,
               OMP_NUM_THREADS="1")

    print(f"  engine: {eng}")
    print(f"  running ./01-run.sh in {case}")
    cp = subprocess.run(["bash", "./01-run.sh"], cwd=case, env=env, capture_output=True,
                        text=True, timeout=1200)
    log = cp.stdout + cp.stderr
    (tmp / "run.log").write_text(log)

    fails = []
    if cp.returncode != 0:
        fails.append(f"01-run.sh rc={cp.returncode}")
    if SUCCESS_LINE not in log:
        fails.append(f"engine success line '{SUCCESS_LINE}' not in output; tail:\n{log[-1500:]}")
    got = {}
    if not fails:
        try:
            got = collect(case, log)
        except Exception as e:  # outputs missing/unreadable
            fails.append(f"could not read outputs: {e}")

    if a.record:
        print(json.dumps(got, indent=2))
    elif got:
        print(f"  OK finished normally (rc=0, '{SUCCESS_LINE}')")
        for c in EXP["numeric_checks"]:
            v = got[c["name"]]
            if abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}+-{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.6g}")

    if a.keep:
        print(f"  kept run dir: {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    if a.record:
        return 0
    print("PASS: ELMFIRE Tutorial 01 (constant wind) reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
