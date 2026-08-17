# VIC — Diagnostic Triplets

Structured error knowledge: symptom → diagnosis → remedy.
Consult this file FIRST when VIC misbehaves.

---

### dt_vic_001 — FROZEN_SOIL corrupted by config_paths.py regex

**Symptom**: VIC crashes with `FROZEN_SOIL value is neither TRUE nor FALSE` — the field contains a file path instead of a boolean.

**Diagnosis** (ROOT CAUSE, identified 2026-07-09): `config_paths.create_global_param()` substituted paths with the UNANCHORED pattern `r'SOIL\s+.*'`. `re.sub` matches anywhere in a line, so it also matched the `SOIL             FALSE` substring inside

```
FROZEN_SOIL             FALSE
```

rewriting that line to `FROZEN_SOIL   /path/SOIL_PARAM_COMPLETE.txt`. It was never the template's fault — the generator corrupted its own output on every run. Reproduce with:
`re.sub(r'SOIL\s+.*', 'SOIL  /new', 'FROZEN_SOIL             FALSE')`

**Remedy**: FIXED IN PLACE. All patterns in `create_global_param()` are now anchored (`r'^SOIL\s+.*$'` with `flags=re.MULTILINE`), and the function asserts post-hoc that `FROZEN_SOIL` / `FULL_ENERGY` still hold `TRUE`/`FALSE`, raising `RuntimeError` otherwise. No hand-editing is needed. The same hazard applies to any config key that is a suffix of another key — always anchor.

---

### dt_vic_002 — Precipitation conversion factor wrong (86400 vs 10800)

**Symptom**: Simulated runoff is systematically 8x too high or 8x too low. No error message.

**Diagnosis**: CMFD precipitation is in mm/s (kg/m2/s). Converting to mm/3hr requires multiplying by 10800 (seconds in 3 hours). Using 86400 (seconds in a day) produces 8x overestimate. The model runs without error but produces vastly inflated runoff.

**Remedy**: Verify that process_forcing.py uses 10800 (not 86400) as the precipitation conversion factor for 3-hourly CMFD/MSWX data. Always validate one forcing file against CMFD raw data: pick a cell, compare daily total precip (sum of 8 timesteps) against CMFD daily total.

---

### dt_vic_003 — FORCING1 prefix mismatch

**Symptom**: VIC error `Unable to open forcing file` — the FORCING1 prefix in global_param does not match actual forcing filenames.

**Diagnosis**: VIC constructs forcing file paths by concatenating: FORCING1 prefix + latitude + `_` + longitude. If process_forcing.py generated files with a different prefix or different decimal precision, VIC cannot find them.

**Remedy**: Check the actual filename prefix in `forcing_final/` and update the FORCING1 line in global_param to match exactly. After process_forcing.py completes, always compare its output filenames against the FORCING1 prefix.

---

### dt_vic_004 — Time range mismatch between forcing and global parameter

**Symptom**: VIC error `Not enough records in forcing file` or `insufficient forcing records`.

**Diagnosis**: STARTYEAR/ENDYEAR in global_param extends beyond the time range of the forcing files, or FORCEYEARFIRST/FORCEYEARLAST do not match. The time range must be synchronized across four locations: (1) forcing_1d.py YEAR_START/YEAR_END, (2) process_forcing.py START_YEAR/END_YEAR, (3) global_param STARTYEAR/ENDYEAR, (4) global_param FORCEYEARFIRST/FORCEYEARLAST.

**Remedy**: Synchronize all four time-range variables. Always verify time range consistency before running VIC.

---

### dt_vic_005 — sed -i empties Python scripts

**Symptom**: Running sed -i on skill scripts empties the files completely — 0 bytes after sed.

**Diagnosis**: Shell expansion in sed -i commands corrupts Python script files. The sed command expands special characters in the replacement string (particularly `/` in file paths and `$` in Python f-strings), producing an invalid command that truncates the file to 0 bytes.

**Remedy**: NEVER use sed -i on skill scripts. Use Python `str.replace()` or the Edit tool instead. If a file was emptied, restore from backup: `cp <script>.bak <script>`.

---

### dt_vic_006 — config_paths.py ignores CLI arguments

**Symptom**: Passing --basin_name or --year_start on the command line has no effect.

**Diagnosis**: config_paths.py reads configuration from hardcoded variables at the top of the file, not from argparse or sys.argv. Passing CLI arguments is silently ignored.

**Remedy**: Edit the variables directly at the top of config_paths.py (BASIN_NAME, YEAR_START, YEAR_END, RESOLUTION, shp_file) instead of passing CLI arguments.

---

### dt_vic_007 — SOIL_PARAM_COMPLETE.txt wrong column count

