#!/usr/bin/env python3
"""Run the official Cell2Fire (C2F-W) Scott & Burgan test case and check expected.json.

Foundation case for the Cell2Fire KI. This is the 'sb-asc' case of C2F-W's own test
suite (test/test.sh): a 7x7 grid that holds one cell of each Scott & Burgan fuel type,
113 fires, seed 123. The run uses the exact official command line, in the same
relative folder layout the official test uses (model/sb-asc -> test_results/sb-asc),
so the output files can be compared byte for byte with the official target results
in reference/target_results.zip (unmodified copy from the C2F-W repo).

The KI run tool (tools/run_cell2fire.py) is NOT used: it refuses this case because it
demands an elevation raster, and it always adds extra flags the official command does
not use. See README "Known KI gaps".

Exit 0 PASS, 2 checks failed, 3 engine missing.
Binary lookup: --cell2fire-bin -> $CELL2FIRE_BIN -> `which Cell2Fire` -> server default.
Extra: --print-metrics DIR prints the metrics of an existing output folder and exits.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
REF_ZIP = HERE / "reference" / "target_results.zip"
REF_PREFIX = "target_results/sb-asc/"
_DEF = ("/home/server/knowledge-dissection-toolkit/auto_dissect/_work/Cell2Fire/"
        "source/repo/Cell2Fire/Cell2Fire")
INPUTS = ("fuels.asc", "Weather.csv", "spain_lookup_table.csv")
NSIMS = 113
# Official command from C2F-W test/test.sh for model=sb, format=asc.
ARGS = ["--input-instance-folder", "model/sb-asc", "--output-folder", "test_results/sb-asc",
        "--nsims", str(NSIMS), "--output-messages", "--grids", "--out-intensity",
        "--sim", "S", "--seed", "123", "--ignitionsLog", "--scenario", "1"]


def find_bin(cli):
    for c in (cli, os.environ.get("CELL2FIRE_BIN"), shutil.which("Cell2Fire"), _DEF):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def metrics(out):
    """Numbers read straight from a Cell2Fire output folder (KI parse tool cannot read it)."""
    out = Path(out)
    log = (out / "log.txt").read_text()
    burnt = [int(x) for x in re.findall(r"^\s*Burnt\s+(\d+)", log, re.M)]
    nonburn = [int(x) for x in re.findall(r"^\s*Non-Burnable\s+(\d+)", log, re.M)]
    totals = re.findall(r"^\s*Total\s+(\d+)\s+100\.00%", log, re.M)
    gdirs = sorted((out / "Grids").glob("Grids*"), key=lambda p: int(p.name[5:]))
    ign = [l.split(",") for l in (out / "ignition_and_weather_log.csv").read_text().strip().splitlines()[1:]]
    mfiles = sorted((out / "Messages").glob("MessagesFile*.csv"))
    msgs = [np.loadtxt(f, delimiter=",", ndmin=2) for f in mfiles]
    msg_all = np.vstack([m for m in msgs if m.size])
    # Burnt cells of each fire = ignition cell + every cell that received a spread message.
    # (ForestGrid files under --grids are timed snapshots, not the final scar.)
    ncell = 49
    burnt_map, scar_ok = np.zeros((len(msgs), ncell)), len(msgs) == len(burnt) == len(ign)
    for i, m in enumerate(msgs):
        cells = {int(ign[i][1])} | ({int(c) for c in m[:, 1]} if m.size else set())
        burnt_map[i, [c - 1 for c in cells]] = 1
        if i < len(burnt) and len(cells) != burnt[i]:
            scar_ok = False
    bp = burnt_map.mean(axis=0)
    si = np.array([np.loadtxt(f, skiprows=6) for f in sorted((out / "SurfaceIntensity").glob("SurfaceIntensity*.asc"))])
    return {
        "n_simulations_finished": len(totals),
        "n_message_files": len(msgs),
        "n_surface_intensity_files": len(si),
        "n_grid_folders": len(gdirs),
        "n_ignition_log_rows": len(ign),
        "n_output_files": sum(1 for p in out.rglob("*") if p.is_file()),
        "non_burnable_cells": max(nonburn) if nonburn else -1,
        "message_scar_matches_log_burnt": int(scar_ok),
        "burnt_cells_mean": float(np.mean(burnt)),
        "burnt_cells_min": int(min(burnt)),
        "burnt_cells_max": int(max(burnt)),
        "total_spread_messages": int(msg_all.shape[0]),
        "max_spread_message_period": int(msg_all[:, 2].max()),
        "burn_probability_mean": float(bp.mean()),
        "burn_probability_max": float(bp.max()),
        "surface_intensity_max": float(si.max()),
        "surface_intensity_mean": float(si.mean()),
    }


def compare_with_official(out, tmp):
    """Byte-compare every output file with the official target (log 'version:' line removed, as test.sh does)."""
    ref = tmp / "ref"
    with zipfile.ZipFile(REF_ZIP) as z:
        for n in z.namelist():
            if n.startswith(REF_PREFIX) and not n.endswith("/"):
                z.extract(n, ref)
    ref = ref / REF_PREFIX
    a = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    b = {p.relative_to(ref).as_posix() for p in ref.rglob("*") if p.is_file()}
    diff = len(a ^ b) + sum(1 for r in a & b if (out / r).read_bytes() != (ref / r).read_bytes())
    return diff, len(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell2fire-bin")
    ap.add_argument("--print-metrics")
    ap.add_argument("--keep", action="store_true", help="keep the temp run folder")
    a = ap.parse_args()
    if a.print_metrics:
        print(json.dumps(metrics(a.print_metrics), indent=2))
        return 0
    exe = find_bin(a.cell2fire_bin)
    if not exe:
        print("MISSING DEPENDENCY: Cell2Fire binary not found (set CELL2FIRE_BIN or "
              "--cell2fire-bin). NOT run.", file=sys.stderr)
        return 3

    tmp = Path(tempfile.mkdtemp(prefix="c2f_sb_asc_"))
    (tmp / "model" / "sb-asc").mkdir(parents=True)
    out = tmp / "test_results" / "sb-asc"
    out.mkdir(parents=True)
    for f in INPUTS:
        shutil.copy(HERE / "inputs" / f, tmp / "model" / "sb-asc" / f)
    print(f"  engine: {exe}")
    with open(out / "log.txt", "w") as fh:
        cp = subprocess.run([exe] + ARGS, cwd=tmp, stdout=fh, stderr=subprocess.PIPE,
                            text=True, timeout=600)
    fails = []
    if cp.returncode != 0:
        fails.append(f"Cell2Fire exit code {cp.returncode}: {cp.stderr[-400:]}")
    else:
        print("  OK finished normally: return code 0")
        # official test.sh drops the build 'version:' line before comparing
        txt = (out / "log.txt").read_text()
        (out / "log.txt").write_text("".join(l for l in txt.splitlines(True) if "version:" not in l))
        got = metrics(out)
        got["files_differing_from_official_target"], nref = compare_with_official(out, tmp)
        for c in EXP["numeric_checks"]:
            v = got[c["name"]]
            if abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v:.10g} vs {c['expected']} +/- {c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.10g}")
        print(f"  (compared {nref} official target files byte for byte)")

    if a.keep:
        print(f"  kept run folder: {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: Cell2Fire sb-asc official test reproduced the official target results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
