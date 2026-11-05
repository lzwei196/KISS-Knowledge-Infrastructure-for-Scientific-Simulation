# Delft3D — foundation test case: "f34_standard"

Authentic foundation case: the official Delft3D-FLOW example **01_standard** (the F34
estuary tutorial) from the Deltares Delft3D source tree, `examples/delft3d4/01_standard`.
Tidal boundary + uniform wind, 25 hours, 5-minute time step, 5 monitoring points (W1–W5).
`inputs/` are the unmodified files (git commit bb39f63b).

| | |
|---|---|
| Engine | Delft3D-FLOW (flow2d3d 6.04.03), `d_hydro` + `libflow2d3d.so` — the engine the KI preflight resolves |
| Source | Deltares/Delft3D `examples/delft3d4/01_standard` |
| Licence | Deltares Delft3D licences (GPL-3.0 / LGPL-2.1 / AGPL-3.0 by component) |
| KI | `Delft3D` |

## Run
```
python run_reference.py    # finds d_hydro (or $D_HYDRO, --d-hydro); 0=PASS 2=FAIL 3=engine missing
# by hand, in a dir with the inputs:  LD_LIBRARY_PATH=<flow2d3d lib dir> d_hydro config_d_hydro.xml
```
The run copy of `f34.mdf` gets one output keyword, `FlNcdf = #maphis#`, so FLOW writes
`trih-f34.nc`. That only switches the output format (the tri-diag file was compared with a
NEFIS-only run: same run). The history file is read with the KI's own
`tools/parse_delft3d_output.py`; water levels (`ZWL`) are checked directly.

## Expected (recorded 2026-10-05; repeat runs give the same values)
- `tri-diag.f34` says `FINISHED    Delft3D-FLOW`
- 301 history records to t = 90000 s, 5 stations
- water level (m) max / min / last: W1 1.2592 / −1.0936 / 1.0823, W5 1.0432 / −0.7081 / 0.8493
  (all 5 stations in `expected.json`, tolerance 0.001 m)

## KI gaps (status 2026-10-06)
- **Fixed in `d591049`:** `tools/run_delft3d.py` has a `--mode d_hydro` for Delft3D-FLOW 4 (the
  server build) and counts a run as good only when this run's `FINISHED` line is there. Before:
  it only started runs through DIMR (`dimr` / `run_dimr.sh`), but the server build has only
  `d_hydro` + `libflow2d3d.so`, so it could not drive this engine. This case runs `d_hydro`
  itself; the workaround in `run_reference.py` is kept so the case also runs with older tool
  versions.
- **Fixed in `d591049`:** `tools/parse_delft3d_output.py` now reads the Delft3D-FLOW variables
  `ZWL`, `ZCURU`, `ZCURV` and `ZTAU*`. Before: it did not pick up the water level `ZWL` from
  `trih-*.nc` (the CSV had only the time column), so `ZWL` is checked directly here; the
  workaround in `run_reference.py` is kept so the case also runs with older tool versions.
