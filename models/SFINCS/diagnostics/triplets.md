# SFINCS — Diagnostic Triplets

Structured error knowledge: symptom → diagnosis → remedy.
Consult this file FIRST when SFINCS misbehaves.

---

### dt_001 — Precipitation in mm/3hr not converted to mm/hr

**Symptom**: Flood depths 10-100x too high; entire domain floods unrealistically.

**Diagnosis**: CMFD and MSWX forcing data are accumulated over 3-hour windows (mm/3hr). SFINCS expects instantaneous rates in mm/hr. If mm/3hr values are passed directly, precipitation is 3x too high. For example, 30 mm/3hr becomes 30 mm/hr instead of 10 mm/hr.

**Remedy**: Divide CMFD/MSWX precipitation by 3.0 before writing to sfincs.precip. Check max value is reasonable (<100 mm/hr for extreme events). `prepare_sfincs_rainfall.py` always divides by 3 and validates range.

---

### dt_002 — Precipitation in m/s instead of mm/hr

**Symptom**: No flooding despite heavy rain event. Max depth < 0.01m.

**Diagnosis**: Some climate model outputs provide precipitation in kg/m2/s (= m/s water equivalent). SFINCS expects mm/hr. 1 m/s = 3,600,000 mm/hr. If not converted, values are effectively zero.

**Remedy**: Convert from m/s to mm/hr: multiply by 3600 * 1000. Check forcing data units in source NetCDF metadata. Verify precipitation maximum is >1 mm/hr during storm events.

---

### dt_003 — Discharge in mm/day (VIC) not converted to m3/s

**Symptom**: CaMa-Flood discharge BC produces wrong flood extent; river flow too small.

**Diagnosis**: VIC outputs runoff in mm/day per grid cell. To convert to discharge for SFINCS: `Q_m3s = runoff_mm_day * cell_area_m2 / (1000 * 86400)`. CaMa-Flood outflw is already in m3/s, so no conversion needed for CaMa output. But if using VIC runoff directly, the conversion is critical.

**Remedy**: Use CaMa-Flood outflw (already m3/s) for SFINCS discharge BC. If using VIC directly, convert: `Q = runoff_mm * area_m2 / (1000 * 86400)`. `cama_to_sfincs_boundary.py` reads CaMa outflw directly in m3/s.

---

### dt_004 — Vertical datum mismatch (EGM96 vs MSL)

**Symptom**: Coastal water levels systematically offset by 20-40m from expected.

**Diagnosis**: Copernicus GLO-30 and China DEM 90m use EGM96 geoid heights. Tidal models (FES2014) and many water level records use local MSL or chart datum. The difference can be 20-40m depending on location. For coastal flood modeling, this offset makes water level BCs appear permanently flooded or permanently dry.

**Remedy**: Verify both DEM and water level BC use the same vertical datum. Apply geoid correction if needed. CaMa-Flood sfcelv uses same geoid as DEM (both EGM96), so usually consistent.

---

### dt_005 — CRS mismatch: geographic degrees used with metric dx/dy

**Symptom**: SFINCS crashes immediately with grid error or produces garbage output.

**Diagnosis**: SFINCS dx/dy are in the CRS unit. If EPSG is geographic (e.g., 4326), dx=100 means 100 degrees, not 100 meters. The grid must use a projected CRS (e.g., UTM) for metric dx/dy values.

**Remedy**: Use a projected CRS (UTM). `setup_sfincs_domain.py` auto-detects the correct UTM zone. Verify dx/dy are in meters, not degrees.

---

### dt_006 — x0/y0 origin mismatch after DEM reprojection

**Symptom**: Flood map displaced from actual terrain; flooding in wrong locations.

**Diagnosis**: When reprojecting DEM to SFINCS grid, the origin (x0, y0) must be consistent between the grid definition and the dep/msk files. If the DEM is clipped or reprojected separately, the origin may shift.

**Remedy**: Ensure `build_sfincs_topobathy` uses the exact same x0, y0, dx, dy from grid_info.json. Overlay flood map on DEM to check alignment.

---

### dt_007 — Mask boundary cells set to 3 (active) instead of 2 (outflow)

**Symptom**: Water flows uphill at domain boundary; water accumulates at edges.