**Symptom**: VIC error parsing soil file — `Error in soil file` or `Invalid number of soil`.

**Diagnosis**: fill_parameters2.py interpolation failed for some cells, producing rows with missing or extra columns. VIC expects exactly N columns per row (~53 for a 3-layer configuration). If some cells have no coverage in global reference data, rows may be incomplete.

**Remedy**: Check column count consistency: `awk '{print NF}' SOIL_PARAM_COMPLETE.txt | sort -u` should show exactly one number. Re-run fill_parameters2.py or manually pad/trim problematic rows.

---

### dt_vic_008 — Stale forcing files from previous basin

**Symptom**: Forcing files from a previous basin are mixed with the current basin's files. No error — model runs with wrong meteorological data.

**Diagnosis**: forcing_1d.py uses BASIN_TAG as a suffix in output filenames. If old files with a different BASIN_TAG remain in the output directory, both old and new files coexist, and process_forcing.py may read the wrong ones.

**Remedy**: Delete all files in forcing_1d/ before running forcing_1d.py for a new basin: `rm -f forcing_1d/*.nc`. Verify the directory is empty before re-running.

---

### dt_vic_009 — Grid cell count is 0 (basin too small or wrong CRS)

**Symptom**: make_basin_grid_nc.py produces a NetCDF with no cells — `0 grid cells`.

**Diagnosis**: The basin shapefile does not intersect any grid cell centers at the chosen resolution. At 0.25 deg resolution, each cell is ~625 km2, so basins under ~1000 km2 may have 0-2 cells. A missing/wrong CRS (projected instead of geographic) will also cause zero intersection.

**Remedy**: Switch to 0.1 deg resolution for small basins, or check and fix the shapefile CRS. Use 0.1 deg for basins < 5000 km2.

---

### dt_vic_010 — process_forcing.py needs SOIL_PARAM_COMPLETE.txt

**Symptom**: `FileNotFoundError: SOIL_PARAM_COMPLETE.txt` — soil parameters must be generated before forcing.

**Diagnosis**: process_forcing.py reads grid cell coordinates from SOIL_PARAM_COMPLETE.txt. The dependency is: Grid (s2) -> Soil (s3) -> Forcing (s5). This is not obvious because forcing is logically about meteorological data, not soil. However, process_forcing.py needs the exact grid cell coordinates from the soil file.

**Remedy**: Run soil parameter generation (fill_parameters1.py + fill_parameters2.py) before process_forcing.py. Always follow the dependency order: Grid -> Soil -> Forcing.

---

### dt_vic_011 — Uncalibrated default parameters produce poor results

**Symptom**: VIC runs successfully but simulated discharge is physically unreasonable — NSE < 0.3, PBIAS > 50%.

**Diagnosis**: Default VIC soil parameters (binfilt, Ds, Dsmax, Ws, soil depths) are not tuned for the specific basin. Typical uncalibrated results show NSE 0.0-0.3 and PBIAS 30-60%. Key parameters: binfilt (infiltration curve), Ds/Dsmax (baseflow), Ws (soil moisture threshold), soil_d2/soil_d3 (layer depths).

**Remedy**: Run AI-assisted calibration using the vic_cali_ai skill if observed discharge data is available. Calibration can improve NSE from ~0.3 to 0.8+. If no observed data, report results as uncalibrated.

---

### dt_vic_012 — Temperature K-to-C conversion missing or double-applied

**Symptom**: Mean air temperature is ~273 K too high or too low. No error message.

**Diagnosis**: CMFD stores temperature in Kelvin. VIC expects Celsius. If the conversion (-273.15) is missing, VIC sees temperatures of ~273-310 K interpreted as Celsius, producing extreme ET. If applied twice, temperatures become ~-273 C, causing zero ET.

**Remedy**: Check first forcing file: column 1 is AIR_TEMP, values should be -40 to +50 (Celsius). If values are 230-320: add -273.15 conversion. If values are -300 to -230: remove one of the two conversions.

---

### dt_vic_013 — Forcing files incomplete (wrong line count)

**Symptom**: VIC error `Not enough records in forcing file` — same as dt_vic_004 but different root cause.

**Diagnosis**: forcing_1d.py or process_forcing.py produced incomplete data — some timesteps are missing, typically at year boundaries or due to interrupted processing. VIC expects exactly n_days * 8 lines per forcing file for 3-hourly data.

**Remedy**: Check line count: `wc -l <forcing_file>`. Expected: n_days * 8 (e.g., 365*8=2920 per non-leap year). If too few lines, delete forcing_1d/ and forcing_final/ contents and re-run.

---

