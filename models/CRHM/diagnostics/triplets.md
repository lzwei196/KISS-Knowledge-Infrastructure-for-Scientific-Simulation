# CRHM — Diagnostic Triplets

Structured error knowledge: symptom → diagnosis → remedy.
Consult this file FIRST when CRHM misbehaves.

---

### dt_001 — Specific humidity passed as relative humidity

**Symptom**: SWE accumulates indefinitely, never melting completely in summer. Sublimation is near zero. ET is unrealistically low. No error message.

**Diagnosis**: VIC forcing provides specific humidity (0.001–0.02 kg/kg). CRHM expects relative humidity (0–100%). If specific humidity is written directly to the .obs file, CRHM interprets 0.005 as 0.005% RH — essentially bone-dry atmosphere. All sublimation and evaporation go to zero. Snow accumulates without limit. The simulation completes without error, making this extremely difficult to detect.

**Remedy**: Convert specific humidity to relative humidity using Tetens formula: `RH = (q*P / (0.622*es)) * 100`. Check max RH in .obs file — if max < 1.0, units are wrong. `convert_vic_to_obs.py` handles conversion automatically.

---

### dt_002 — Precipitation rate vs accumulation mismatch

**Symptom**: Simulated discharge peaks are 3–8x too high. Flooding occurs in every month, not just spring melt. Annual water balance shows more output water than input precipitation.

**Diagnosis**: VIC forcing provides precipitation per timestep (e.g., mm per 3 hours). CRHM expects precipitation rate in mm/day. If 3-hourly accumulation is passed directly, CRHM receives 8 timesteps per day, each interpreted as mm/d, effectively multiplying daily precipitation by 8.

**Remedy**: If CRHM reads sub-daily, pass mm/timestep. If CRHM reads daily, SUM the sub-daily values. The conversion depends on CRHM's own timestep setting. Verify daily total precipitation matches known climatology for the basin.

---

### dt_003 — .obs file header format incorrect

**Symptom**: CRHM crashes at startup with error about observation file format — variable count mismatch or invalid header.

**Diagnosis**: CRHM .obs header must have exact format: variable name, space, column count (integer), space, unit in parentheses. Example: `t 1 (C)`. Common mistakes: missing column count, using tab instead of space, unit without parentheses, or variable name with spaces. Data columns (after `YYYY M D H 0`) must equal the sum of all N values.

**Remedy**: Each variable line: `varname N (unit)`. Computed variables: `$varname formula (unit) description`. Use `convert_vic_to_obs.py` to generate correctly formatted headers.

---

### dt_004 — Module chain order incorrect

**Symptom**: CRHM crashes during initialization with error about unresolved variable reference — `declgetvar...not found`.

**Diagnosis**: CRHM modules use `declgetvar()` to retrieve variables produced by earlier modules via `declvar()`. If module A calls `declgetvar("SWE")` but module B (which provides SWE) appears AFTER module A in the chain, the variable doesn't exist yet. The fix is always to reorder the chain, not to modify the modules.

**Remedy**: Reorder module chain so producers come before consumers. Standard order: basin → global → obs → radiation → canopy → snow → infiltration → soil → routing. `select_modules.py` validates dependency chain automatically.

---

### dt_005 — Wrong number of parameter values for nhru

**Symptom**: CRHM crashes or produces garbage output. Parameter values appear to be read from wrong locations in the .prj file. Some HRUs have physically impossible parameter values.

**Diagnosis**: Per-HRU parameters must have exactly nhru values. If nhru=10 but only 8 values are provided, CRHM reads the next 2 values from whatever follows in the file — which may be the next parameter's declaration line or range specification. This shifts all subsequent parameter reads, cascading corruption through the entire parameter set.

**Remedy**: Count nhru in Dimensions section. For each parameter, count values (space-separated across lines). Values must equal nhru (per-HRU) or 1 (global). Use `create_prj_file.py` which auto-generates correct value counts.

---

### dt_006 — Parameter value silently clamped to declared range

**Symptom**: Simulation runs without error but results don't change when you modify a parameter value. You set fetch=50000 but results are identical to fetch=10000.

**Diagnosis**: CRHM parameters have declared ranges in angle brackets: `<min to max>`. If a value exceeds the max, CRHM silently clamps it to max. The .prj file shows 50000 but the model uses 10000. No warning is produced. This makes parameter sensitivity analysis unreliable.

**Remedy**: Run `validate_prj.py` — it checks all values against ranges. For any range violation, adjust the value to be within `<min to max>`. If the range is too narrow for your basin, this may indicate the wrong module. Never assume CRHM will warn about bad values.

