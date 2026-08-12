# RZWQM2 Workflow — End-to-End Orchestration Guide

**For AI agents operating RZWQM2 autonomously using this knowledge infrastructure.**

This document describes the exact data flow, file dependencies, and per-site configuration steps needed to run RZWQM2 for any location. It was validated through end-to-end testing on 2026-03-16.

---

## For Multi-Site / Batch Runs

Use `tools/s10_mass_generation/mass_project_generator.py` — the single entry point:

```bash
python mass_project_generator.py sites.csv /path/to/project /path/to/template \
    hwsd cmfd /mnt/disk1/.../Data_forcing_03hr_010deg
```

**Do NOT write custom setup scripts.** The mass generator handles all 12 pipeline steps per site, incorporating all validated bug fixes. It calls every tool in the correct order with correct parameters.

---

## What the User Provides

At minimum:
- **lat, lon** — site coordinates in decimal degrees
- **start_date, end_date** — simulation period (YYYY-MM-DD)
- **crop_name** — crop to simulate (e.g., "maize", "soybean", "wheat")

Optional:
- **soil_source** — "soilgrids" (default), "hwsd", "vic_global"
- **forcing_source** — "mswx" (default), "cmfd", "csv"
- **forcing_path** — path to forcing data directory
- **cultivar_id** — specific DSSAT cultivar (default: auto-select)

---

## Project Directory Structure

Every RZWQM2 simulation requires this layout. The binary runs from the scenario directory as CWD — all paths are relative to this directory.

```
{project_root}/
  {station_id}/              <- scenario directory (binary runs here)
    main_ryzen_patched       <- RZWQM2 binary (Linux) — MUST be here
    ipnames.dat              <- master control: 8 file paths + dates
    cntrl.dat                <- output control (generic, no changes needed)
    rzwqm.dat                <- soil/site/management config (updated per site)
    rzinit.dat               <- initial conditions (updated per site)
    plgen.dat                <- generic plant growth (0 = use DSSAT)
    expdata.dat              <- observation data (generic, no changes needed)
    RZCropSel.rzq            <- crop/cultivar selection (updated per site)
    MZDSSAT.RZX              <- DSSAT maize config (paths updated per project)
    SBDSSAT.RZX              <- DSSAT soybean config
    WHDSSAT.RZX              <- DSSAT wheat config
    DSSAT/                   <- DSSAT crop database files
      MZCER040.CUL, .ECO, .SPE
      SBGRO040.CUL, .ECO, .SPE
      ...
  Meteorology/
    {station_id}.met         <- daily weather data (36-line header + data)
    {station_id}.brk         <- breakpoint rainfall (20-line header + events)
    {station_id}.sno         <- snow parameters (generic, works for all sites)
  Analysis/
    {station_id}.ana         <- model output (created by RZWQM2)
```

---

## Step-by-Step Pipeline

### Step 0: Create Project from Template

**Action**: Copy the **canonical template** directory, then modify only what changes.

**Canonical template**: `/home/server/RZWQM2/RZWQM2/template_bengbu/`

This is a clean, validated Bengbu wheat project stripped of output files. It contains all 8 required input files, DSSAT crop databases (maize/wheat/soybean), and the pre-patched Linux binary.

**Why template-first**: RZWQM2 has dozens of config sections with exact Fortran fixed-width formatting. Generating from scratch is **not supported** — even one wrong column alignment causes silent errors or segfaults. The template approach is how RZWQM2 is used in practice, both by humans and agents.

**What gets copied**: Everything — binary, config files, DSSAT database, RZX files, support files. The `initialize_scenario.py` tool also cleans old output files (.OUT, .PLT, .ana, .log) automatically.

**Critical**: The RZWQM2 binary must be in the scenario directory. The template already contains it.

**Tool**: `initialize_scenario.py` (preferred) or direct `shutil.copytree`

```bash
# Using the tool:
python tools/s7_scenario_assembly/initialize_scenario.py \
    /path/to/new_project  bengbu_wheat  <new_site_name> \
    <start_date>  <end_date>

# Or direct copy + manual path update:
shutil.copytree(
    "/home/server/RZWQM2/RZWQM2/template_bengbu/bengbu_wheat",
    "/path/to/new_project/<new_site>"
)
```

**After copying**, proceed to Steps 1-7 to update site-specific parameters. The template values (Bengbu soil, Bengbu weather) will be overwritten by the pipeline tools.

---

### Step 1: Retrieve Soil Data (S0)