### dt_vic_014 — MSWX data path moved

**Symptom**: forcing_1d.py fails with FileNotFoundError — MSWX data path has moved.

**Diagnosis**: MSWX forcing data was originally at `KISSPATH_DATA/新加卷/msxw/` (auto-mounted external drive) and has been moved to `KISSPATH_FORCING/`. Scripts referencing the old path will fail.

**Remedy**: Update INPUT_DATA_DIR in forcing_1d.py to `KISSPATH_FORCING/`. Verify the path exists with `ls KISSPATH_FORCING/`.

---

### dt_vic_015 — CMFD used for out-of-China basin

**Symptom**: VIC runs successfully but simulated discharge is physically unreasonable — forcing_1d.py used CMFD (China-only) for a basin outside China.

**Diagnosis**: CMFD only covers mainland China (17.5-55N, 72.5-140E). For basins outside this domain, forcing_1d.py must use MSWX (`KISSPATH_FORCING/`). The script does NOT auto-detect this. When CMFD is used out-of-domain, xarray clips to nearest China border cells, producing completely wrong forcing. Dangerous silent failure.

**Remedy**: Check basin coordinates: if lat/lon is outside China (17.5-55N, 72.5-140E), MUST use MSWX. Change INPUT_DATA_DIR in forcing_1d.py to `KISSPATH_FORCING/`. Also cap max_workers to 4 for MSWX.

---

### dt_vic_016 — forcing_1d.py hangs with MSWX (I/O saturation)

**Symptom**: forcing_1d.py hangs with zero output files for minutes when using MSWX — all workers stuck in disk I/O wait state.

**Diagnosis**: MSWX yearly files are 3-9 GB each (global coverage). Default max_workers uses all CPU cores (e.g., 113 workers). When 100+ workers each try to read multi-GB files from the same disk, I/O hits 100% and all workers enter D (uninterruptible sleep) state.

**Remedy**: Cap max_workers to 4 when using MSWX data. Kill stuck workers: `pkill -9 -f forcing_1d.py`. Add auto-detection: `if 'msxw' in str(INPUT_DATA_DIR): max_workers = 4`.

---

### dt_vic_017 — Koksilah River case: CMFD used for Canada

**Symptom**: Agent used CMFD (China-only) forcing for Koksilah River (BC, Canada) — produced meaningless forcing data that was silently wrong.

**Diagnosis**: forcing_1d.py INPUT_DATA_DIR defaulted to CMFD; agent did not check basin location vs forcing coverage. This is the discovered instance that led to dt_vic_015.

**Remedy**: Added FORCING DATASET SELECTION section to CLAUDE.md. CLAUDE.md now has mandatory forcing check before any simulation.

---

### dt_vic_018 — forcing_1d.py MSWX hung 15+ minutes (I/O saturation)

**Symptom**: forcing_1d.py with MSWX hung for 15+ minutes producing zero output — 113 workers saturated disk I/O on 3-9 GB files.

**Diagnosis**: Default max_workers uses all CPU cores; MSWX files are 100x larger than CMFD files. This is the discovered instance that led to dt_vic_016.

**Remedy**: Capped max_workers to 4 for MSWX. Auto-detect MSWX and cap workers.

---

### dt_vic_019 — VIC has NO routing: gauge discharge needs Lohmann route_1.0

**Symptom**: You need daily discharge (m3/s) at a gauge, but the flux files only contain `OUT_RUNOFF` / `OUT_BASEFLOW` in mm. `OUT_DISCHARGE` is all zeros (or absent).

**Diagnosis**: `dag.yaml` states it plainly: "Inside VIC, OUT_DISCHARGE is generated only by the optional lake module; basin-scale discharge against a gauge requires an external routing model." Summing runoff+baseflow over the basin and calling it discharge is wrong — it has no travel time, so the hydrograph has no lag and no attenuation. Comparing that to a gauge produces a plausible-looking but meaningless NSE.

**Remedy**: Run the Lohmann routing binary `model/route_1.0/src/rout` after VIC. Its 5 parameter files are built by the KI tool `s5_routing/build_routing_param.py` (added 2026-07-09). Preprocess each VIC flux file to 7 columns — `year month day prec evap runoff baseflow`, i.e. `df.iloc[:, [0,1,2,3,18,16,17]]` for the standard OUTVAR list — into `routing_param/vic_in/fluxes_<LAT>_<LON>`, then `cd routing_param && rout rout_global.txt`. Daily m3/s lands in `rout_out/<STA>.day`.

---

### dt_vic_020 — Routing flow-direction grid built from a COARSENED DEM is wrong