**Diagnosis**: SFINCS mask values: 0=inactive, 1=boundary inflow, 2=outflow, 3=active interior. If edge cells are set to 3, water cannot leave the domain and accumulates unrealistically at boundaries.

**Remedy**: Set edge cells of active domain to mask=2 (outflow). `build_sfincs_topobathy.py` auto-detects edge cells and sets to 2.

---

### dt_008 — Subgrid resolution too fine relative to computational grid

**Symptom**: Checkerboard pattern in flood depth; alternating wet/dry cells.

**Diagnosis**: The subgrid lookup tables approximate volume-depth relationships within each computational cell. If the subgrid resolution is too fine (e.g., 1m subgrid on 200m computational grid = 200x ratio), the tables become noisy and produce numerical artifacts. Recommended ratio: 5-20x.

**Remedy**: Reduce subgrid ratio to 5-20x. For dx=100m, use 5-20m subgrid. `setup_sfincs_domain.py` caps subgrid ratio at 20x.

---

### dt_009 — CFL violation: dt too large for dx

**Symptom**: Model crashes with NaN or Inf after N timesteps.

**Diagnosis**: CFL condition for shallow water equations: `dt <= dx / sqrt(g * h_max)`. For dx=100m and h_max=10m: dt_max = 100 / sqrt(9.81*10) = 10.1s. Exceeding this causes numerical instability and NaN propagation.

**Remedy**: Reduce dt. Use `dt <= 0.75 * dx / sqrt(9.81 * h_max_expected)`. `generate_sfincs_inp.py` auto-computes CFL-stable dt.

---

### dt_010 — Advection instability on steep terrain

**Symptom**: Very slow convergence; oscillating water levels; simulation takes 100x expected.

**Diagnosis**: The momentum damping coefficient alpha (default 0.75) controls numerical stability. With advection=1 on steep terrain, alpha < 0.5 can cause oscillations. The solver may auto-reduce dt, drastically increasing runtime.

**Remedy**: Set advection=0 (usually not needed for flood inundation). If needed, increase alpha to 0.75-0.95. `generate_sfincs_inp.py` sets advection=0 by default.

---

### dt_011 — Grid resolution too fine for domain size

**Symptom**: Runtime 10-100x longer than expected; grid seems too fine for domain.

**Diagnosis**: SFINCS cost is proportional to n_cells * n_timesteps. Halving dx quadruples cells and halves dt (CFL), giving 8x cost. For a 50km x 50km domain: dx=100m gives 250,000 cells (manageable), dx=10m gives 25,000,000 cells (250x slower).

**Remedy**: Increase dx. Use subgrid for fine-resolution effects. For domains >10km, use dx >= 50m. `setup_sfincs_domain.py` warns when total_cells > 1,000,000.

---

### dt_012 — Boundary point locations not aligned to active mask cells

**Symptom**: Water level BC has no effect; boundary appears dry.

**Diagnosis**: SFINCS matches bnd point coordinates to the nearest grid cell. If the nearest cell has mask=0 (inactive), the BC is ignored silently. The point must fall on a cell with mask=1 (boundary) or mask=3 (active).

**Remedy**: Verify bnd point coordinates fall on active mask cells (mask > 0). Convert to grid indices: `i = (x - x0) / dx, j = (y - y0) / dy`. Check mask value at those indices.

---

### dt_013 — Discharge source placed on high ground, not in channel

**Symptom**: Discharge source creates artificial pond at a single point; no downstream flow.

**Diagnosis**: SFINCS adds water at discharge source points (sfincs.src). If the point is on a topographic high, water pools locally instead of flowing downstream. The source point must be placed in the river channel (topographic low).

**Remedy**: Place discharge source at a topographic low (river channel). Check DEM elevation at source point. If wrong, move to nearest low point.

---

### dt_014 — Double flood volume from both precipitation and VIC runoff

**Symptom**: Double flood volume — both precipitation and VIC runoff applied in SFINCS domain.

**Diagnosis**: When SFINCS receives gridded precipitation AND VIC surface runoff as discharge sources, the rainfall is counted twice: once by VIC (producing runoff that enters SFINCS via CaMa-Flood boundary) and once by SFINCS itself (direct rainfall-runoff). The SFINCS domain must be excluded from VIC, or SFINCS must not have rainfall.

**Remedy**: Choose ONE approach: (a) SFINCS with rainfall + CaMa river BC only, or (b) SFINCS with VIC runoff sources, no rainfall. Do NOT combine both.