**Tool**: `tools/s0_global_data/soil_source_adapter.py`
**Input**: lat, lon, source ("soilgrids"), num_horizons (6 recommended for SoilGrids)
**Output**: JSON with horizon list — each horizon has: depth_cm, sand_pct, clay_pct, silt_pct, bulk_density_gcc, texture_class, ws, fc33, fc15, fc10, ksat_cm_hr, pore_size_dist, bubbling_pressure, wr, N2, C2

**Data sources**:
| Source | Coverage | Command |
|--------|----------|---------|
| `soilgrids` | Global (gaps in NE China) | No local data needed — API-based |
| `hwsd` | China (full coverage) | `tools/s0_global_data/hwsd_soil_adapter.py` — needs HWSD raster + .mdb + mdbtools |
| `vic_global` | Global 0.25deg | Needs `global_soil_param_new.txt` — NOT recommended (model-derived, not atlas) |

**HWSD data paths (this server)**:
- Raster: `/mnt/disk1/Hydrocraft_server/data/soil/HWSD_China_Geo.img`
- Database: `/media/server/hc_ssd/forcing/huaihe_raw/soil/HWSD.mdb`
- Requires: `mdbtools` system package

**SoilGrids standard depths**: 0-5cm, 5-15cm, 15-30cm, 30-60cm, 60-100cm, 100-200cm (6 layers)

**Data flows to**: S4 (soil properties), S5 (nodes), S6 (initial conditions)

---

### Step 2: Retrieve Forcing Data (S0)

**Tool**: `tools/s0_global_data/forcing_source_adapter.py`
**Input**: lat, lon, start_date, end_date, source ("mswx"), source_path, output_csv
**Output**: Daily CSV with columns: date, tmin, tmax, wind, radiation, epan, rh, par, rain

**MSWX data**:
- **Path**: `/mnt/disk3/msxw/` (7 subdirs: Tair, P, Pres, SWd, LWd, wind, spechum)
- **Layout**: `{var}/{prefix}_{YYYY}.nc` — yearly files, ~9GB each, global 0.1deg 3-hourly
- **Coverage**: 1979-2026
- **Performance**: Uses multiprocessing (6 parallel reads). ~4 min/year.
- **Units**: Tair in deg C, P in mm/3h (summed to daily mm), wind in m/s (converted to km/day), SWd in W/m2 (converted to MJ/m2/day)

**CRITICAL**: Always use `forcing_source_adapter.py` for weather data. Do NOT write custom conversion scripts or convert from VIC model output (flux files). VIC output causes severe precipitation underestimation (~10% of actual, dt_015).

**For multiple sites (batch)**: Call the tool once per site:
```bash
for each site (lat, lon):
    python forcing_source_adapter.py <lat> <lon> <start> <end> cmfd \
        /media/server/hc_ssd/forcing/Data_forcing_03hr_010deg \
        weather_csv/<site_id>_weather.csv
```
The tool handles all unit conversions (K→C, kg/m²/s→mm, W/m²→MJ/m²/day) and sets E-pan=0, PAR=0.

**Data flows to**: S2 (.met generation), S3 (.brk generation)

---

### Step 3: Select Crop (S0)

**Tool**: `tools/s0_global_data/crop_selector.py`
**Input**: crop_name, dssat_db_path
**Output**: JSON with dssat_prefix (e.g., "MZCER040"), default_cultivar_id, cultivar_count

**Data flows to**: S7 (RZCropSel.rzq update, RZX path update)

---

### Step 4: Write Site Properties (S1)

**Tool**: `tools/s1_site_config/write_site_properties.py`
**Input**: project_path, station_id, lat_rad, lon_rad, elevation, slope
**Modifies**: `{station_id}/rzwqm.dat` — grid_general_property section

**CRITICAL**: Latitude and longitude must be in **RADIANS**, not degrees.
```
lat_rad = lat_deg * pi / 180
lon_rad = lon_deg * pi / 180
```
Wrong units cause silent errors in ET and radiation calculations (dt_009).

---

### Step 5: Generate .met File (S2)

**Tool**: `tools/s2_met_prep/generate_met_file.py`
**Input**: input_csv (from Step 2), output_met_path, start_date, end_date
**Output**: `.met` file with 36-line header + daily data rows
**Columns**: Julian day, year, Tmin(C), Tmax(C), wind(km/day), radiation(MJ/m2/day), E-pan, RH(%), PAR, rain(mm)