**Symptom**: `build_routing_param` reports a nonsensical outlet, low initial connectivity (e.g. "initial connectivity: 51/251") and needs dozens of "repair" iterations. The station cell's flow accumulation is SMALLER than that of cells upstream of it.

**Diagnosis**: The original `skills/routing-run/s5_routing_param/run_build_routing_new.py` resampled the DEM to 0.05° (~5.5 km) with an AVERAGE resample and ran `fill_depressions` + `d8_flow_accumulation` on that, over a **bbox-cropped** (not basin-masked) DEM. Averaging obliterates incised gorges, so `fill_depressions` floods the plateau and reroutes the network. And because the crop is a bbox, a boundary VIC cell's footprint straddles the *downstream* river, whose huge accumulation is then imported by the `max()` aggregation. At Tangnaihai the gauge cell drained 1,122 units while a cell 300 km upstream drained 3,891 — physically impossible.

**Remedy**: FIXED. `s5_routing/build_routing_param.py` now reuses the NATIVE-resolution `flow_accum.tif` + `basin.tif` from `ki_tools_common.terrain_ops.delineate_basin` (pass them via `VIC_FLOW_ACCUM` / `VIC_BASIN_RASTER` / `VIC_FILLED_DEM`, or let the tool call `delineate_basin` itself) and masks accumulation to the basin before aggregating. The outlet is then the arg-max accumulation cell, and `VIC_OUTLET_LON/LAT` is used to ASSERT that cell is the gauge's own cell (raises if >1 cell away). Sanity check: `max_accum * pixel_area` must equal the delineated basin area. At Tangnaihai this gives 122,982 km2 and connectivity 251/251 with zero repair iterations.

---

### dt_vic_021 — Scoring window chosen before checking observation coverage

**Symptom**: `compute_calval_metrics` returns NaN, or n=0, or a validation NSE computed from a handful of days.

**Diagnosis**: The KDT standard split (spinup 1980, cal 1981-85, val 1986-90) assumes a Bengbu-like continuous record. Many Chinese gauge files are sparse and pad missing days with `-99`. 唐乃亥 (Yellow R.) has valid daily Q ONLY for {1985, 1987, 2007-2020, 2022, 2023} — 1986 and 1988-2006 are entirely `-99`. Running the standard window yields 2 years of calibration data and ZERO validation days.

**Remedy**: ALWAYS profile obs coverage before choosing the simulation period:
`v = q[q > -90]; v.groupby(v.index.year).size()`
Pick the first contiguous fully-observed decade, keep a >=1-year spinup ahead of it, confirm the forcing dataset covers it (CMFD spans 1951-2024), and record the deviation from the standard split in `notes`. For 唐乃亥: spinup 2005-06, cal 2007-11, val 2012-16.

---

### dt_vic_022 — config_paths.py patched scripts OUTSIDE the KI (silent no-op)

**Symptom**: You run `python config_paths.py`, it prints "✓ 已更新脚本", yet the stage scripts still point at the previous basin and write to the old `outputs/<old_basin>/` tree.

**Diagnosis**: `SCRIPTS_DIR` was hard-coded to `WORKSPACE_ROOT/"skills"/"vic-auto-run"`, a *copy* of the stage scripts living outside `knowledge_infrastructure/`. The documented workflow then executed the untouched KI copies, so the configuration step did nothing.

**Remedy**: FIXED — `SCRIPTS_DIR = Path(__file__).resolve().parent`. Better still, do not rely on the in-place regex rewriting at all: every stage script (`s1_grid`, `s2_forcing`, `s3_soil`, `s4_veg`, `s5_routing`) now reads its configuration from the environment. Export `VIC_BASIN_NAME`, `VIC_BASIN_SHP`, `VIC_OUT_ROOT`, `VIC_CMFD_DIR`, `VIC_YEAR_START/END`, `VIC_START_DATE/END_DATE`, `VIC_FORCING_PREFIX` and run the scripts unmodified. This also removes the `_xixian` NetCDF suffix and the `huai_01dy_025deg_` forcing prefix that were hard-coded into `forcing_1d.py` / `process_forcing.py` and silently made a new basin find zero input files.

---

### dt_vic_023 — Stage script SIGSEGVs at exit *after* writing correct output; pipeline dies with rc=1

**Symptom**: A stage script prints its full success banner ("成功率: 100.0%", all N cells written), every expected output file is on disk and correct, yet the driver reports the stage failed. `run.log` ends with:

```
STDERR: .../xarray/backends/plugins.py:109: RuntimeWarning: Engine 'gmt' loading failed:
Error loading GMT shared library at 'libgmt.so'.
```

