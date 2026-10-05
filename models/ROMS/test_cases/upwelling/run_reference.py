#!/usr/bin/env python3
"""Run the official ROMS UPWELLING test case and check expected.json.

Foundation case for the ROMS KI. The run goes through the KI's own tools/run_roms.py
(serial romsS, roms.in fed on stdin). The tool's command line keeps only the last 500
characters of the model log, so this script imports the tool and calls its run_roms()
function to get the full log (ROMS prints its energy / volume table there), then uses the
tool's own log scan and output-file check.

Exit 0 PASS, 2 checks failed, 3 binary/dependency missing.

romsS lookup: --roms-bin -> $ROMS_BIN -> which romsS -> server default (UPWELLING build).
The binary MUST be built with ROMS_APP=UPWELLING (ROMS compiles the case header in).
"""
import argparse, importlib.util, json, os, re, shutil, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_roms.py"
_DEF = ("/home/server/knowledge-dissection-toolkit/auto_dissect/_work/ROMS/source/repo/"
        "build_upwelling/romsS")

ROW = re.compile(r"^\s+(\d+)\s+\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d\d\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")
CFL = re.compile(r"^\s+\(\d+,\d+,\d+\)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")


def load_tool():
    spec = importlib.util.spec_from_file_location("ki_run_roms", RUN_TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def summarise_log(log):
    rows, speed = {}, {}
    last = None
    for line in log.splitlines():
        m = ROW.match(line)
        if m:
            last = int(m.group(1))
            rows[last] = [float(m.group(i)) for i in range(2, 6)]
            continue
        c = CFL.match(line)
        if c and last is not None and last not in speed:
            speed[last] = float(c.group(4))
    o = {"n_diag_rows": len(rows), "last_step": max(rows) if rows else -1}
    if rows:
        ke, pe, te, vol = rows[max(rows)]
        o.update(final_kinetic_energy=ke, final_potential_energy=pe, final_total_energy=te,
                 final_net_volume=vol, initial_total_energy=rows[min(rows)][2],
                 max_kinetic_energy=max(r[0] for r in rows.values()),
                 net_volume_rel_change=abs(vol - rows[min(rows)][3]) / rows[min(rows)][3])
    if speed:
        o["final_max_speed"] = speed[max(speed)]
    m = re.search(r"number of time records written in HISTORY file =\s*(\d+)", log)
    if m:
        o["his_records"] = int(m.group(1))
    return o


def summarise_his(path):
    import netCDF4 as nc
    o = {}
    with nc.Dataset(path) as d:
        o["his_ocean_time_end_s"] = float(d["ocean_time"][-1])
        for v in ("temp", "zeta", "u"):
            x = d[v][-1]
            o[f"his_final_{v}_min"] = float(x.min())
            o[f"his_final_{v}_max"] = float(x.max())
        o["his_final_temp_mean"] = float(d["temp"][-1].mean())
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roms-bin")
    a = ap.parse_args()
    b = next((c for c in (a.roms_bin, os.environ.get("ROMS_BIN"), shutil.which("romsS"), _DEF)
              if c and Path(c).is_file()), None)
    if not b:
        print("MISSING DEPENDENCY: romsS (UPWELLING build) not found (set ROMS_BIN). NOT run.",
              file=sys.stderr)
        return 3
    try:
        import netCDF4  # noqa: F401
    except ImportError:
        print("MISSING DEPENDENCY: python netCDF4 not installed. NOT run.", file=sys.stderr)
        return 3
    if not RUN_TOOL.is_file():
        print(f"MISSING DEPENDENCY: KI tool {RUN_TOOL} not found. NOT run.", file=sys.stderr)
        return 3
    tool = load_tool()

    run = Path(tempfile.mkdtemp(prefix="roms_upwelling_"))
    fails = []
    try:
        cfg = run / "roms_upwelling.in"
        shutil.copy(HERE / "inputs" / "roms_upwelling.in", cfg)
        (run / "ROMS" / "External").mkdir(parents=True)
        shutil.copy(HERE / "inputs" / "ROMS" / "External" / "varinfo.yaml",
                    run / "ROMS" / "External" / "varinfo.yaml")
        params = tool.parse_roms_in(str(cfg))
        res = tool.run_roms(b, str(cfg), nprocs=1, timeout=1200, workdir=str(run))
        log = res["stdout"] + res["stderr"]
        print(f"  ran romsS through KI tools/run_roms.py run_roms() "
              f"({res['elapsed_seconds']:.1f} s, rc={res['returncode']})")
        errs, _ = tool.scan_log_for_errors(res["stdout"], res["stderr"])
        created, _ = tool.validate_output_files(params, str(run))
        if res["returncode"] != 0:
            fails.append(f"romsS return code {res['returncode']}: {log[-400:]}")
        if "ROMS: DONE" not in log:
            fails.append("success line 'ROMS: DONE' not found in log")
        else:
            print("  OK finished normally: rc=0 and 'ROMS: DONE' in log")
        if not re.search(r"Header file\s*:\s*upwelling\.h", log):
            fails.append("binary is not the UPWELLING build (log 'Header file' is not upwelling.h)")
        if errs:
            fails.append(f"KI log scan found errors: {errs}")
        if not any(c.startswith("HISNAME") for c in created):
            fails.append("history file roms_his.nc not created")
        got = summarise_log(log)
        try:
            got.update(summarise_his(run / "roms_his.nc"))
        except Exception as ex:
            fails.append(f"could not read roms_his.nc: {ex}")
        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            if v is None:
                fails.append(f"{c['name']}: not computed")
            elif abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v:.10g} vs {c['expected']} +- {c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.10g}")
    finally:
        shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: ROMS UPWELLING case matches the recorded reference values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
