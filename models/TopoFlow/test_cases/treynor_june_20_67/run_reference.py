#!/usr/bin/env python3
"""Run the official TopoFlow Treynor (Iowa) June 20 1967 storm example and check it.

Steps:
  1. Copy inputs/ to a fresh temp dir.
  2. In the temp copy ONLY, apply the three run-setup changes listed in
     README.md (out_directory -> temp dir; rain file also placed in the
     in_directory; disabled 'ice' line commented out of the provider file).
  3. Run the model through the KI run tool (tools/run_topoflow.py).
  4. Read the report and output files and compare with expected.json.
  5. Delete the temp dir (unless --keep).

Exit codes: 0 PASS, 2 checks failed (or run failed), 3 engine/dependency missing.

Engine lookup (a Python that can import topoflow.framework.emeli):
  --topoflow-python ARG -> $TOPOFLOW_PYTHON -> `which python3` -> server default venv.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN_TOOL = HERE.parents[1] / "tools" / "run_topoflow.py"
DEFAULT_PY = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/TopoFlow/venv/bin/python"
CASE_DIR = "Treynor_Iowa_30m/__No_Infil_June_20_67_Rain"
PREFIX = "June_20_67"


def can_import(py):
    if not py or not os.path.isfile(py) or not os.access(py, os.X_OK):
        return False
    try:
        r = subprocess.run([py, "-c", "import topoflow.framework.emeli, netCDF4"],
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0
    except Exception:
        return False


def find_python(arg):
    cands = [arg, os.environ.get("TOPOFLOW_PYTHON"), shutil.which("python3"), DEFAULT_PY]
    for c in cands:
        if can_import(c):
            return c
    return None


def prepare(tmp):
    root = tmp / "inputs"
    shutil.copytree(HERE / "inputs", root)
    case = root / CASE_DIR
    out = tmp / "out"
    out.mkdir()
    # (a) path setting: write outputs to the temp dir, not ~/TF_Output/Treynor
    pi = case / f"{PREFIX}_path_info.cfg"
    txt = pi.read_text()
    new = re.sub(r"^(out_directory\s*\|\s*)~/TF_Output/Treynor\s*(\|)",
                 lambda m: f"{m.group(1)}{out}  {m.group(2)}", txt, flags=re.M)
    assert new != txt, "out_directory line not found"
    pi.write_text(new)
    # (b) file layout: in_directory is '..' and the meteorology component reads
    #     the rain file from there, so place a byte-identical copy there too.
    shutil.copy2(case / f"{PREFIX}_rain_rates.txt", root / "Treynor_Iowa_30m" / f"{PREFIX}_rain_rates.txt")
    # (c) provider file: the ice component is 'Disabled' in its cfg, but a
    #     disabled ice component has no h_ice and the framework crashes while
    #     linking components (same with upstream HEAD code). Comment it out.
    pf = case / f"{PREFIX}_providers.txt"
    txt = pf.read_text()
    new = re.sub(r"^ice(\s+)tf_ice_gc2d", r"# ice\1tf_ice_gc2d", txt, flags=re.M)
    assert new != txt, "ice provider line not found"
    pf.write_text(new)
    return case, out


def num(pattern, text, name):
    m = re.search(pattern, text, flags=re.M)
    if not m:
        raise ValueError(f"could not find {name} in model report")
    return float(m.group(1))


def collect(py, stdout, out):
    v = {}
    v["n_timesteps_driver"] = num(r"Number of timesteps:\s*(\d+)", stdout, "timesteps")
    v["simulated_time_min"] = num(r"Simulated time:\s*([\d.]+)", stdout, "simulated time")
    v["Q_peak_m3s"] = num(r"^Q_peak:\s*([\d.eE+-]+)", stdout, "Q_peak")
    v["Q_peak_time_min"] = num(r"^Q_peak_time:\s*([\d.eE+-]+)", stdout, "Q_peak_time")
    v["Q_outlet_final_m3s"] = num(r"^Q_outlet \(final\):\s*([\d.eE+-]+)", stdout, "Q_outlet final")
    v["vol_P_m3"] = num(r"vol_P\s+\(precip\):\s*([\d.eE+-]+)", stdout, "vol_P")
    v["vol_edge_m3"] = num(r"vol_edge \(boundary\):\s*([\d.eE+-]+)", stdout, "vol_edge")
    v["vol_Q_outlet_m3"] = num(r"vol_Q\s+\(discharge\):\s*([\d.eE+-]+)", stdout, "vol_Q")
    v["vol_chan_final_m3"] = num(r"vol_chan_final\s+\(channels\):\s*([\d.eE+-]+)", stdout, "vol_chan_final")
    v["mass_balance_rel_error"] = num(r"vol_error/ vol_in =\s*([\d.eE+-]+)", stdout, "vol_error/vol_in")
    # outlet hydrograph text file (read directly; KI parse_output.py cannot read its header)
    rows = []
    for line in (out / f"{PREFIX}_0D-Q.txt").read_text().splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 2:
            rows.append([float(x) for x in parts])
    q = [r[1] for r in rows]
    v["hydrograph_0D_rows"] = float(len(rows))
    v["hydrograph_0D_Q_max_m3s"] = max(q)
    v["hydrograph_0D_Q_sum_x60s_m3"] = sum(q) * 60.0
    # 2D Q grid stack (netCDF) read with the engine python
    snip = ("import netCDF4,json;d=netCDF4.Dataset(r'%s');Q=d.variables['Q'][:];"
            "print(json.dumps([int(Q.shape[0]),float(Q.max()),float(Q[-1].max())]))" % (out / f"{PREFIX}_2D-Q.nc"))
    r = subprocess.run([py, "-c", snip], capture_output=True, text=True, timeout=300)
    n, qmax, qlast = json.loads(r.stdout.strip().splitlines()[-1])
    v["grid_2D_Q_frames"] = float(n)
    v["grid_2D_Q_max_m3s"] = qmax
    v["grid_2D_Q_last_frame_max_m3s"] = qlast
    return v


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topoflow-python", default=None, help="Python that can import topoflow")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    ap.add_argument("--timeout", type=int, default=1200)
    args = ap.parse_args()

    py = find_python(args.topoflow_python)
    if py is None:
        print("MISSING DEPENDENCY: no Python that can import topoflow.framework.emeli and netCDF4 "
              "(tried --topoflow-python, $TOPOFLOW_PYTHON, which python3, %s). NOT run." % DEFAULT_PY)
        return 3
    if not RUN_TOOL.is_file():
        print(f"MISSING DEPENDENCY: KI run tool {RUN_TOOL} not found. NOT run.")
        return 3

    expected = json.loads((HERE / "expected.json").read_text())
    tmp = Path(tempfile.mkdtemp(prefix="topoflow_treynor_"))
    try:
        case, out = prepare(tmp)
        cmd = [py, str(RUN_TOOL), "--cfg_prefix", PREFIX, "--cfg_directory", str(case)]
        print("Engine python :", py)
        print("Running       :", " ".join(cmd))
        try:
            p = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=args.timeout)
        except subprocess.TimeoutExpired:
            print(f"FAIL: run took longer than {args.timeout} s")
            return 2
        (tmp / "run_stdout.txt").write_text(p.stdout)
        (tmp / "run_stderr.txt").write_text(p.stderr)
        stdout = p.stdout
        tool_status = None
        jm = re.search(r"^\{\n.*\n\}\s*$", stdout, flags=re.M | re.S)
        if jm:
            try:
                tool_status = json.loads(jm.group(0)).get("status")
            except Exception:
                pass
        finished = [
            ("return_code_0", p.returncode == 0),
            ("ki_tool_status_success", tool_status == "success"),
            ("model_line_'Simulation complete.'", "Simulation complete." in stdout),
            ("model_line_'Finished. (June_20_67)'", "Finished. (June_20_67)" in stdout),
            ("stop_rule_'Reached Q_peak fraction = 0.05'", "Stopping: Reached Q_peak fraction = 0.05." in stdout),
        ]
        ok = True
        for name, good in finished:
            print(f"  [{'ok' if good else 'FAIL'}] {name}")
            ok &= good
        if not ok:
            print("--- stdout tail ---\n" + stdout[-3000:] + "\n--- stderr tail ---\n" + p.stderr[-3000:])
            print("RESULT: FAIL (run did not finish normally)")
            return 2
        got = collect(py, stdout, out)
        for chk in expected["numeric_checks"]:
            name, exp, tol = chk["name"], chk["expected"], chk["tol"]
            val = got.get(name)
            good = val is not None and abs(val - exp) <= tol
            print(f"  [{'ok' if good else 'FAIL'}] {name}: got {val!r} expected {exp!r} +/- {tol}")
            ok &= good
        print("RESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 2
    finally:
        if args.keep:
            print("kept temp dir:", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