and the shell/subprocess return code is `139` (SIGSEGV) or `-11`. A driver that does `if p.returncode != 0: sys.exit(1)` then aborts the whole run at a stage that actually SUCCEEDED. The 2026-07-09 唐乃亥 detached run died exactly here: `state.json` recorded `returncode: 1` at s6 `process_forcing.py`, all 251 forcing files were correct, and the orchestrator captured **null metrics** for a run whose physics were fine.

**Diagnosis**: Two independent conditions must both hold.

1. `pygmt` 0.18.0 is installed on this server but the GMT C library is **not** (`ldconfig -p | grep gmt` → nothing; there is no `libgmt.so` anywhere on disk). Its `xarray.backends` entrypoint `pygmt.xarray:GMTBackendEntrypoint` therefore fails to import.
2. A **bare** `xr.open_dataset(path)` — no `engine=` — makes xarray enumerate *every* installed backend entrypoint (`plugins.list_engines()`). That probe imports `rex` → `h5py`, dlopening h5py's bundled `libhdf5` first. `netCDF4`'s C calls then bind to that foreign HDF5, and the interpreter dies with SIGSEGV during HDF5 teardown — **after** the data has been read and written correctly.

The crash is at interpreter *exit*, so it is invisible in the script's own stdout. It is nondeterministic across stages: whichever library wins the global symbol table first decides whether that stage survives. `forcing_1d.py` survived while `process_forcing.py` died in the same run.

Minimal reproduction (any NetCDF file):

```
python3 -c 'import xarray as xr; xr.open_dataset("grid.nc").close()'          # rc=139  SIGSEGV
python3 -c 'import netCDF4, xarray as xr; xr.open_dataset("grid.nc", engine="netcdf4").close()'  # rc=0
```

**Remedy**: FIXED in every stage script. Two rules, both required — pinning alone is sufficient in isolation, but import order is the cheap insurance when a third-party import (`rioxarray`, `rasterstats`) pulls HDF5 in behind your back:

1. `import netCDF4` **before** `import xarray` (`# isort:skip`, `# noqa: F401`).
2. **Never** call `xr.open_dataset()` without `engine=`. Use the shared `open_nc()` helper — present in `s2_forcing/forcing_1d.py`, `s2_forcing/process_forcing.py`, `s3_soil/fill_parameters1.py`, `s4_veg/process_vegetation_detailed.py` — which pins `netcdf4` and falls back to `h5netcdf`.

Guard against regression:

```
grep -rn "open_dataset(" --include=*.py s1_grid s2_forcing s3_soil s4_veg s5_routing | grep -v "engine="
```

must return nothing. Do **not** "fix" this by making the driver tolerate a nonzero return code: a real crash and a teardown crash are then indistinguishable, and the next genuine failure will be silently scored.

---

### dt_vic_024 — `create_global_param()` writes NOTHING and does not raise (dead template path)

**Symptom**: step s7 prints `✗ 模板文件不存在: .../outputs/pearl_river_calibration_ai/best_run/global_param.txt`,
no `global_param_<basin>.txt` is produced, and the run dies much later at
`vic_classic.exe -g <missing file>` with an unrelated-looking I/O error.

**Diagnosis**: `config_paths.PATH_CONFIG["global_param_template"]` defaulted to a path under
`outputs/` — an *output* directory of an old calibration run, not a KI asset. That directory
does not exist on this server. Worse, `create_global_param()` handled the miss with
`return False`; no caller checked the return value, so the failure was silent at the point it
occurred. A KI must never depend on `outputs/` for an input.

**Remedy**: FIXED (2026-07-10, Harbin/Songhua run).
* The template now ships inside the KI: `docs/vic_param/global_param_template.txt`, and is the
  default value of `VIC_GLOBAL_PARAM_TEMPLATE`.
* A missing template now raises `FileNotFoundError` instead of returning `False`.
* The template's header documents that its 21 `OUTVAR` lines are order-critical: `s5_routing`
  and SKILL.md slice the flux file as `df.iloc[:, [0,1,2,3,18,16,17]]`
  (`year month day OUT_PREC OUT_EVAP OUT_RUNOFF OUT_BASEFLOW`). Reorder an OUTVAR and `rout`
  is silently fed the wrong columns.

---

### dt_vic_025 — A new basin needs FOUR env vars SKILL.md's quickstart table does not list

**Symptom**: `s5_routing/build_routing_param.py` raises
`RuntimeError: No VIC_FLOW_ACCUM/VIC_BASIN_RASTER/VIC_FILLED_DEM supplied and no
VIC_OUTLET_LON/LAT to delineate with`, or `KeyError: 'VIC_BASIN_SHP'`.