---

### dt_007 — Observation file path resolved relative to CWD, not .prj

**Symptom**: CRHM crashes at startup with error about observation file not found — `cannot open...obs`.

**Diagnosis**: CRHM resolves .obs file paths relative to the current working directory (CWD) when crhm is invoked, NOT relative to the .prj file's directory. If the .prj has `obs/basin.obs` and you run CRHM from `/home/user`, it looks for `/home/user/obs/basin.obs` even if the .prj is in `/data/project/`.

**Remedy**: Use absolute paths in .prj Observations section, or run CRHM with `--obs_file_directory` pointing to the obs directory, or `cd` to the directory containing the .obs file before running. `create_prj_file.py` generates absolute paths by default.

---

### dt_008 — Module runtime error from invalid data or state

**Symptom**: CRHM exits with non-zero return code. Error message on stderr mentions a specific module name and variable — `STOP`, `abort`, or `segfault`.

**Diagnosis**: Common causes: (1) observation data has NaN or extreme outlier values causing numerical overflow, (2) parameter combination leads to division by zero (e.g., zero soil depth), (3) snow depth goes negative due to excessive sublimation, (4) timestep too large for the module's numerical stability.

**Remedy**: Run `validate_obs_file.py` to check for extreme values. Check for NaN, -9999, or other missing value indicators in .obs. Verify no parameter is zero that shouldn't be (`soil_Depth`, `route_L`). Try running with a shorter period to isolate when the crash occurs.

---

### dt_009 — Unit mismatch between VIC and CRHM output variables

**Symptom**: Merged CRHM+VIC comparison shows wildly different magnitudes for the same variable (e.g., VIC SWE is 50mm while CRHM SWE is 5000mm). Water balance doesn't close.

**Diagnosis**: VIC reports some variables in different units than CRHM: VIC runoff in mm/day vs CRHM runoff possibly mm/timestep; VIC ET in mm/day vs CRHM ET_act possibly mm/timestep. Merging without unit alignment produces nonsensical comparisons. This is the coupling-specific instance of the universal unit trap (37% of all silent errors across 15 models).

**Remedy**: Check CRHM output units (row 2 of STD output) and VIC output units (from `global_param` OUTVAR definitions). Convert all variables to common units before merging — fluxes in mm/day, states in mm. Build a unit conversion table before any coupling attempt.

---

### dt_010 — Double-counting hydrological processes between VIC and CRHM

**Symptom**: Combined water balance shows more output (ET + Q) than input (P). Annual runoff ratio exceeds 1.0. Results appear physically impossible but no error is raised.

**Diagnosis**: Both VIC and CRHM compute snowmelt, sublimation, ET, and soil moisture. If both models' snowmelt values are added together, the total melt is 2x the actual value. Similarly for ET and runoff. The process ownership table was not defined or not followed during the merge step.

**Remedy**: Create a process ownership table — each process assigned to exactly one model. When merging, use ONLY the owner's value for each process. For snow processes: typically CRHM (better cold regions physics). For routing: always VIC (grid-based Lohmann/CaMa-Flood). Validate: P − ET − Q − dS ≈ 0 over multiple years.

---

### dt_011 — Gap-filled winter observation data with artificial constant values

**Symptom**: Winter SWE is unrealistically smooth or constant. Temperature, wind, and precipitation show suspiciously repetitive patterns during December–March. Simulated spring melt timing is wrong.

**Diagnosis**: Cold-region weather stations frequently fail during extreme cold (−40°C), blizzards, or rime icing of instruments. Automated gap filling often inserts constant values (last known reading) or climatological means during these outages. CRHM reads whatever is in the .obs file without checking. Constant temperature during a blizzard misses the cold snap that would freeze the soil surface, affecting frozen soil infiltration and spring runoff timing.

**Remedy**: Check for constant-value runs > 3 days (suspicious in winter). Compare against nearby stations or reanalysis for gap periods. Use ERA5 or MERRA-2 for winter gap filling (better than constant fill). Use reanalysis-based forcing (CMFD, MSWX, ERA5) instead of station data for cold regions.

---

### dt_012 — CRS mismatch between DEM and basin shapefile

**Symptom**: Total HRU area is much larger or smaller than expected basin area. HRU elevations are all identical or don't match known basin relief.