---

### dt_015 — CaMa-Flood boundary flows in wrong direction

**Symptom**: CaMa-Flood boundary flows in wrong direction; flooding appears on wrong side.

**Diagnosis**: CaMa-Flood outflw can be positive (downstream) or negative (backwater effect). If negative discharge is used as SFINCS inflow, water is removed instead of added. Also, using water level BC (sfcelv) at a river entry point may cause reverse flow if the SFINCS domain elevation is higher than the BC water level.

**Remedy**: Use discharge BC (sfincs.src + sfincs.dis) for river inflow. Use water level BC (sfincs.bnd + sfincs.bzs) for coastal/downstream boundaries. Verify discharge values are positive for inflow.

---

### dt_016 — Step changes in water level from daily CaMa-Flood output

**Symptom**: Artificial step changes in water level at SFINCS boundary every 24 hours.

**Diagnosis**: CaMa-Flood typically outputs daily mean discharge/water level. SFINCS operates at seconds-to-minutes timesteps. Linear interpolation between daily values creates 24-hour ramps that do not represent actual flood dynamics. For rapid flood events (flash floods), this temporal mismatch can significantly affect results.

**Remedy**: Use sub-daily CaMa-Flood output if available. Otherwise, acknowledge temporal smoothing. For flash flood applications, daily BC is insufficient.

---

### dt_017 — SFINCS reads from CWD only; binary executed from wrong directory

**Symptom**: SFINCS exits immediately with `Cannot open file` error.

**Diagnosis**: SFINCS has NO command-line arguments. It reads sfincs.inp from the current working directory. If the binary is called from a different directory than where sfincs.inp resides, it will fail to find any input files.

**Remedy**: `cd` to the directory containing sfincs.inp before running the binary. `run_sfincs.py` handles this automatically via cwd parameter.

---

### dt_018 — Output format not set; default may be binary instead of NetCDF

**Symptom**: Output file empty or missing after successful run.

**Diagnosis**: If `outputformat` is not specified in sfincs.inp, SFINCS may default to binary output instead of NetCDF. The post-processing tools expect NetCDF (sfincs_map.nc).

**Remedy**: Add `outputformat = net` to sfincs.inp. `generate_sfincs_inp.py` always includes this.

---

### dt_019 — Mask file has no active cells

**Symptom**: Model runs to completion but output is all zeros.

**Diagnosis**: If sfincs.msk contains only zeros, SFINCS has no cells to compute. The model may still run without error but produce empty output. This can happen if the shapefile used for masking has wrong CRS or doesn't overlap with the computational grid.

**Remedy**: Check sfincs.msk has active cells (values > 0). Verify shapefile CRS matches grid CRS. `build_sfincs_topobathy.py` checks active cell count > 0.

---

### dt_020 — Manning's n too low (< 0.01)

**Symptom**: Water flows too fast; CFL instability with reasonable dt. NaN in output.

**Diagnosis**: Manning's n controls flow resistance. Values below 0.01 are physically unrealistic for any surface and can cause CFL violations even with small dt. Minimum realistic values: 0.02 (smooth water), 0.025 (concrete).

**Remedy**: Set minimum Manning's n to 0.02. Check LULC-to-Manning lookup table. `build_sfincs_roughness.py` enforces minimum n=0.015.

---

### dt_v001 — sfincs.ind binary format wrong (reads as 1 active cell)

**Symptom**: SFINCS reads sfincs.ind and reports `Number of active z points: 1` despite thousands of active cells in mask.

**Diagnosis**: sfincs.ind written as full 2D grid of sequential int32 indices instead of the required binary format: [n_active int32] [flat_indices int32 1-based]. The first int32 value (which is 1) is interpreted as n_active=1, so only 1 cell is active. This is the MOST DANGEROUS trap — the model reads silently and produces a nearly-empty domain.

**Remedy**: Write sfincs.ind as: header (n_active as int32) + body (1-based flat indices of active cells as int32 array). Verify: first 4 bytes of sfincs.ind should equal n_active when read as int32. `build_sfincs_topobathy.py` (fixed) writes correct binary format.

---

### dt_v002 — VIC forcing column 0 is temperature, not precipitation

**Symptom**: `prepare_sfincs_rainfall.py` produces negative "precipitation" values when reading VIC forcing files.