**Diagnosis**: SKILL.md's "Server quickstart" env table stops at `VIC_GLOBAL_PARAM_TEMPLATE`,
but the s9 routing stage additionally reads `VIC_STATION_NAME`, `VIC_OUTLET_LON`,
`VIC_OUTLET_LAT` and `VIC_DEM`. The outlet coordinates are not optional for a new basin: they
are both the delineation pour point and the assertion that the max-accumulation cell really is
the gauge cell.

**Remedy**: export all of them. Working Harbin/Songhua invocation (866 cells, 384,411 km² at the
outlet vs ~391,000 km² published, connectivity 866/866):

```bash
export VIC_BASIN_NAME=harbin_songhua_1980_1987
export VIC_BASIN_SHP=KISSPATH_DATA/shp/harbin_songhua_shp/harbin_songhua_boundary_shp/harbin_songhua_boundary.shp
export VIC_CMFD_DIR=KISSPATH_FORCING/Data_forcing_03hr_010deg
export VIC_YEAR_START=1980 VIC_YEAR_END=1987
export VIC_START_DATE=1980-01-01 VIC_END_DATE=1987-12-31
export VIC_FORCING_PREFIX=harbin_025deg_
export VIC_STATION_NAME=HRB
export VIC_OUTLET_LON=126.6 VIC_OUTLET_LAT=45.75
export VIC_DEM=KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif
export VIC_STREAM_THRESHOLD=200000 VIC_SNAP_DIST_M=5000   # scale threshold with basin size
```

`VIC_STREAM_THRESHOLD` is in **native DEM cells**, so it must grow with the basin: 20,000 cells
(~160 km² at 90 m) is right for a 10³-km² headwater but leaves a 4×10⁵-km² basin's snap target
ambiguous. 200,000 worked at Harbin.

**Note on `delineate_basin` cost**: it runs `fill_depressions` on whatever raster it is handed,
with no internal bbox crop. Never pass the 3.5 GB `china_dem_90m.tif` directly —
`build_routing_param.py` crops to the basin bbox + 0.5° first (`crop_dem_to_basin`). Harbin's
crop was 10.4° × 10.9° and the whole delineation took ~2 minutes.

---

### dt_vic_026 — 哈尔滨 (Songhua) observation record: a 13-year hole after 1987

**Symptom**: the KDT standard split (spinup 1980 / cal 1981-85 / val 1986-90) appears to work,
but `nse_val` is computed on ~730 days instead of ~1826.

**Diagnosis**: `KISSPATH_DATA/china_water_level/松辽txt/哈尔滨.txt` is complete daily
1980-1987, then `-99` for **1988-2000** inclusive, then 2001-2003, 2005-2019, 2021-2023.
This is the exact trap dt_vic_021 warns about, at a second basin.

**Remedy**: profile first (`v = q[q > -90]; v.groupby(v.index.year).size()`), then either
truncate the validation window to 1986-1987 (what the Harbin real-case did, keeping the
standard spinup/cal periods intact) or move the whole experiment to the 2005-2019 block.
Do not silently accept a 5-year `period_validation` string that only 2 years of data back.

---

### dt_vic_027 — all_metrics / compute_calval_metrics return UPPERCASE keys

**Symptom**: the model finished (`vic rc=0`, `rout rc=0`, routed `.day` on disk) but the
orchestrator recorded `nse: null`. The runner's tail shows
`KeyError: 'nse'` at `cv["calibration"]["nse"]`.

**Diagnosis**: `ki_tools_common.metrics.all_metrics` returns
`{'NSE','KGE','PBIAS','RMSE','r'}` and `validators.standard_calval.compute_calval_metrics`
returns `{'NSE','KGE','PBIAS','r','n'}` per period — UPPERCASE for every metric except
`r`. A runner that indexes `['nse']` dies AFTER the expensive part has succeeded, and
`kdt_detached_run.py` still writes `DONE`, so the failure looks like "the model produced
nothing". Verified 2026-07-10: the 哈尔滨 run burned 13 min of VIC + routing and was
discarded. The same casing bit the Harbin runner and is latent in any new runner.

**Remedy**: index `m["NSE"]`, `m["KGE"]`, `m["PBIAS"]`, `m["RMSE"]`, `m["r"]`. Do not
"fix" `ki_tools_common` — every other KI depends on the current casing. Always write
`result.json` from a `try/except` that emits `status:"failed"` with the traceback, so a
scoring bug can never masquerade as a null-metrics model failure.

---

### dt_vic_028 — Lohmann VELOCITY default (1.5 m/s) is a Bengbu value; it caps NSE via r

**Symptom**: routed hydrograph has a plausible volume but poor NSE; `r` is stuck around
0.5-0.6 no matter which soil parameter is calibrated. At 哈尔滨: NSE −0.40, r 0.589,
PBIAS +28.9%.

