#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      run_mizuroute
Stage:        s8_routing
Description:  Write mizuRoute's control file + param.nml into --output_dir,
              execute the mizuroute.exe binary, and extract the routed discharge
              time series at the outlet segment.

The control file is HAND-BUILT, not rendered from route/settings/SAMPLE.control.
SAMPLE.control carries lake (<is_lake_sim>), water-management (<fname_wm> ...)
and runoff-remap (<is_remap> T, <fname_remap> ...) directives that MUST be absent
for this workflow; emitting only the keys we need is safer than deleting keys
from the sample. SAMPLE.control is the provenance reference for key spelling.

route_opt is HARD-CODED to 1 (IRF) and is NOT exposed as a flag. IRF's unit
hydrograph is driven solely by reach Length plus velo/diff from param.nml.
Every other scheme (KWT/KW/MC/DW) consumes channel Slope, which
build_river_network.py can only write as a nominal placeholder because
HydroBASINS carries no slope field. Exposing them would silently route on a
fabricated slope.

param.nml is copied VERBATIM from route/ancillary_data/param.nml.default with
only &IRF_UH velo and diff substituted, and is written to --output_dir.

Exit codes: 0=success, 1=input error, 2=mizuRoute failure, 3=output error
"""
import sys
import os
import re
import csv
import json
import glob
import logging
import argparse
import subprocess

import numpy as np
from netCDF4 import Dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MIZUROUTE_EXE = "/mnt/disk1/Hydrocraft_server/model/mizuRoute/mizuRoute-main/route/bin/mizuroute.exe"
PARAM_NML_DEFAULT = "/mnt/disk1/Hydrocraft_server/model/mizuRoute/mizuRoute-main/route/ancillary_data/param.nml.default"

# mizuRoute aborts via shr_mpi_abort ("FATAL ERROR") or a bare Fortran STOP.
# Anchor on word boundaries so STOPWATCH / STOPPING_CRITERION do not false-positive.
FATAL_RE = re.compile(r"FATAL ERROR", re.IGNORECASE)
STOP_RE = re.compile(r"(^|\s)STOP(\s|$)")

CASE_NAME = "summa_route"


def parse_args():
    p = argparse.ArgumentParser(description="Run mizuRoute IRF routing on SUMMA runoff")
    p.add_argument("--ntopo_nc", required=True)
    p.add_argument("--runoff_nc", required=True)
    p.add_argument("--output_dir", required=True)
    p.add_argument("--sim_start", required=True, help="yyyy-mm-dd")
    p.add_argument("--sim_end", required=True, help="yyyy-mm-dd")
    p.add_argument("--outlet_seg_id", required=True, type=int, help="compact seg_id of the gauge reach")
    p.add_argument("--dt", type=int, default=86400, help="runoff/simulation time step [s]")
    p.add_argument("--velo", type=float, default=1.5, help="&IRF_UH velo [m/s]")
    p.add_argument("--diff", type=float, default=5000.0, help="&IRF_UH diff [m2/s]")
    return p.parse_args()


def write_param_nml(dest, velo, diff):
    """Copy param.nml.default verbatim, substituting ONLY &IRF_UH velo/diff."""
    with open(PARAM_NML_DEFAULT) as f:
        txt = f.read()
    txt = re.sub(r"(velo\s*=\s*)[-0-9.eE+]+", rf"\g<1>{velo}", txt, count=1)
    txt = re.sub(r"(diff\s*=\s*)[-0-9.eE+]+", rf"\g<1>{diff}", txt, count=1)
    with open(dest, "w") as f:
        f.write(txt)
    return dest


def write_control(dest, *, ancil_dir, input_dir, output_dir, ntopo_name,
                  runoff_name, param_nml, sim_start, sim_end, dt):
    """Emit the control file.

    HARD PARSER CONTRACT (read_control.f90:100-103): every non-comment line is
    scanned for '<', '>' AND '!' --
        iend_data = index(cLines(iLine),'!'); if(iend_data==0) err=20
    A directive line WITHOUT a trailing '!' aborts with
    "problem disentangling cLines(iLine)". The '!' is the value terminator, not
    decoration. Each entry below is therefore (key, value, mandatory-comment).
    """
    entries = [
        ("case_name",         CASE_NAME,               "name of simulation"),
        ("sim_start",         f"{sim_start} 00:00:00", "simulation start"),
        ("sim_end",           f"{sim_end} 00:00:00",   "simulation end"),
        ("route_opt",         "1",                     "1 = IRF only (see module docstring)"),
        ("doesBasinRoute",    "1",                     "gamma hillslope UH (&HSLOPE)"),
        ("dt_qsim",           str(dt),                 "simulation time step [s]"),
        ("is_lake_sim",       "F",                     "no lakes"),
        ("is_flux_wm",        "F",                     "no water management"),
        ("is_vol_wm",         "F",                     "no target volume"),
        ("ancil_dir",         ancil_dir,               "holds the topology netCDF"),
        ("input_dir",         input_dir,               "holds the runoff netCDF"),
        ("output_dir",        output_dir,              "history files land here"),
        ("fname_ntopOld",     ntopo_name,              "river network"),
        ("dname_sseg",        "seg",                   "segment dimension"),
        ("dname_nhru",        "hru",                   "hru dimension"),
        ("fname_qsim",        runoff_name,             "runoff netCDF (read directly, not a file list)"),
        ("vname_qsim",        "runoff",                "runoff variable"),
        ("vname_time",        "time",                  "time variable"),
        ("vname_hruid",       "hru_id",                "runoff hru id variable"),
        ("dname_time",        "time",                  "time dimension"),
        ("dname_hruid",       "hru",                   "runoff hru dimension"),
        ("units_qsim",        "m/s",                   "native m/s; read_control.f90:456"),
        ("dt_ro",             str(dt),                 "runoff time step [s]"),
        ("is_remap",          "F",                     "runoff hrus == network hrus 1:1"),
        ("hydGeometryOption", "1",                     "compute"),
        ("topoNetworkOption", "1",                     "compute"),
        ("computeReachList",  "1",                     "compute"),
        ("param_nml",         param_nml,               "bare filename; resolved against input_dir"),
        ("varname_area",      "Basin_Area",            "hru area"),
        ("varname_length",    "Length",                "segment length"),
        ("varname_slope",     "Slope",                 "segment slope (nominal; unused by IRF)"),
        ("varname_HRUid",     "hruid",                 "hru id"),
        ("varname_hruSegId",  "seg_hru_id",            "segment below each hru"),
        ("varname_segId",     "seg_id",                "segment id"),
        ("varname_downSegId", "tosegment",             "downstream segment id"),
        ("newFileFrequency",  "single",                "one history file"),
        ("outputFrequency",   "1",                     "every simulation step"),
        ("basRunoff",         "F",                     "not needed"),
        ("instRunoff",        "F",                     "not needed"),
        ("dlayRunoff",        "F",                     "not needed"),
        ("sumUpstreamRunoff", "F",                     "not needed"),
        ("IRFroutedRunoff",   "T",                     "the routed discharge we score"),
        ("debug",             "F",                     "quiet"),
    ]
    lines = [
        "! mizuRoute control file -- hand-built by run_mizuroute.py",
        "! key spelling follows route/settings/SAMPLE.control",
        "! every directive line MUST end in a '!' comment (read_control.f90:102)",
    ]
    for key, val, comment in entries:
        lines.append(f"<{key}>".ljust(24) + f"{val}".ljust(28) + f"! {comment}")
    with open(dest, "w") as f:
        f.write("\n".join(lines) + "\n")
    return dest


def main():
    args = parse_args()
    for pth in (args.ntopo_nc, args.runoff_nc, MIZUROUTE_EXE, PARAM_NML_DEFAULT):
        if not os.path.exists(pth):
            logger.error(f"input not found: {pth}")
            sys.exit(1)

    out_dir = os.path.abspath(args.output_dir)
    os.makedirs(out_dir, exist_ok=True)

    # PATH RESOLUTION CONTRACT (init_model_data.f90:165 and :695):
    #   param.nml  is opened as  trim(input_dir)//trim(param_nml)
    #   ntopo      is opened as  trim(ancil_dir)//trim(fname_ntopOld)
    # So <param_nml> must be a BARE FILENAME living in <input_dir> -- an absolute
    # path there gets concatenated onto input_dir and the open fails. We therefore
    # set <input_dir> = --output_dir and stage a symlink of the runoff NetCDF into
    # it, so that EVERY file this tool writes (param.nml, mizuroute.control,
    # mizuroute.log, history, routed_discharge.csv) lands in --output_dir.
    write_param_nml(os.path.join(out_dir, "param.nml"), args.velo, args.diff)

    runoff_link = os.path.join(out_dir, os.path.basename(args.runoff_nc))
    if os.path.abspath(args.runoff_nc) != runoff_link:
        if os.path.islink(runoff_link) or os.path.exists(runoff_link):
            os.remove(runoff_link)
        os.symlink(os.path.abspath(args.runoff_nc), runoff_link)

    control = write_control(
        os.path.join(out_dir, "mizuroute.control"),
        ancil_dir=os.path.dirname(os.path.abspath(args.ntopo_nc)) + "/",
        input_dir=out_dir + "/",
        output_dir=out_dir + "/",
        ntopo_name=os.path.basename(args.ntopo_nc),
        runoff_name=os.path.basename(args.runoff_nc),
        param_nml="param.nml",          # bare filename, resolved against input_dir
        sim_start=args.sim_start, sim_end=args.sim_end, dt=args.dt,
    )

    for stale in glob.glob(os.path.join(out_dir, f"{CASE_NAME}.h*.nc")):
        os.remove(stale)

    logger.info(f"running {MIZUROUTE_EXE} {control}")
    proc = subprocess.run([MIZUROUTE_EXE, control], capture_output=True, text=True, cwd=out_dir)
    log = (proc.stdout or "") + (proc.stderr or "")
    with open(os.path.join(out_dir, "mizuroute.log"), "w") as f:
        f.write(log)

    if proc.returncode != 0 or FATAL_RE.search(log) or STOP_RE.search(log):
        logger.error(f"mizuRoute failed (rc={proc.returncode})")
        logger.error(log[-3000:])
        sys.exit(2)

    hist = sorted(glob.glob(os.path.join(out_dir, f"{CASE_NAME}.h*.nc")))
    if not hist:
        logger.error(f"mizuRoute produced no history file in {out_dir}")
        sys.exit(3)

    times, flows = [], []
    for hf in hist:
        with Dataset(hf) as ds:
            if "IRFroutedRunoff" not in ds.variables:
                raise RuntimeError(f"IRFroutedRunoff absent from {hf}")
            reach = np.asarray(ds["reachID"][:]).astype(np.int64)
            where = np.where(reach == args.outlet_seg_id)[0]
            if where.size != 1:
                raise RuntimeError(f"outlet_seg_id {args.outlet_seg_id} not found exactly once in {hf}")
            j = int(where[0])
            tv = ds["time"]
            import cftime
            tt = cftime.num2date(np.asarray(tv[:]), tv.units,
                                 getattr(tv, "calendar", "standard"))
            times.extend([str(t)[:10] for t in tt])
            flows.extend(np.asarray(ds["IRFroutedRunoff"][:, j], dtype=np.float64).tolist())

    csv_path = os.path.join(out_dir, "routed_discharge.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "Q_m3s"])
        for d, q in zip(times, flows):
            w.writerow([d, f"{q:.6f}"])

    print(json.dumps({
        "status": "success",
        "n_steps": len(flows),
        "outlet_seg_id": args.outlet_seg_id,
        "mean_Q_m3s": float(np.mean(flows)) if flows else None,
        "control": control,
        "param_nml": os.path.join(out_dir, "param.nml"),
        "history_files": hist,
        "routed_discharge_csv": csv_path,
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"run_mizuroute failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(3)