**CRITICAL**: E-pan (column 7) and PAR (column 9) **must be 0**. When non-zero, RZWQM2 uses them directly instead of computing ET internally, causing incorrect water balance and crop death (dt_014). The tool hardcodes these to 0.

**Follow-up**: `tools/s2_met_prep/met_quality_check.py` — fixes Tmin>Tmax swaps and caps RH at 100%.

---

### Step 6: Generate .brk File (S3)

**Tool**: `tools/s3_brk_generation/create_breakpoint_file.py`
**Input**: project_path, station_id (reads from Meteorology/{station_id}.met)
**Output**: `.brk` file with 20-line header + rain events

**CRITICAL**: .brk uses **INCHES** for precipitation. The tool converts from .met mm automatically (divide by 25.4). If done manually, wrong units cause drainage 25x too high (dt_004).

---

### Step 7: Write Soil Properties (S4)

**Tool**: `tools/s4_soil_setup/write_soil_properties.py`
**Input**: project_path, station_id, soil_config_json (from Step 1)
**Modifies**: `{station_id}/rzwqm.dat` — 8 sections atomically:
1. Horizon depths
2. Node discretization
3. Physical properties (bulk density, particle density, sand/silt/clay)
4. Hydraulic properties (Brooks-Corey: pore_size_dist, ws, wr, bubbling_pressure, ksat, N2, C2, fc33, fc10, fc15)
5. Heat model properties
6. Micropore properties (texture-based defaults)
7. Macropore properties
8. Infiltration parameters

**CRITICAL**: All sections must have the same horizon count. Inconsistent counts cause dt_005 fatal error.

---

### Step 8: Node Discretization (S5)

**Tool**: `tools/s5_node_discretization/generate_nodes.py`
**Input**: project_path, station_id, horizon_depths (comma-separated cm values)
**Modifies**: `{station_id}/rzwqm.dat` — node discretization section

Note: S4 already does this via `insert_new_horizon_to_existing_dat_file()`. S5 can refine if needed.

---

### Step 9: Write Initial Conditions (S6)

**Tool**: `tools/s6_initial_conditions/write_initial_conditions.py`
**Input**: project_path, station_id, num_horizons
**Modifies**: `{station_id}/rzinit.dat` — 3 sections:
1. Water & temperature (tension gradient + temperature per horizon)
2. Chemistry (pH, CEC, organic carbon per horizon — placeholder values)
3. Nutrients (carbon/nitrogen pools per horizon — placeholder values)

---

### Step 10: Write Management Events (S6.5)

**Tool**: `tools/s6_management_write/write_management_events.py`
**Input**: project_path, station_id, management_config_json, simulation_years_json
**Modifies**: `{station_id}/rzwqm.dat` — planting, fertilizer, irrigation sections

**Multi-year**: The tool writes one planting event per year. `simulation_years` must be a list of all years (e.g., `[2015, 2016, 2017, 2018, 2019, 2020]`).

**Management config structure**:
```json
{
  "planting": {
    "planting_doy": 121,
    "harvest_doy": 274,
    "row_spacing_cm": 76.0,
    "depth_layer_index": 7,
    "density_seeds_per_ha": 72000
  },
  "fertilizer": {
    "applications": [{
      "timing": 1,
      "method": 2,
      "nh4_kg_ha": 85,
      "urea_kg_ha": 85
    }]
  },
  "irrigation": {"is_irrigated": false}
}
```

---

### Step 11: Scenario Assembly (S7)

Three tools, run in sequence:

**11a. Update IPNAMES paths + dates**:
**Tool**: `tools/s7_scenario_assembly/update_ipnames_paths.py`
**Input**: project_path, station_id, new_root, start_date, end_date
**Modifies**: `{station_id}/ipnames.dat` — 8 file paths + simulation dates (line 8)

The tool auto-detects file case on disk (rzwqm.dat vs RZWQM.dat) for Linux compatibility.

**11b. Update RZX paths**:
**Tool**: `tools/s7_scenario_assembly/update_rzx_paths.py`
**Input**: scenario_dir, dssat_db_path, project_path
**Modifies**: All .RZX files — DATABASE FILE LOCATIONS section

**CRITICAL**: RZX paths must be **relative** with **trailing slashes**. The Fortran binary does simple string concatenation (not path joining):
- Correct: `DSSAT/` + `MZCER040.CUL` = `DSSAT/MZCER040.CUL`
- Wrong: `DSSAT` + `MZCER040.CUL` = `DSSATMZCER040.CUL`