**Diagnosis**: `s5_routing/build_routing_param.py` hard-codes `VELOCITY = 1.5` m/s and
`DIFFUSIVITY = 800` m²/s (env `VIC_ROUT_VELOCITY` / `VIC_ROUT_DIFF`, undocumented in
SKILL.md). Those reproduce Bengbu (121,330 km²). At 哈尔滨 (398,330 km², flat Songnen
Plain) the resulting basin-mean unit-hydrograph lag is **6.2 d** while the observed lag
is **28 d**. Two consequences that are easy to misread:

* `NSE <= r**2`. With zero-lag r = 0.589 the NSE ceiling is **0.347** — the target
  NSE >= 0.5 was arithmetically unreachable, and no soil parameter could have fixed it.
* `rout` renormalises UH_S (`unit_hyd_routines.f`, `MAKE_UHM` and `MAKE_GRID_UH` both
  divide by their sum), so routing is mass-conserving at ANY velocity. **A velocity
  error moves timing and can NEVER move PBIAS.** A wet bias is therefore never evidence
  that the routing is right.

**Remedy**: before scoring, measure both numbers with `s5_routing/run_routing.py`:
`observed_lag_days(obs, sim)` (lag-correlation) and `basin_mean_uh_lag(uh_s)` (read from
the `.uh_s` rout itself writes). If the observed lag exceeds the UH lag, IDENTIFY the
velocity by bisecting until they agree — on the CALIBRATION window only. Do not fit
velocity to NSE. At 哈尔滨 this gives v = 0.15 m/s (UH lag 27.8 d), zero-lag r
0.589 → 0.894, NSE ceiling 0.347 → 0.799.

Read the identified value as an **effective basin residence time, not a channel
celerity**: Lohmann's linearised Saint-Venant scheme lumps hillslope, floodplain,
wetland and reservoir storage into (velocity, diffusivity). Where that storage dominates
(large flat basins), prefer a routing scheme with explicit storage — CaMa-Flood 4.20 is
on this server (`cama_maps_15min_extracted`). Note `rout.f` caps the routed response at
`UH_DAY = 96` days and the within-cell `UH.all` at `KE = 12` days, so `UH.all` alone can
never supply more than ~12 d of lag.

**VELOCITY SATURATES — below a basin-dependent threshold it is an INERT knob.**
`MAKE_UHM` (`unit_hyd_routines.f`) builds each cell's impulse response on
`t ∈ (0, LE*DT] = (0, 48 h]` and then **renormalises it to unit mass**. Once
`xmask / velocity` exceeds 48 h the clipped kernel stops changing shape, so its mean
travel time freezes at ~1.3 d per cell no matter how small `velocity` gets. The
basin-mean UH lag therefore asymptotes to

    uh_lag_max  ≈  mean(UH.all)  +  mean_flow_path_in_cells × ~1.3 d

At 哈尔滨 (mean path 20.4 cells) that ceiling is **29.8 d**, measured directly by routing
at `v = 0.002`. Observed demand was ~33 d. Consequence: dropping `v` from 0.15 to 0.002
buys only 2 d of lag and moves held-out NSE by 0.03 (0.488 → 0.521), and a 5-7 day
residual lead survives at EVERY attainable velocity.

So a velocity optimiser will happily walk to its lower bound and report "success" while
the model has stopped responding. **Always probe `v → 0` first** (one 7 s `rout` call)
to learn the ceiling, then:

* if `target_lag < uh_lag_max` → identify `velocity` by bisection (the honest case);
* if `target_lag >= uh_lag_max` → the scheme is **structurally insufficient** for this
  basin. Pin `velocity` to a pre-declared constant (the `rout_velocity` `range` lower
  bound in `calibration.yaml`, 0.10 m/s), report the plateau's NSE spread so the reader
  can see the parameter is unidentifiable, and say so. Do NOT tune inside the plateau,
  and do NOT report the plateau optimum as an identified value.

---

### dt_vic_029 — `rout` opens `<STA>.uh_s` with Fortran `status='new'`

**Symptom**: a second `rout` run in the same directory dies on the OPEN of
`HRB  .uh_s`; or worse, an operator copies the old `.uh_s` in, `rout` takes the
`UH_STRING(1:4) .ne. 'NONE'` branch, and silently routes with the PREVIOUS velocity's
unit hydrograph — the new velocity has no effect at all and the hydrograph is unchanged.

