#!/usr/bin/env python3
"""Run the official USGS TRIGRS tutorial in a clean temp dir and check expected.json.

Foundation case for the TRIGRS KI. Steps (the tutorial's own order):
  1. TopoIndex (tpx) builds the runoff-routing files from dem.asc + directions.asc.
  2. TRIGRS (trg, serial) runs the 2-period rain storm on the 10 x 10 tutorial grid.
TRIGRS is run through the KI's own tools/run_trigrs.py (--skip_compile --skip_topoindex);
TopoIndex is run directly (see README "Known KI gaps"). Output grids are read with the
KI's tools/parse_trigrs_output.py (factor of safety, water-table depth) and directly
(runoff, infiltration, pressure head, list file, mass balance).

Only path settings change, and only in the temp copies (inputs/ stay untouched):
  tpx_in.txt  data/dem.asc, data/directions.asc -> Data/tutorial/dem.asc, .../directions.asc
  tr_in.txt   Data/tutorial/TIdscelGrid_tutorial.asc -> Data/tutorial/TIdscelGrid_tutorial.txt
              (TopoIndex writes this grid with a .txt name; with the .asc name TRIGRS
              silently skips runoff routing)
The grids are copied into <tmp>/Data/tutorial/ so all other tr_in.txt paths work as shipped.

Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.
Binary lookup: --trg-bin -> $TRIGRS_BIN -> which trg -> server default;
               --tpx-bin -> $TOPOINDEX_BIN -> which tpx -> server default.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_trigrs.py"
PARSE_TOOL = TOOLS / "parse_trigrs_output.py"
_SRC = "/mnt/disk1/Hydrocraft_server/models/TRIGRS/source/repo/source/trigrs_full/src"
_DEF_TRG = (f"{_SRC}/TRIGRS/trg", "/mnt/disk1/Hydrocraft_server/models/TRIGRS/bin/trg")
_DEF_TPX = (f"{_SRC}/TopoIndex/tpx",)
PATH_EDITS = {
    "tpx_in.txt": [("data/dem.asc", "Data/tutorial/dem.asc"),
                   ("data/directions.asc", "Data/tutorial/directions.asc")],
    "tr_in.txt": [("Data/tutorial/TIdscelGrid_tutorial.asc",
                   "Data/tutorial/TIdscelGrid_tutorial.txt")],
}


def find_bin(arg, env, name, defaults):
    for c in (arg, os.environ.get(env), shutil.which(name), *defaults):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return str(Path(c).resolve())
    return None


def edit_paths(fp, edits):
    lines = fp.read_text().splitlines(keepends=True)
    for old, new in edits:
        hits = [i for i, l in enumerate(lines) if l.strip() == old]
        if len(hits) != 1:
            raise RuntimeError(f"{fp.name}: expected one line '{old}', found {len(hits)}")
        lines[hits[0]] = lines[hits[0]].replace(old, new)
    fp.write_text("".join(lines))


def grid(fp):
    """ESRI ASCII grid -> 1-D array of data cells (nodata removed)."""
    with open(fp) as f:
        hdr = [f.readline().split() for _ in range(6)]
    nod = float(hdr[5][1])
    d = np.loadtxt(fp, skiprows=6)
    return d[d != nod]


def mass_balance(log):
    """Period -> (precip+exfil, infil+runoff, infil, runoff) from TrigrsLog.txt."""
    out = {}
    blocks = re.findall(r"Mass Balance Totals for period\s+(\d+)\s*\n.*?\n\s*(\S+)\s*:\s*(\S+)"
                        r"\s*\n.*?\n\s*(\S+)\s+(\S+)", log)
    for p, a, b, i, r in blocks:
        out[int(p)] = tuple(float(x) for x in (a, b, i, r))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trg-bin")
    ap.add_argument("--tpx-bin")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()
    trg = find_bin(a.trg_bin, "TRIGRS_BIN", "trg", _DEF_TRG)
    tpx = find_bin(a.tpx_bin, "TOPOINDEX_BIN", "tpx", _DEF_TPX)
    if not trg or not tpx:
        miss = " and ".join(n for n, b in (("TRIGRS trg", trg), ("TopoIndex tpx", tpx)) if not b)
        print(f"MISSING DEPENDENCY: {miss} binary not found (use --trg-bin/--tpx-bin or "
              "TRIGRS_BIN/TOPOINDEX_BIN). NOT run.", file=sys.stderr)
        return 3
    print(f"  trg: {trg}\n  tpx: {tpx}")

    run = Path(tempfile.mkdtemp(prefix="trigrs_tutorial_"))
    data = run / "Data" / "tutorial"
    data.mkdir(parents=True)
    for f in (HERE / "inputs" / "data" / "tutorial").iterdir():
        shutil.copy(f, data / f.name)
    for name, edits in PATH_EDITS.items():
        shutil.copy(HERE / "inputs" / name, run / name)
        edit_paths(run / name, edits)

    fails, got = [], {}
    # 1. TopoIndex (direct; see README Known KI gaps)
    cp = subprocess.run([tpx], cwd=run, stdin=subprocess.DEVNULL, capture_output=True,
                        text=True, timeout=300)
    tlog = (run / "TopoIndexLog.txt").read_text() if (run / "TopoIndexLog.txt").exists() else ""
    if cp.returncode != 0 or "TopoIndex finished normally" not in tlog:
        fails.append(f"TopoIndex failed (rc={cp.returncode}): {cp.stdout[-300:]}{cp.stderr[-300:]}")
    else:
        print("  OK TopoIndex finished normally")

    # 2. TRIGRS via the KI run tool, else direct
    if not fails:
        src = Path(trg).parent
        use_tool = (src / "Makefile").is_file() and Path(trg).name == "trg" \
            and shutil.which("gfortran") and RUN_TOOL.is_file()
        if use_tool:
            cmd = [sys.executable, str(RUN_TOOL), "--source_dir", str(src), "--work_dir",
                   str(run), "--mode", "serial", "--skip_compile", "--skip_topoindex"]
            print("  running TRIGRS through KI tool run_trigrs.py")
        else:
            cmd = [trg]
            print("  running TRIGRS binary directly (KI tool needs trg inside a src/TRIGRS "
                  "dir with Makefile and gfortran on PATH)")
        cp = subprocess.run(cmd, cwd=run, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=900)
        log = (run / "TrigrsLog.txt").read_text() if (run / "TrigrsLog.txt").exists() else ""
        if cp.returncode != 0 or "TRIGRS finished normally" not in log:
            fails.append(f"TRIGRS failed (rc={cp.returncode}): {cp.stdout[-400:]}{cp.stderr[-300:]}")
        else:
            print("  OK TRIGRS finished normally (rc=0)")
        if "Runoff-routing computations" not in log:
            fails.append("runoff routing was skipped (routing files not read)")
        else:
            print("  OK runoff routing ran")

    if not fails:
        # KI parse tool for FS + water-table depth
        sj = run / "summary.json"
        cp = subprocess.run([sys.executable, str(PARSE_TOOL), "--output_dir", str(data),
                             "--suffix", "tutorial", "--work_dir", str(run),
                             "--result_csv", str(run / "results.csv"),
                             "--summary_json", str(sj)],
                            capture_output=True, text=True, timeout=300)
        if cp.returncode != 0 or not sj.exists():
            fails.append(f"parse_trigrs_output.py failed: {cp.stderr[-400:]}")
        else:
            s = json.loads(sj.read_text())
            for k in ("1", "2"):
                st = s["fs_min"][k]["stats"]
                got[f"fs_min_t{k}"] = st["min_fs"]
                got[f"fs_mean_t{k}"] = st["mean_fs"]
                got[f"n_cells_fs_lt1_t{k}"] = st["n_unstable"]
                got[f"water_depth_mean_t{k}"] = s["water_depth"][k]["stats"]["mean"]
            got["n_cells_fs_grid"] = s["fs_min"]["2"]["stats"]["n_cells"]
        # direct reads
        sz = (data / "TIgrid_size.txt").read_text().split()
        got["topoindex_data_cells"] = int(sz[4])
        got["topoindex_downslope_cells"] = int(sz[7])
        got["runoff_sum_per2"] = float(grid(data / "TRrunoffPer2tutorial.asc").sum())
        got["infil_mean_per2"] = float(grid(data / "TRinfilratPer2tutorial.asc").mean())
        got["p_at_fs_min_max_t2"] = float(grid(data / "TRp_at_fs_min_tutorial_2.asc").max())
        lst = (data / "TRlist_z_p_fs_tutorial.txt").read_text()
        got["n_profiles_list"] = len(re.findall(r"^cell\s", lst, re.M))
        mb = mass_balance(log)
        if 2 in mb:
            pe, ir, inf, ro = mb[2]
            got["mb_infiltration_per2"] = inf
            got["mb_runoff_per2"] = ro
            got["mb_rel_closure_per2"] = abs(pe - ir) / pe
        for c in EXP["numeric_checks"]:
            if c["name"] not in got:
                fails.append(f"{c['name']}: not computed")
                continue
            v = got[c["name"]]
            if abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v:.8g} vs {c['expected']}±{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.8g}")

    if a.keep:
        print(f"  kept run dir: {run}")
    else:
        shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: TRIGRS USGS tutorial reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