Always pass: `dssat_db_path="DSSAT"`, `project_path="."`

**11c. Update crop selection**:
**Tool**: `tools/s7_scenario_assembly/update_crop_selection.py`
**Input**: scenario_dir, crop_code, crop_name, cultivar_id, cultivar_desc
**Modifies**: `{station_id}/rzwqm.dat` (the real source) AND `{station_id}/RZCropSel.rzq` (GUI sync)

**CRITICAL**: The crop selection RZWQM2 actually reads is inside **rzwqm.dat** (~line 494), NOT RZCropSel.rzq. Crop codes are hardwired:
- `7000` = maize → uses MZDSSAT.RZX
- `7001` = soybean → uses SBDSSAT.RZX
- `7002` = wheat → uses WHDSSAT.RZX

The `crop_ref` in planting events maps to entry position (1→first entry, 2→second, 3→third).

**11d. Update cultivar from DSSAT China library**:
**Tool**: `tools/s7_scenario_assembly/update_cultivar.py`
**Input**: scenario_dir, crop, lat (for auto-select) OR cultivar_id (explicit)
**Modifies**: `{station_id}/DSSAT/MZCER040.CUL` — overwrites the active VAR# line with Chinese cultivar params

The tool reads from DSSAT's China cultivar library (`/home/server/DSSAT/Data/Genotype/China/`) and auto-selects by latitude:
- \> 40°N: NEC Spring cultivars (CN0017-19)
- 33-40°N: HHH Summer cultivars (CN0001-04, Zhengdan 958)
- < 33°N: SC Summer cultivar (CN0021)

**CRITICAL**: The tool overwrites the **existing** VAR# line (e.g., IB1068) in the .CUL file with the Chinese cultivar's parameters, keeping the original VAR# ID. This is because RZWQM2 matches cultivar by the 6-char ID in RZCropSel.rzq.

The `mass_project_generator` automatically calls this for every site using latitude-based selection.

**11e. RZX nitrogen must be ON**:
The `update_rzx_paths` tool now automatically enables nitrogen routines (ISWNIT=Y) in all RZX files. The Ohio template had nitrogen OFF in WHDSSAT.RZX, which silently limits crop growth.

---

### Step 12: Run Model (S8)

**Tool**: `tools/s8_execution/run_rzwqm2.py`
**Input**: scenario_dir, binary_path, timeout
**Output**: `.ana` file + many .OUT files in scenario directory

**CRITICAL**: The binary must be **in the scenario directory** and launched from there as CWD. All RZWQM2 file lookups are relative to CWD.

```python
binary_path = os.path.join(scenario_dir, "main_ryzen_patched")
os.chmod(binary_path, 0o755)
```