**Diagnosis**: `unit_hyd_routines.f` `MAKE_GRID_UH` does
`open(98, file = NAME5//'.uh_s', status='new')`. `status='new'` requires the file to be
absent. The station file's second line is the UH_S filename; `NONE` means "build it".
`NAME5` is the station name padded to 5 characters, so the file is literally `HRB  .uh_s`
(two spaces).

**Remedy**: run every `rout` invocation in a FRESH scratch directory —
`s5_routing/run_routing.route()` does exactly this and never mutates `routing_param/`,
which also makes a (velocity, diffusivity) sweep safe to parallelise. One call is ~7 s
for 866 cells because velocity and diffusivity affect ONLY the routing stage: **no VIC
re-run is needed to change them.**

---

### dt_vic_030 — a 1-year spin-up leaves VIC's deep soil layer filling for 5+ years

**Symptom**: `nse_cal` >> `nse_val` and PBIAS grows steadily through the record. Looks
exactly like overfitting; it is not.

**Diagnosis**: `fill_parameters1.py` writes `init_moist` = 66.79 mm for every layer, i.e.
~10-14% saturation, and the KI's soil column is 0.1 + 0.3 + 1.5 = 1.9 m. SKILL.md's
standard split gives it ONE spin-up year (1980). At 哈尔滨 the column takes ~5-6 years to
equilibrate. From the model's own flux output, basin-sampled annual means:

| year | 1980 | 1981 | 1982 | 1983 | 1984 | 1985 | 1986 | 1987 |
|---|---|---|---|---|---|---|---|---|
| baseflow (mm/yr) | 22.5 | 38.3 | 48.9 | 72.2 | 70.7 | 78.0 | 111.3 | 87.9 |
| storage on 31 Dec (mm) | 320 | 397 | 391 | 460 | 484 | 504 | 492 | 499 |

Baseflow quintuples; the baseflow index climbs 0.31 → 0.54. Because the still-filling
store absorbs water, PBIAS *rises* as the model equilibrates: **+19.5% (1981-82),
+28.5% (1983-85), +36.8% (1986-87)**. The calibration window is the least equilibrated
part of the record, so any cal-vs-val gap is a spin-up transient.

**Remedy**: before scoring, check the storage trend
(`OUT_SOIL_MOIST_*` + `OUT_SWE` on 31 Dec of each year) and the baseflow trend. If either
is still climbing at the start of the calibration window, extend the spin-up. CMFD covers
1951-2024, so starting the simulation ~5-10 years before `CAL_START` costs only VIC time
(~95 s per simulated year for 866 cells in water-balance mode). Do NOT read a
`nse_cal > nse_val` gap as overfitting until this check is clean.

---

### dt_vic_031 — FROZEN_SOIL TRUE is blocked by bubble = -9999 / fs_active = 0, then by NODES

**Symptom**: two failures in sequence when enabling the frozen-soil module on a cold basin.
First, VIC reads sentinel values into `estimate_layer_ice_content()`. Then, once the soil
file is fixed, VIC aborts with
`read_soilparam.c:770 ... The number of soil thermal nodes (N) is too small for the supplied
damping depth (4.000000) with EXP_TRANS set to TRUE ... 5*ln(dp+1)<Nnodes-1`.

**Diagnosis**: (a) `fill_parameters1.py:213-214` writes `bubble` (cols 28-30) = -9999 and
`fs_active` (col 53) = 0. Both are inert while `FULL_ENERGY` and `FROZEN_SOIL` are FALSE, so
no reference basin ever noticed — but they make `FROZEN_SOIL TRUE` unusable.
(b) `FROZEN_SOIL TRUE` makes VIC set `QUICK_FLUX = FALSE`
(`drivers/classic/src/get_global_param.c:111`), which leaves `EXP_TRANS` at its TRUE default.
`EXP_TRANS` then demands `5*ln(dp+1) < NODES-1`. The KI's `dp` is 4.0 m, so
`5*ln(5) = 8.05` and **NODES must be >= 10**. `NODES 3` (the water-balance default) and
`NODES 7` both abort.

**Remedy**: `fill_parameters2.py` now derives `bubble = 0.32*expt + 4.3` (VIC's own texture
relation, the one used to build the Maurer/Livneh CONUS soil files; gives 7.3-8.4 cm here)
and sets `fs_active = 1`. Use the shipped
`docs/vic_param/global_param_template_frozen.txt` (`FULL_ENERGY FALSE`, `FROZEN_SOIL TRUE`,
`NODES 10`) via `VIC_GLOBAL_PARAM_TEMPLATE`. Cost: ~9.5x the water-balance run
(75 s per simulated month for 866 cells, vs 8 s). Verify the run with `OUT_SOIL_TEMP_0`
(-18.6 degC at 哈尔滨 in January — if it is ~0 the thermal solution is not running).
