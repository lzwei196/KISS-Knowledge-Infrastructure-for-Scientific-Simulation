#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      summa_to_mizuroute
Stage:        s8_routing
Description:  Convert a SUMMA output NetCDF into the 1-D-vector runoff NetCDF
              that mizuRoute reads as <fname_qsim>.

UNITS -- there is NO conversion and there is NO scale flag.
  SUMMA scalarTotalRunoff is m/s (parse_summa_output.py:12-13,25 -- "Do NOT
  divide by 1000"). mizuRoute's read_control.f90:456-458 accepts
  <units_qsim> = 'm/s' natively (`case('m'); length_conv = 1._dp`).
  This tool therefore copies the values through unchanged and stamps units='m/s'.

The SUMMA hruId set must equal the ntopo hruid set EXACTLY. A mismatch raises
and lists the symmetric difference; there is no lumped-broadcast fallback.

Exit codes: 0=success, 1=input error, 2=processing error
"""
import sys
import os
import json
import logging
import argparse

import numpy as np
from netCDF4 import Dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RUNOFF_VAR = "scalarTotalRunoff"   # m/s, HRU dimension


def parse_args():
    p = argparse.ArgumentParser(description="SUMMA output -> mizuRoute runoff NetCDF")
    p.add_argument("--summa_output_nc", required=True)
    p.add_argument("--ntopo_nc", required=True)
    p.add_argument("--output_nc", required=True)
    return p.parse_args()


def main():
    args = parse_args()
    for pth in (args.summa_output_nc, args.ntopo_nc):
        if not os.path.exists(pth):
            logger.error(f"input not found: {pth}")
            sys.exit(1)

    with Dataset(args.ntopo_nc) as nt:
        ntopo_hru = np.asarray(nt["hruid"][:]).astype(np.int64)

    with Dataset(args.summa_output_nc) as sm:
        if RUNOFF_VAR not in sm.variables:
            raise RuntimeError(f"{RUNOFF_VAR} absent from {args.summa_output_nc}; "
                               f"add it to the SUMMA outputControl file")
        if "hruId" not in sm.variables:
            raise RuntimeError(f"hruId absent from {args.summa_output_nc}")
        summa_hru = np.asarray(sm["hruId"][:]).astype(np.int64)

        only_summa = sorted(set(summa_hru.tolist()) - set(ntopo_hru.tolist()))
        only_ntopo = sorted(set(ntopo_hru.tolist()) - set(summa_hru.tolist()))
        if only_summa or only_ntopo:
            raise RuntimeError(
                "SUMMA hruId set != ntopo hruid set. "
                f"only_in_summa={only_summa[:20]} only_in_ntopo={only_ntopo[:20]}"
            )

        rv = sm[RUNOFF_VAR]
        dims = rv.dimensions
        data = np.asarray(rv[:], dtype=np.float64)
        if dims[0] != "time":                 # (hru,time) -> (time,hru)
            data = data.T
        tvar = sm["time"]
        tvals = np.asarray(tvar[:], dtype=np.float64)
        tunits = tvar.units
        tcal = getattr(tvar, "calendar", "standard")

    # reorder SUMMA columns into ntopo hruid order
    order = {h: i for i, h in enumerate(summa_hru.tolist())}
    idx = np.array([order[h] for h in ntopo_hru.tolist()], dtype=int)
    data = data[:, idx]

    if not np.all(np.isfinite(data)):
        raise RuntimeError(f"{RUNOFF_VAR} contains non-finite values")
    if np.any(data < 0.0):
        raise RuntimeError(f"{RUNOFF_VAR} contains negative runoff")

    os.makedirs(os.path.dirname(os.path.abspath(args.output_nc)), exist_ok=True)
    with Dataset(args.output_nc, "w", format="NETCDF4") as out:
        out.createDimension("time", None)
        out.createDimension("hru", ntopo_hru.size)
        t = out.createVariable("time", "f8", ("time",))
        t[:] = tvals
        t.units = tunits
        t.calendar = tcal
        h = out.createVariable("hru_id", "i4", ("hru",))
        h[:] = ntopo_hru.astype(np.int32)
        q = out.createVariable("runoff", "f8", ("time", "hru"))
        q[:, :] = data
        q.units = "m/s"          # consumed verbatim by <units_qsim>
        q.long_name = "SUMMA scalarTotalRunoff, unconverted"
        out.history = f"summa_to_mizuroute.py from {args.summa_output_nc}"

    print(json.dumps({
        "status": "success",
        "n_time": int(data.shape[0]),
        "n_hru": int(data.shape[1]),
        "units": "m/s",
        "mean_runoff_m_s": float(data.mean()),
        "output": args.output_nc,
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"summa_to_mizuroute failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
