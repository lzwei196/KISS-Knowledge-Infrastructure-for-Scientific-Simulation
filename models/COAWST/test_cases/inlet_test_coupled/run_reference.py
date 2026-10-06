#!/usr/bin/env python3
"""Run the official COAWST test application Inlet_test (Coupled: ROMS + SWAN via MCT) and check expected.json.

Foundation case for the COAWST KI. COAWST programs are built per application, so this case needs a
coawstM built for INLET_TEST (build_coawst.sh default; header Projects/Inlet_test/Coupled/inlet_test.h).
The run goes through the KI's own tools/run_coawst.py with 2 MPI ranks (1 ocean + 1 wave, as set in
coupling_inlet_test.in). It takes about 9 minutes. COAWST ships no reference output for this case, so
expected.json holds values from our own runs (two runs were identical in every output variable).
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

coawstM lookup: --coawst-bin -> $COAWST_INLET_TEST_BIN -> server default. A coawstM found on PATH is
NOT used: coawstM is built for one application, and a build for another one (e.g. SANDY) cannot run
this case.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_coawst.py"
_DEF = "/home/server/engine_builds_20261006/coawst/COAWST/coawstM"
CPL = "Projects/Inlet_test/Coupled/coupling_inlet_test.in"


def summarise(run, log):
    import netCDF4
    o = {}
    with netCDF4.Dataset(run / "ocean_his_coupled.nc") as d:
        t = d["ocean_time"][:]
        o["his_records"] = len(t)
        o["his_last_time_s"] = float(t[-1])
        wet = d["mask_rho"][:] > 0.5
        z = np.ma.filled(d["zeta"][-1], np.nan)[wet]
        o["zeta_max_end_m"] = np.max(z)
        o["zeta_min_end_m"] = np.min(z)
        o["ubar_absmax_end_ms"] = float(np.max(np.abs(d["ubar"][-1])))
        o["vbar_absmax_end_ms"] = float(np.max(np.abs(d["vbar"][-1])))
        hw = np.ma.filled(d["Hwave"][-1], np.nan)[wet]
        o["Hwave_max_end_m"] = np.max(hw)
        o["Hwave_mean_end_m"] = np.mean(hw)
        bath = d["bath"][:]
        o["bath_change_absmax_m"] = float(np.max(np.abs(bath[-1] - bath[0])))
        o["sand_01_max_end_kgm3"] = float(np.max(d["sand_01"][-1]))
        o["nonfinite_values_end"] = float(sum(int(np.sum(~np.isfinite(a))) for a in (z, hw)))
    with netCDF4.Dataset(run / "ocean_sta.nc") as d:
        o["station_records"] = len(d["ocean_time"][:])
    with netCDF4.Dataset(run / "hsig.nc") as d:
        hs = np.ma.masked_invalid(d["hs"][-1])
        o["swan_hsig_nc_max_end_m"] = float(hs.max())
    rows = [l.split() for l in (run / "point1.table").read_text().splitlines()
            if l.strip() and not l.lstrip().startswith("%")]
    o["swan_point1_records"] = len(rows)
    o["swan_point1_hsig_end_m"] = float(rows[-1][0])
    o["coupling_exchanges"] = len(re.findall(r"ROMS grid\s+1 recv data from SWAN grid\s+1", log))
    m = re.findall(r"^\s*(\d+)\s+0001-01-01 12:00:00\.00\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)", log, re.M)
    o["roms_last_step"] = int(m[-1][0]) if m else -1
    o["roms_kinetic_energy_end"] = float(m[-1][1]) if m else float("nan")
    return {k: float(v) for k, v in o.items()}


def _descendants(pid):
    """All descendant PIDs of pid (from /proc), deepest first."""
    kids = {}
    for d in Path("/proc").iterdir():
        if d.name.isdigit():
            try:
                ppid = int((d / "stat").read_text().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
            kids.setdefault(ppid, []).append(int(d.name))
    out, todo = [], [pid]
    while todo:
        for c in kids.get(todo.pop(), []):
            out.append(c)
            todo.append(c)
    return out[::-1]


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _stop_tree(proc):
    """Stop the tool and every process it started (mpirun, model ranks), each by its own PID."""
    import signal, time
    pids = _descendants(proc.pid) + [proc.pid]
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for p in pids:
            if _alive(p):
                try:
                    os.kill(p, sig)
                except ProcessLookupError:
                    pass
        t0 = time.time()
        while time.time() - t0 < 10 and any(_alive(p) for p in pids):
            time.sleep(0.5)
    proc.poll()
    left = [p for p in pids if _alive(p)]
    return left


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coawst-bin")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()
    if a.coawst_bin:
        b, src = a.coawst_bin, "--coawst-bin"
    elif os.environ.get("COAWST_INLET_TEST_BIN"):
        b, src = os.environ["COAWST_INLET_TEST_BIN"], "$COAWST_INLET_TEST_BIN"
    else:
        b, src = _DEF, "server default"
    b = os.path.abspath(b)
    if not (Path(b).is_file() and os.access(b, os.X_OK)):
        print(f"MISSING DEPENDENCY: coawstM for INLET_TEST ({src}) is not an executable file: {b}. NOT run.",
              file=sys.stderr)
        return 3
    if not shutil.which("mpirun"):
        print("MISSING DEPENDENCY: mpirun not found. NOT run.", file=sys.stderr)
        return 3
    try:
        import netCDF4  # noqa: F401
    except ImportError:
        print("MISSING DEPENDENCY: python netCDF4. NOT run.", file=sys.stderr)
        return 3
    if not RUN_TOOL.is_file():
        print(f"MISSING DEPENDENCY: KI tool {RUN_TOOL}. NOT run.", file=sys.stderr)
        return 3
    run = Path(tempfile.mkdtemp(prefix="coawst_inlet_"))
    shutil.copytree(HERE / "inputs", run, dirs_exist_ok=True)
    # The KI tool runs the model in the folder of the config file, but the official files use
    # paths relative to the COAWST root (Projects/Inlet_test/Coupled/...). So a byte-identical
    # copy of the official coupling file is put at the run root and passed by its short
    # relative name (COAWST cuts long file names).
    shutil.copy(run / CPL, run / "coupling_inlet_test.in")
    env = dict(os.environ, OMP_NUM_THREADS="1")
    print(f"  coawstM ({src}): {b}")
    # Watchdog: the tool's own timeout only acts when the model prints a line, so this script
    # stops the tool, mpirun and the model ranks itself (each by explicit PID) after 1110 s,
    # leaving time for cleanup within 20 minutes. The tool's own timeout is switched off
    # ("--timeout 0"): it would kill only mpirun and could leave model ranks that this script can
    # no longer find.
    proc = subprocess.Popen([sys.executable, str(RUN_TOOL), "--binary", b, "--config", "coupling_inlet_test.in",
                             "--nprocs", "2", "--timeout", "0"],
                            cwd=run, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, log = proc.communicate(timeout=1110)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        left = _stop_tree(proc)
        try:
            out, log = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:  # a survivor still holds the pipes
            for fh in (proc.stdout, proc.stderr):
                try:
                    fh.close()
                except OSError:
                    pass
            out, log = "", ""
        rc = -1
        log += f"\nWATCHDOG: run stopped after 1110 s; processes still alive after stop: {left}"
    fails = []
    try:
        res = json.loads(out[out.index("{"):])
    except ValueError:
        res = {}
    # The tool exits 0 even when the model fails, so its JSON 'returncode' is checked too.
    if rc != 0 or res.get("returncode") != 0 or res.get("status") not in ("success", "completed_with_warnings"):
        fails.append(f"run failed: tool rc={rc}, status={res.get('status')}, model rc={res.get('returncode')}: "
                     f"{log[-600:]}")
    elif "ROMS/TOMS: DONE" not in log:
        fails.append("model line 'ROMS/TOMS: DONE' not found")
    else:
        print(f"  ran through KI tools/run_coawst.py in {run} ({res.get('elapsed_seconds')} s)")
        print("  OK finished: model rc=0 and 'ROMS/TOMS: DONE'")
        try:
            got = summarise(run, log)
        except Exception as ex:
            got = {}
            fails.append(f"could not read outputs: {ex}")
        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            if v is None:
                fails.append(f"{c['name']}: not computed")
            elif not abs(v - c["expected"]) <= c["tol"]:
                fails.append(f"{c['name']}: {v:.10g} vs {c['expected']}+-{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.10g}")
    if a.keep:
        print(f"  kept run dir {run}")
    else:
        shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: COAWST Inlet_test (ROMS+SWAN coupled) matches expected.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