**Diagnosis**: VIC forcing ASCII files have 7 columns: TEMP(0), PREC(1), PRESSURE(2), SW(3), LW(4), VP(5), WIND(6). The original code read `data[:, 0]` (temperature, can be negative in winter) instead of `data[:, 1]` (precipitation).

**Remedy**: Change `data[:, 0]` to `data[:, 1]` in the vic_ascii branch. Check output values are non-negative. `prepare_sfincs_rainfall.py` (fixed) reads column 1 and validates precip >= 0.

---

### dt_v003 — Multi-year VIC forcing time offset not computed

**Symptom**: SFINCS rainfall forcing shows wrong season — e.g., winter precipitation for a summer flood event.

**Diagnosis**: VIC forcing files contain the entire simulation period (e.g., 2000-2010, ~80,000+ 3-hourly timesteps). When extracting a sub-period (e.g., Aug 2008), the tool must compute the byte offset from VIC simulation start to the target start_date. The original code reads the whole file but takes only the first n_times entries without offset, so for start_date=2008-08-01 it reads Jan 2000 data instead.

**Remedy**: Compute day offset from VIC simulation start to target start_date, convert to timestep offset, then slice: `data[ts_start:ts_end, 1]`. `prepare_sfincs_rainfall.py` (fixed) computes time offset from VIC start year.

---

### dt_v004 — netprecipfile silently fails; SFINCS runs with zero precipitation

**Symptom**: SFINCS log shows `Precipitation: no` despite netprecipfile being specified in sfincs.inp.

**Diagnosis**: SFINCS netprecipfile keyword requires specific NetCDF variable naming and coordinate conventions that are version-dependent. When netprecipfile fails, SFINCS silently disables precipitation — it does NOT crash, just runs dry.

**Remedy**: Use ASCII precipitation format with `precipfile` keyword instead of NetCDF `netprecipfile`. Generate ASCII sfincs.precip with format: `time_seconds precip_mmhr` (one line per timestep). `prepare_sfincs_rainfall.py` (fixed) produces ASCII format by default.

---

### dt_v005 — Inland domain drains instantly via mask=2 outflow at sea level

**Symptom**: Zero water depth across entire domain despite correct active cells and correct precipitation — all h=0, hmax=0.

**Diagnosis**: Mask outflow boundary (mask=2) defaults to water level 0.0m (sea level). For inland terrain at 143m+ elevation, this creates a huge hydraulic gradient that instantly drains all water. Rainfall is instantly drained and never accumulates. Completely silent failure.

**Remedy**: For inland/mountainous domains, use mask=1 (closed boundary) instead of mask=2 (outflow at sea level). Only use mask=2 for coastal domains or with explicit bzs water levels. Only set mask=2 at the lowest-elevation downstream boundary cells. `build_sfincs_topobathy.py` (fixed) auto-detects inland vs coastal based on min_elevation.

---

### dt_v006 — SIGABRT after successful simulation (gfortran finalization bug)

**Symptom**: SFINCS exits with code -6 (SIGABRT) after printing `Simulation finished` — output is valid but exit code suggests failure.

**Diagnosis**: gfortran 13.3 runtime finalization crashes during cleanup after successful simulation. Likely a NetCDF/HDF5 library deallocation race condition. The simulation output (sfincs_map.nc, sfincs_his.nc) is complete and valid.

**Remedy**: Check sfincs.log for `Simulation finished` AND verify sfincs_map.nc exists. If both true, treat as success regardless of exit code. `run_sfincs.py` (fixed) uses two-stage success detection.

---

### dt_v007 — zsmax (water surface elevation) used instead of hmax (water depth)

**Symptom**: `extract_sfincs_results` reports max flood depth 310m — physically impossible for a 6.99m actual flood.

**Diagnosis**: SFINCS output variable `zsmax` is water surface elevation (bed_level + water_depth), not water depth. For terrain at 310m elevation, zsmax=310m even with only 0.05m of water. The extract tool prioritized zsmax over hmax in its search order.

**Remedy**: Change variable priority to `['hmax', 'h', ...]` in `extract_sfincs_results.py`. hmax should have values in physically reasonable range (0-20m for most floods).

---

### dt_v008 — precipfile keyword mismatch (ASCII file with netprecipfile keyword)

