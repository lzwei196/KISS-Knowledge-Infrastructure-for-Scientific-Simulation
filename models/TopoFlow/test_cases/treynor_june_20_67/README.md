# TopoFlow — foundation test case: "treynor_june_20_67"

Official case: the **Treynor, Iowa, 20 June 1967 storm** example that ships with TopoFlow
(`topoflow/examples/Treynor_Iowa_30m/__No_Infil_June_20_67_Rain`, by S.D. Peckham).
Rain falls on a 0.396 km2 watershed (30 m grid, 44 x 29 cells) and is routed to the outlet
with kinematic-wave channels. No infiltration, snow, evaporation or groundwater. The run stops
by the official rule: when outlet flow drops to 5% of its peak.

`inputs/` holds the unmodified official files, taken with `git show HEAD:<path>` (the working
copy on the server had local edits). Each file was checked against the upstream git blob hash.
Only the files the run reads are kept: all files of the case folder (minus `calibrate.cfg` and
`June_20_67_rain_rates_ORIG.txt`) and 9 grids + `__NOTES.txt` from `__topo/`.

| | |
|---|---|
| Engine | TopoFlow 3.71 (2023-09-25, as printed by the model), python package `topoflow` |
| Source | github.com/peckhams/topoflow36, commit a1c07d0a72185cbd0baeff1ef77feadad09c3f88 (2025-10-09) |
| Licence | MIT (Copyright (c) 2019 Scott D. Peckham) |
| Engine python | `/home/server/knowledge-dissection-toolkit/auto_dissect/_work/TopoFlow/venv/bin/python` |
| KI | `TopoFlow`, run through `tools/run_topoflow.py` |

## Run
```
python run_reference.py    # 0=PASS 2=FAIL 3=missing engine
python run_reference.py --topoflow-python /path/to/python   # or set $TOPOFLOW_PYTHON
```
It copies `inputs/` to a fresh temp dir, makes the three run-setup changes below in that copy
only, runs the model with the KI tool `tools/run_topoflow.py`, checks the results against
`expected.json`, and deletes the temp dir. Run time is about 1 second.

## Run-setup changes (temp copy only, never in `inputs/`)
1. `June_20_67_path_info.cfg`: `out_directory` `~/TF_Output/Treynor` -> the temp dir. Path only.
2. `June_20_67_rain_rates.txt`: a byte-identical copy is also put in `Treynor_Iowa_30m/`.
   The cfg sets `in_directory = ..` and the meteorology component reads the rain file from there,
   but upstream git keeps it only in the case folder. File placement only.
3. `June_20_67_providers.txt`: the line `ice tf_ice_gc2d` is commented out. This is **not**
   a path change. Why it is needed: the ice component is `Disabled` in its own cfg, but a
   disabled ice component never sets `h_ice`, so the framework crashes while linking components
   (`AttributeError: 'ice_component' object has no attribute 'h_ice'`). This happens with the
   installed engine and also with clean upstream HEAD code. A disabled ice component only gives
   zero melt (`mr_ice = 0`, `vol_MR = 0` in `ice_base.py`); without it the engine also uses zero
   melt, and the report shows `vol_IM (icemelt) = 0.0`. So this change does not change results.

## Expected (recorded 2026-10-05 from our own real run; run twice, all values matched exactly)
Upstream ships no model reference output for this case, so the values are from our runs.
Between two runs the `0D-Q.txt` and raw `.rts` grid files were byte-identical.
- finished normally: return code 0, KI tool status `success`, `Simulation complete.`,
  `Finished. (June_20_67)`, `Stopping: Reached Q_peak fraction = 0.05.`
- 1592 driver steps of 6 s, simulated time 159.2 min
- outlet: Q_peak 12.4438734 m3/s at 41.8 min, final Q 0.6131273 m3/s
- volumes: rain 123547.89 m3, out over DEM edge 122404.56 m3, through main outlet 42127.20 m3,
  left in channels 1102.13 m3; mass balance error / input = 3.33e-4
- `0D-Q.txt`: 160 rows, max outlet Q 12.436923 m3/s
- `2D-Q.nc`: 160 frames, max Q 15.3555 m3/s, last frame max 0.91824 m3/s

For context only (not a check): the official observed discharge
(`__observations/June_20_1967_Observed_Discharge.txt`, not packaged) peaks at 12.415 m3/s.

## Known KI gaps
- `tools/run_topoflow.py` looks for output files only in the cfg folder (and its parent), not in
  the `out_directory` from `path_info.cfg`. So its JSON says "No output files found" and gives no
  peak flow, even though the run wrote all outputs. `run_reference.py` reads them directly.
- `tools/run_topoflow.py` checks DEM and `.rti` files only in the cfg folder, so it warns
  "No DEM file found" for the official layout (grids sit in `../__topo/`). Only a warning.
- `tools/parse_output.py` cannot read the official `*_0D-Q.txt` (it fails on the header line
  `Time [min] ...`) and reports "No discharge data available". `run_reference.py` reads the file
  itself.
- The installed engine is the upstream source tree with local edits (not upstream as is):
  `framework/emeli.py` (goes on when a provider is missing), `components/channels_base.py` and
  `topoflow_driver.py` (use 0 when icemelt is missing), `components/met_base.py` (default lat/lon
  changed from Denver to Nuxia, Tibet; sets `h_snow`/`h_ice` to 0), `utils/regrid.py` (GDAL import
  made optional). Clean upstream HEAD code cannot run this example in the KI venv: it needs
  `osgeo` (GDAL), which is not installed there, and even with GDAL it stops on the provider
  problem in change 3. The lat/lon edit does not touch this case (`PRECIP_ONLY = Yes`).