**Platform notes**:
- Linux: `main_ryzen_patched` (must have AVX2, must be patchelf'd — see dt_012)
- Windows: `RZWQMRelease.exe`

**Expected runtime**: ~1 minute per simulation year on modern hardware.

---

### Step 13: Parse Results (S9)

**Tool**: `tools/s9_result_parsing/parse_ana_output.py`
**Input**: project_path, station_id, variable_name
**Output**: CSV with datetime + variable value

**Available variables** (40+ mapped):
| Category | Variables |
|----------|-----------|
| Hydrology | stored_soil_water, precipitation, infiltration, actual_et, runoff, deep_seepage, tile_drainage |
| Crop | biomass_above, lai, grain_yield, growth_stage, root_depth, plant_height |
| Nitrogen | nitrogen_uptake, mineralization, denitrification, no3_leaching |
| Weather | tmin, tmax, tmean, radiation, rh |
| Snow | snow, snow_water_equiv, snow_melt |
| GHG | n2o_nitrification, n2o_denitrification |
| Phosphorus | drp_loss_tile, plant_p_uptake |

Also accepts `col_N` for any raw column (e.g., `col_42` for column 42).

**Layer output**: `tools/s9_result_parsing/parse_layer_output.py` — extracts depth-resolved data from LAYER.PLT (soil temperature, soil water content by node depth).

---

## Per-Site Configuration Checklist

When creating a new site, these files need updating (everything else stays as template):

| File | What changes | Tool |
|------|-------------|------|
| `rzwqm.dat` | Site properties (lat/lon/elev) | write_site_properties |
| `rzwqm.dat` | Soil (physical, hydraulic, heat, micro/macropore) | write_soil_properties |
| `rzwqm.dat` | Management (planting dates, fertilizer, irrigation) | write_management_events |
| `rzinit.dat` | Initial conditions (water, chemistry, nutrients) | write_initial_conditions |
| `ipnames.dat` | File paths + simulation dates | update_ipnames_paths |
| `*.RZX` | DSSAT database paths | update_rzx_paths |
| `rzwqm.dat` | Crop cultivar (the REAL source) | update_crop_selection |
| `RZCropSel.rzq` | Crop cultivar (GUI sync) | update_crop_selection |
| `Meteorology/*.met` | Daily weather data | generate_met_file |
| `Meteorology/*.brk` | Breakpoint rainfall | create_breakpoint_file |

**Files that stay as template** (generic, no changes needed):
- `cntrl.dat` — output control
- `plgen.dat` — generic plant growth (0 = DSSAT)
- `expdata.dat` — observation data for comparison
- `*.sno` — snow parameters (physical constants)
- `DSSAT/*` — crop model database
- `Gleams.dat`, `HERMES.dat`, `FORGMOW.DAT` — sub-model configs

---

## Critical Domain Knowledge

These cause silent failures if violated — no error message, just wrong results:

1. **Lat/lon in RADIANS** for rzwqm.dat. Degrees cause wrong ET/radiation (dt_009).
2. **BRK precipitation in INCHES**. .met uses mm. Divide by 25.4 (dt_004).
3. **Tile drainage output in CM**. Multiply by 10 for mm (dt_010).
4. **RZX paths relative with trailing slash**. Fortran does string concatenation, not path join.
5. **Binary runs from scenario CWD**. All paths resolve relative to where the binary is launched.
6. **Horizon count consistent everywhere**. Physical, hydraulic, heat, micropore, macropore in rzwqm.dat + water, chemistry, nutrients in rzinit.dat must all agree.
7. **Linux case sensitivity**. The RZWQM class uses `_resolve_case()` to handle both `rzwqm.dat` and `RZWQM.dat`. ipnames paths must match actual file case on disk (dt_013).
8. **fc10 < ws**. Field capacity at 1/10 bar must be less than saturated water content. If not, model refuses to start.
9. **E-pan and PAR must be 0** in .met file. Non-zero values override the model's internal ET calculation, causing silent crop failure (dt_014). The generate_met_file tool enforces this.
10. **Never use VIC flux output as RZWQM2 weather source**. VIC OUT_PREC/OUT_RAINF are model outputs with different units/timing than raw forcing. Always use CMFD or MSWX directly via forcing_source_adapter (dt_015).
10. **Crop selection is in rzwqm.dat**, not RZCropSel.rzq. Codes 7000=maize, 7001=soybean, 7002=wheat are hardwired. Always update rzwqm.dat when changing cultivar.
11. **Nitrogen must be ON** in all RZX files (ISWNIT=Y). Template WHDSSAT.RZX had it OFF, silently limiting wheat growth. The update_rzx_paths tool now auto-enables it.
12. **Crop densities vary by crop**: maize ~84,000, soybean ~519,000, wheat ~3,884,000 seeds/ha. Using the wrong density gives unrealistic results.

---

## Data Source Paths (this server)

| Data | Path | Notes |
|------|------|-------|
| MSWX forcing | `/mnt/disk3/msxw/` | 1979-2026, global 0.1deg, ~9GB/year/var |
| VIC global soil | `/home/server/桌面/yc/doc/soil/data/global_soil_param_new.txt` | NOT recommended for RZWQM2 |
| HydroCraft tools | `/mnt/disk1/Hydrocraft_server/` | Reference for MSWX reading patterns |
| RZWQM2 template | `linux/` directory in this repo | Working Ohio scenario |
| DSSAT database | `data/databases/DSSAT/` or `linux/DSSAT/` | 41 crop models |

---

## Diagnostic Reference

When something fails, check `diagnostics/triplets.yaml` (13 triplets). Key ones:

| ID | Symptom | Severity |
|----|---------|----------|
| dt_001 | Model crashes on startup (Windows paths on Linux) | Fatal |
| dt_004 | Drainage 25x too high (BRK in mm not inches) | Silent |
| dt_005 | Segfault (inconsistent horizon counts) | Fatal |
| dt_009 | Wrong ET (lat/lon in degrees not radians) | Silent |
| dt_012 | Binary won't start on Linux (interpreter path) | Fatal |
| dt_013 | FileNotFoundError for existing files (case mismatch) | Fatal |
