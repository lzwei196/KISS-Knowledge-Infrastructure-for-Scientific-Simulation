#!/usr/bin/env python3
"""Run MOM6's official test case tc1 (low-res 'benchmark', 10x8x8) and check expected.json.

Foundation case for the MOM6 KI. Inputs are the unmodified files of MOM6 .testing/tc1.
Two runs, both through the KI's own tools/run_mom6.py, each in a fresh temp dir:
  1. 1 MPI rank (MOM6 default layout 1,1)      -> values checked against expected.json
  2. 2 MPI ranks with LAYOUT=2,1               -> must give byte-identical ocean.stats and
     chksum_diag. This is MOM6's own "layout" test (.testing/Makefile writes the same
     'LAYOUT=2,1' line into MOM_override of the temp copy). The packaged inputs are not changed.
Output is read with the KI's tools/output_parser.py (parse_ocean_stats); the mass / salt /
temperature columns it does not read are taken straight from ocean.stats.

Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.
Binary lookup: --mom6-bin -> $MOM6_BIN -> `which MOM6` -> server default.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_mom6.py"
_DEF = ("/home/server/knowledge-dissection-toolkit/auto_dissect/_work/MOM6/source/repo/"
        ".testing/build/symmetric/MOM6")
_MPI_DEF = "/home/server/.local/bin"
INPUTS = ("MOM_input", "MOM_override", "input.nml", "diag_table")


def find_bin(arg):
    for c in (arg, os.environ.get("MOM6_BIN"), shutil.which("MOM6"), _DEF):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return os.path.abspath(c)
    return None


def run_case(binary, nprocs, override, env):
    run = Path(tempfile.mkdtemp(prefix=f"mom6_tc1_np{nprocs}_"))
    for f in INPUTS:
        shutil.copy(HERE / "inputs" / f, run / f)
    if override:  # same as .testing/Makefile: echo "<override>" > MOM_override (temp copy only)
        (run / "MOM_override").write_text(override + "\n")
    (run / "INPUT").mkdir()    # tc1 is fully analytic; run_mom6.py requires the dir to exist
    (run / "RESTART").mkdir()  # input.nml restart_output_dir
    cp = subprocess.run([sys.executable, str(RUN_TOOL), "--run-dir", str(run),
                         "--binary", binary, "-n", str(nprocs), "--timeout", "900",
                         "--json-report", str(run / "ki_report.json")],
                        capture_output=True, text=True, timeout=1000, env=env)
    return run, cp


def stats_cols(path):
    """Last data row of ocean.stats -> dict of M, S, T, Me, Se, Te, truncs."""
    rows = [l for l in open(path) if re.match(r"\s*\d+,", l)]
    last = rows[-1]
    out = {"truncs": int(last.split(",")[2])}
    for k in ("M", "S", "T", "Me", "Se", "Te"):
        out[k] = float(re.search(rf",\s*{k}\s+([-+\d.Ee]+)", last).group(1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mom6-bin")
    ap.add_argument("--keep", action="store_true", help="keep temp run dirs")
    a = ap.parse_args()
    binary = find_bin(a.mom6_bin)
    if not binary:
        print("MISSING DEPENDENCY: MOM6 executable not found (set --mom6-bin or $MOM6_BIN). "
              "NOT run.", file=sys.stderr)
        return 3
    env = dict(os.environ)
    if not shutil.which("mpirun"):
        env["PATH"] = _MPI_DEF + os.pathsep + env.get("PATH", "")
    if not shutil.which("mpirun", path=env["PATH"]):
        print("MISSING DEPENDENCY: mpirun (Open MPI) not on PATH, needed for the 2-rank "
              "layout run. NOT run.", file=sys.stderr)
        return 3
    if not RUN_TOOL.is_file():
        print(f"MISSING DEPENDENCY: KI run tool {RUN_TOOL} not found. NOT run.", file=sys.stderr)
        return 3
    sys.path.insert(0, str(TOOLS))
    import output_parser  # KI parse tool

    fails, runs = [], []
    r1, cp1 = run_case(binary, 1, "", env)
    runs.append(r1)
    r2, cp2 = run_case(binary, 2, "LAYOUT=2,1", env)
    runs.append(r2)
    for tag, r, cp in (("1-rank", r1, cp1), ("2-rank LAYOUT=2,1", r2, cp2)):
        ok_end = (r / "exitcode").is_file() and (r / "exitcode").read_text().strip() == "0"
        log = (r / "mom6_run.log").read_text(errors="replace") if (r / "mom6_run.log").is_file() else ""
        ok_end = ok_end and "Total runtime" in log and "Termination" in log
        if cp.returncode != 0 or not ok_end or not (r / "ocean.stats").is_file():
            fails.append(f"{tag} run did not finish normally (KI tool rc={cp.returncode}, "
                         f"exitcode/clock-table ok={ok_end}): {cp.stderr[-600:]}")
        else:
            print(f"  ran {tag}: KI tool rc=0, MOM6 exitcode 0, clock table has Total runtime + Termination")

    if not fails:
        recs = output_parser.parse_ocean_stats(str(r1 / "ocean.stats"))
        cols = stats_cols(r1 / "ocean.stats")
        first, last = recs[0], recs[-1]
        diff = lambda f: sum(1 for x, y in zip(open(r1 / f), open(r2 / f)) if x != y) + \
            abs(sum(1 for _ in open(r1 / f)) - sum(1 for _ in open(r2 / f)))
        got = {
            "n_stats_records": len(recs),
            "final_step": last["step"],
            "final_day": last["day"],
            "initial_energy_per_mass": first["energy"],
            "final_energy_per_mass": last["energy"],
            "final_max_cfl": last["cfl"],
            "final_mean_sea_level": last["sea_level"],
            "final_total_mass": cols["M"],
            "final_mean_salinity": cols["S"],
            "final_mean_temp": cols["T"],
            "final_frac_mass_err": cols["Me"],
            "final_truncations": cols["truncs"],
            "layout_2x1_ocean_stats_lines_differing": diff("ocean.stats"),
            "layout_2x1_chksum_diag_lines_differing": diff("chksum_diag"),
        }
        for c in EXP["numeric_checks"]:
            v = got[c["name"]]
            if abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v!r} vs {c['expected']} +/- {c['tol']}")
            else:
                print(f"  OK {c['name']}: {v!r}")

    if a.keep:
        print("kept run dirs:", *runs)
    else:
        for r in runs:
            shutil.rmtree(r, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: MOM6 tc1 (benchmark) reproduced the expected results; 1-rank and 2-rank "
          "layout runs are identical.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
