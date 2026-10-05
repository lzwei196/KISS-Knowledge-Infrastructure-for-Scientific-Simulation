# HEC_RAS — foundation test case: "mixed_flow_regime_channel"

Authentic foundation case: HEC's own **Mixed Flow Regime Channel** steady example, from the
official HEC-RAS example projects download (`Example_Projects_6_6.zip`, folder
`1D Steady Flow Hydraulics/Mixed Flow Regime Channel`). One steep-then-mild reach with 19
cross sections and two flows (PF 1 = 500 cfs, PF 2 = 1000 cfs). The water runs fast
(supercritical) at the top, then a hydraulic jump turns it slow (subcritical). The flow
file holds 19 "Observed WS" values from HEC for PF 1.

`inputs/` are the unmodified official files. They are byte-identical to the official zip
and to the KI's bundled template `knowledge_infrastructure/examples/MixedFlowSteady/`
(sha256 in `manifest.json`).

| | |
|---|---|
| Engine | HEC-RAS 6.7 Beta 5, `RasSteady.exe` (x64) under WINE 9.0 |
| Source | USACE HEC, `Example_Projects_6_6.zip` from github.com/HydrologicEngineeringCenter/hec-downloads (release 1.0.33) |
| Licence | HEC-RAS is free US Government (USACE) software, closed source; HEC hands out the example projects freely |
| KI | `HEC_RAS` (run tool `tools/run_hecras.py`) |

## Run
```
python run_reference.py    # finds RasSteady.exe (or $RASSTEADY_BIN, --rassteady-bin); 0=PASS 2=FAIL 3=missing
```
It copies `inputs/` to a fresh temp dir and runs the real `RasSteady.exe MIXED.r01` under
WINE through the KI's own `tools/run_hecras.py` (that tool seeds `MIXED.p01.tmp.hdf` from
`MIXED.g01.hdf`, its normal step). The results HDF is read with the KI's
`tools/parse_output_hecras.py`, and PF 1 is compared with the official observed water
surface by `tools/validate_hecras.py`. Needs `wine`, `h5py`, `numpy`. Takes about 3 seconds.

## Expected (recorded 2026-10-05)
The official example ships no computed results (no `.O01` or `.p01.hdf`), so solver values
come from our own run. Two clean runs gave the same `MIXED.O01` bytes and the same values in
all 71 numeric HDF datasets (deterministic).
- finished normally: tool exit 0, solver return code 0 and the line `Finished Steady Flow Simulation`
- 2 profiles x 19 cross sections; flow 500 cfs (PF 1) and 1000 cfs (PF 2) at every section
- PF 1 water surface: top 71.8657 ft, bottom 66.0005 ft, just below the jump 69.5186 ft
- PF 2 water surface: top 72.9266 ft, bottom 69.0194 ft
- supercritical sections: PF 1 = 6, PF 2 = 5; PF 1 jump between XS 4 and XS 5 (RS 0.4925 to 0.4735),
  the same place as the jump in the official observed values
- against HEC's 19 official observed WS (PF 1): RMSE 0.0963 ft, NSE 0.9965, largest gap 0.277 ft

Water-surface tolerance is 0.005 ft to allow for small float differences on another WINE or CPU.

After `Finished Steady Flow Simulation`, RasSteady.exe prints an `HDF5-DIAG ... H5Gopen2(): not a
location` message. The return code is 0 and all results are written, so this is noise.

## KI gaps (status 2026-10-06)

No KI tool fix for HEC_RAS has landed in this checkout since the case was made (last HEC_RAS commit `189d37e`), so every item below is still open.

- **Still open:** In this repo, `tools/_hecras_env.py` holds an install-time placeholder (`KISSPATH_HOME`)
  in the HEC-RAS install path, and neither it nor `run_hecras.py` takes the binary path as a
  flag or env var. So `run_reference.py` sets `_hecras_env.BINARIES["steady"]` and
  `WINEPREFIX` to the binary it found, then calls `run_hecras.main()` unchanged.
- **Still open:** The repo copy of the KI has no `examples/` folder, so `run_hecras.py` with no
  `--project` (and `prepare_steady_run.py`, which copy the bundled template) cannot work from
  the repo alone; this case passes `--project` with its own copy of the official files.
- **Note (not a gap):** A missing engine or `wine` is reported (exit 3), never faked.