**Symptom**: SFINCS runs without precipitation despite ASCII precip file existing — log shows `Precipitation: no`.

**Diagnosis**: `generate_sfincs_inp.py` wrote `netprecipfile = sfincs.precip` but the file is in ASCII format. SFINCS `netprecipfile` expects NetCDF, `precipfile` expects ASCII. SFINCS fails to parse ASCII as NetCDF and silently falls back to no precipitation.

**Remedy**: Use `precipfile` keyword (ASCII) instead of `netprecipfile` (NetCDF). `generate_sfincs_inp.py` (fixed) now writes `precipfile` for ASCII format.

---

### dt_v009 — Interior cells set to mask=3 (water level BC) instead of mask=1 (active)

**Symptom**: SFINCS runs but produces zero flood depth despite rainfall input.

**Diagnosis**: `build_sfincs_topobathy.py` used mask value 3 for active cells. SFINCS convention: 0=inactive, 1=active (flow computed), 2=outflow boundary, 3=water level BC (prescribed). With mask=3, SFINCS expects prescribed water levels, not rainfall-driven computation. Found 2026-04-11 Wangjiaba test: 80K cells with mask=3, zero flooding despite 10mm/hr rain.

**Remedy**: Set interior cells to mask=1, edge cells to mask=2. Check: `np.unique(msk)` should show mostly 1 (active) and some 2 (outflow). `build_sfincs_topobathy.py` (fixed 2026-04-11).

---

### dt_v010 — CMFD precip treated as mm/3hr but actual unit is kg/m2/s

**Symptom**: Precipitation near zero (max < 0.01 mm/hr) despite monsoon conditions.

**Diagnosis**: CMFD NetCDF attribute says kg/m2/s. Tool divided by 3 (assuming mm/3hr). Correct: multiply by 3600 for mm/hr. This is the #1 CMFD unit trap (PREFLIGHT.md).

**Remedy**: CMFD: multiply by 3600 (kg/m2/s to mm/hr). MSWX: divide by 3 (mm/3hr to mm/hr). `prepare_sfincs_rainfall.py` (fixed 2026-04-11).

---

### dt_v011 — Rainfall tool reads all CMFD files instead of requested period

**Symptom**: Rainfall tool hangs or takes hours — reading all CMFD files.

**Diagnosis**: CMFD directory has hundreds of monthly files. Tool globbed *.nc without filtering by YYYYMM. Each file is 3-9 GB. Fixed: extract YYYYMM from filename, only read files within start_date to end_date range.

**Remedy**: Filter glob results by YYYYMM matching start/end period. `prepare_sfincs_rainfall.py` (fixed 2026-04-11).

---

### dt_v012 — Precipitation written as NetCDF but referenced as precipfile (ASCII)

**Symptom**: SFINCS segfaults when reading precipitation file.

**Diagnosis**: SFINCS has two modes: `precipfile` (ASCII) and `netprecipfile` (NetCDF). Tool wrote NetCDF to sfincs.precip but sfincs.inp used `precipfile` keyword. SFINCS tried to read binary NetCDF as ASCII text, causing segfault.

**Remedy**: Write ASCII format: one line per timestep, `time_seconds precip_mmhr`. `prepare_sfincs_rainfall.py` (fixed 2026-04-11).

---

### dt_v013 — CaMa-Flood boundary has negative time values

**Symptom**: CaMa-Flood boundary has negative time values, SFINCS ignores them.

**Diagnosis**: `cama_to_sfincs_boundary.py` read all CaMa output years (e.g., 2000-2005) but tref was set to the requested start date (2003-07-01). Times from 2000-2003 became negative. SFINCS ignores negative-time entries silently.

**Remedy**: Filter CaMa data to start_date:end_date before writing sfincs.dis. `cama_to_sfincs_boundary.py` (fixed 2026-04-11).

---

### dt_v014 — sfincs.inp missing forcing file references despite files existing

**Symptom**: sfincs.inp missing srcfile/disfile/precipfile despite files existing in run directory.

**Diagnosis**: `generate_sfincs_inp.py` checks file existence in CWD only, not output_dir. Files exist in output_dir but tool doesn't find them, so sfincs.inp omits the references. SFINCS runs but with no forcing — zero flood depth.

**Remedy**: Check both CWD and output_dir for file existence. `generate_sfincs_inp.py` (fixed 2026-04-11).