**Diagnosis**: If the DEM is in UTM (meters) and the shapefile is in WGS84 (degrees), the spatial clip operation may return incorrect areas. A 100 km² basin might compute as 0.01 km² (degrees-squared) or 10¹⁰ m² (coordinates treated as meters when they're degrees). The HRU creation completes without error but all areas are wrong.

**Remedy**: Check DEM CRS: `gdalinfo dem.tif | grep 'AUTHORITY'`. Check shapefile CRS: `ogrinfo basin.shp -al | grep 'AUTHORITY'`. If different, reproject: `gdalwarp -t_srs EPSG:4326 dem.tif dem_wgs84.tif`. Re-run `create_hru_config.py`. Always assert CRS equality before spatial operations.

---

### dt_013 — .prj section delimiter is not exactly 6 hashes

**Symptom**: CRHM fails to parse .prj file. Error about missing section or unexpected content where a section header was expected.

**Diagnosis**: CRHM .prj format uses exactly `######` (6 hashes) on a standalone line as section delimiters. Using 5 hashes, 7 hashes, or adding spaces after the hashes causes CRHM to treat the delimiter as content rather than a section boundary. The section name must appear on the NEXT line (not same line as hashes), followed by another `######`.

**Remedy**: Search .prj for lines with `#` characters. Replace any that are not exactly `######` (6 characters, no trailing spaces). Ensure section name is on the line between two `######` lines. `create_prj_file.py` generates correct delimiters.

---

### dt_014 — No output variables specified in Display_Variable

**Symptom**: CRHM exits with code 0 (success) but the output file is empty or contains only header lines with no data.

**Diagnosis**: If the Display_Variable section is empty, CRHM runs the entire simulation but writes nothing to the output file. The exit code is still 0 because no error occurred — the model simply had nothing to display. This wastes the entire computation time and produces no usable results.

**Remedy**: Find the `Display_Variable` section in .prj and add output variables: SWE, snowmelt, runoff, soil_moist, WS_outflow. Format: `variable_name HRU_indices` (e.g., `SWE 1 2 3`). `create_prj_file.py` always adds default output variables.

---

### dt_015 — Temporal resolution mismatch between VIC and CRHM outputs

**Symptom**: Merged CRHM+VIC dataset has many NaN values. Time series plots show gaps. Correlation metrics between models return NaN.

**Diagnosis**: VIC may output daily (1 row/day) while CRHM outputs hourly or 3-hourly (8–24 rows/day). A naive join on datetime produces NaN for all CRHM sub-daily rows that have no VIC match. The merged dataset appears mostly empty.

**Remedy**: Resample both datasets to common daily resolution before merging — sum for fluxes, mean for state variables. `merge_crhm_vic.py` auto-detects and resamples sub-daily data.

---

### dt_016 — Module chain inappropriate for basin landscape type

**Symptom**: Simulated SWE distribution across HRUs is physically unrealistic. Wind-sheltered forest HRUs show more blowing snow transport than exposed prairie HRUs. Or mountain basin shows no radiation difference between north and south aspects.

**Diagnosis**: Using PBSM (prairie blowing snow) in dense forest produces unrealistic snow transport because forest wind speeds are too low for transport but the module doesn't check vegetation density. Using SnobalCRHM without Slope_Qsi in mountainous terrain gives identical radiation to all aspects.

**Remedy**: Prairie: use PBSM + PrairieInfil. Forest: use CRHMCanopy + SnobalCRHM (no PBSM). Mountain: use Slope_Qsi + SnobalCRHM. Review `select_modules.py` landscape chain recommendations.

---

### dt_017 — Boost library version mismatch or missing at runtime

**Symptom**: CRHM executable fails to run with error about missing shared library — `libboost...not found` or `GLIBCXX` errors.

**Diagnosis**: CRHM requires Boost 1.75.0. If built with dynamic linking, the Boost shared libraries must be on `LD_LIBRARY_PATH` at runtime. If the system has a different Boost version (e.g., 1.83), the executable may find the wrong version, causing symbol resolution errors. The CMake build defaults to the local Boost in `src/libs/` which should be statically linked, but this can break if CMake finds the system Boost first.

**Remedy**: Check linkage: `ldd build/crhm | grep boost`. If dynamic: `export LD_LIBRARY_PATH=/path/to/boost_1_75_0/lib:$LD_LIBRARY_PATH`. If wrong version: rebuild with `-DBOOST_ROOT=/path/to/boost_1_75_0`. Preferred: rebuild with static Boost linking. Use `install_crhm.sh` which downloads correct Boost version.

---

### dt_018 — Observation timestep doesn't match .prj configuration

**Symptom**: CRHM reads observation data but produces different results than expected. Some timesteps appear to be skipped or doubled. Output has wrong number of rows for the simulation period.

**Diagnosis**: CRHM infers the observation timestep from the first two data rows in the .obs file. If the .obs file is 3-hourly but the .prj expects hourly, CRHM may interpolate or skip rows. If the .obs is daily but modules expect sub-daily data, intermediate timesteps are filled with the previous value (zero-order hold), which is physically wrong for temperature and radiation diurnal cycles.

**Remedy**: Check .obs timestep — look at hour values in first data rows. Hourly: hours 1,2,3,...24. 3-hourly: hours 3,6,9,...24. Daily: hour 1 only. Energy balance modules (SnobalCRHM) work best with hourly data. Match .obs temporal resolution to the finest module requirement.

---

### dt_crhm_012 — MSWX 3-hourly precipitation not aggregated to daily

**Symptom**: Annual precipitation 3,672–6,205 mm in .obs file vs real Saskatchewan 350–400 mm. Discharge PBIAS = +696%.

**Diagnosis**: MSWX 3-hourly precipitation values written as daily totals. Each 3hr value treated as full daily mm, inflating precip by 8x.

**Remedy**: Sum 8 MSWX timesteps to get daily total: `precip_daily = sum(precip_3hr[0:8])`. Forcing converter must aggregate 3-hourly to daily for CRHM .obs format.

---

### dt_crhm_013 — Wrong module chain template for prairie basin

**Symptom**: Spring snowmelt bypasses frozen-soil infiltration. ebsm and PBSM conflict over SWE variable. PrairieInfil missing from module chain.

**Diagnosis**: Module chain uses Belly River mountain template instead of prairie chain. PrairieInfil absent, ebsm conflicts with PBSM.

**Remedy**: Use prairie chain: basin → global → obs → PBSM → PrairieInfil → Soil → Netroute. Remove ebsm. `select_modules.py` must detect prairie vs mountain basins and use appropriate chain.

---

### dt_crhm_014 — No temperature lapse rate applied across elevation range

**Symptom**: SWE peaks at 6,831 mm (45–68x normal 50–150 mm). High-elevation HRUs (3,510m) receive lowland temperature, accumulating unrealistic snowpack.

**Diagnosis**: No temperature lapse rate applied to MSWX forcing. Single grid cell temperature used for all HRUs regardless of elevation (0–3,510m range).

**Remedy**: Apply −6.5°C/km lapse rate to T based on HRU elevation. Apply orographic precip factor 1.5–2.0x per 1000m. Forcing prep must apply lapse rate when basin has >500m elevation range.

---

### dt_crhm_015 — Groundwater lag parameter too high for prairie basin

**Symptom**: gwLag=700 days causes 23-month groundwater delay. Near-zero winter baseflow vs observed ~200 m³/s in January. All GW release shifted to following year summer.

**Diagnosis**: Default gwLag=700 days too high for large prairie basin with alluvial aquifer. South Saskatchewan has quick groundwater response (~30–90 days), not slow deep bedrock (700 days).

**Remedy**: Set gwLag to 30–90 days for prairie alluvial basins. Use 200–400 days for mountain bedrock. `create_prj_file.py` should set gwLag based on basin geology.

---

### dt_019 — .prj uses Macro group format instead of flat module format

**Symptom**: CRHM crashes with `Unknown Module: Basin_Group` or SIGSEGV (exit −11).

**Diagnosis**: `create_prj_file.py` generated modules as `Basin_Group Macro` with `+module` lines. This is a GUI-only format. The CLI binary (crhmcode) requires flat format where each module is on its own line as `module_name CRHM date`. Discovered by comparing with working Belly River .prj (docs-first approach).

**Remedy**: Use flat module format: `basin CRHM 02/24/12` (no Basin_Group, no +prefix). `create_prj_file.py` now uses flat format by default (fixed 2026-04-11). Verified on Ghost River.

---

### dt_020 — .obs file has 2 description lines instead of 1

**Symptom**: CRHM crashes with `Observation: u, not in Data file` despite u being in header.

**Diagnosis**: CRHM .obs format expects EXACTLY 1 description line, then variable declarations. The forcing converter wrote 2 description lines. CRHM parsed the second description line as a variable declaration, shifting all subsequent variable names. When it looked for `u` (wind), it found a shifted/wrong variable name. The resulting SIGSEGV is from accessing invalid data. Discovered by comparing with working Belly River .obs.

**Remedy**: Ensure .obs has exactly 1 description line before variable declarations. Check line 2 of .obs — it must be a variable declaration (e.g., `t 1`), not text. `convert_forcing.py` now writes single description line (fixed 2026-04-11). Verified on Ghost River.
