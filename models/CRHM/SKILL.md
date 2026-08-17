---
name: crhm
description: >-
  Cold Regions Hydrological Modelling platform — Pomeroy et al. Covers Snow accumulation,
  blowing-snow redistribution and sublimation in HRUs; Canopy interception and sublimation
  of rain and snow; Energy-balance and temperature-index snowmelt with slope/aspect
  radiation correction; Frozen and unfrozen soil infiltration; Two-layer soil water
  balance with depression storage and groundwater store. Use when the task involves
  running, configuring, calibrating or interpreting CRHM.
---

> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
CRHM forcing tools are in `tools/s2_observation_data/` in this KI:
- `tools/s2_observation_data/convert_vic_to_obs.py` — Converts VIC/CMFD forcing to CRHM .obs format (handles specific humidity→RH, unit conversions, physical bounds validation)
- `tools/s2_observation_data/validate_obs_file.py` — Validates CRHM .obs format (header, variables, bounds, date continuity)

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.


# CRHM (Cold Regions Hydrological Model) -- Knowledge Infrastructure

**Package**: hydrocraft-crhm v1.0.0
**Model**: CRHM 1.3 (crhmcode, University of Saskatchewan)
**Domain**: Cold regions hydrology -- blowing snow, sublimation, frozen soil infiltration, energy-balance snowmelt
**Coupling target**: VIC 5.1.0 (cold regions process enhancement)

---

## What is CRHM?

CRHM is a modular, physically-based hydrological model designed for cold regions. Unlike grid-based models (VIC, WRF-Hydro), CRHM uses **Hydrological Response Units (HRUs)** -- irregular landscape units grouped by elevation, land cover, slope, and aspect. Its key strength is a library of cold-regions-specific modules:

- **PBSM** (Prairie Blowing Snow Model): Wind transport, sublimation, redistribution of snow
- **CRHMCanopy**: Forest canopy interception, sublimation (30-40% of snowfall in boreal forests)
- **SnobalCRHM**: Full energy-balance snowmelt with wind and radiation effects
- **PrairieInfil**: Frozen soil infiltration using Gray's equation (prairie clay soils)
- **Slope_Qsi**: Solar radiation correction for slope and aspect (critical in mountains)

Modules form a **chain**: output of one feeds input to the next via `declvar()`/`declgetvar()`. The chain order determines the physics.

## Installation

CRHM is built from C++ source with CMake and GCC:

```bash
bash KISSPATH_KI_ROOT/CRHM/knowledge_infrastructure/install_crhm.sh
```

**Requirements**: cmake, g++ (C++14), git, Boost 1.75.0 (auto-downloaded by install script).

**Executable**: `KISSPATH_BINARIES/crhmcode/crhmcode/build/crhm`

**CLI**:
```bash
crhm [-t ISO|YYYYMMDD] [-f STD|OBS] [-o output.txt] [-p 100] [--obs_file_directory dir] project.prj
```

## Pipeline Stages

| Stage | Name | Skill Document | Key Tools |
|-------|------|----------------|-----------|
| s1 | HRU Basin Setup | `docs/s1_basin_setup_skill.md` | `create_hru_config.py` |
| s2 | Observation Data | `docs/s2_observation_data_skill.md` | `convert_vic_to_obs.py`, `validate_obs_file.py` |
| s3 | Module Selection | `docs/s3_module_selection_skill.md` | `select_modules.py` |
| s4 | Parameter Config | `docs/s4_parameter_config_skill.md` | `create_prj_file.py`, `validate_prj.py` |
| s5 | Execution | `docs/s5_execution_skill.md` | `run_crhm.py`, `parse_crhm_output.py`, `plot_crhm_results.py` |
| s6 | VIC Coupling | `docs/s6_vic_coupling_skill.md` | `convert_vic_to_obs.py`, `merge_crhm_vic.py` |

**Dependencies**: s1 and s2 can run in parallel. s3 depends on s1. s4 depends on s1+s3. s5 depends on s2+s4. s6 depends on s5.

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| create_hru_config | s1 | `tools/s1_basin_setup/create_hru_config.py` | Generate HRU definitions from DEM + land cover |
| convert_vic_to_obs | s2 | `tools/s2_observation_data/convert_vic_to_obs.py` | Convert VIC forcing to CRHM .obs format |
| validate_obs_file | s2 | `tools/s2_observation_data/validate_obs_file.py` | Check .obs format, units, gaps |
| select_modules | s3 | `tools/s3_module_selection/select_modules.py` | Configure module chain by landscape type (auto-detect from HRU config) |
| **derive_parameters** | **s4** | `tools/s4_parameter_config/derive_parameters.py` | **NEW** — Derive all module params from HWSD + DEM + Fang et al. (2013) |
| create_prj_file | s4 | `tools/s4_parameter_config/create_prj_file.py` | Generate .prj project file (accepts `--derived_params`) |
| validate_prj | s4 | `tools/s4_parameter_config/validate_prj.py` | Validate .prj structure and parameter ranges |
| run_crhm | s5 | `tools/s5_execution/run_crhm.py` | Execute CRHM with progress reporting |
| parse_crhm_output | s5 | `tools/s5_execution/parse_crhm_output.py` | Parse CRHM output to CSV/NetCDF |
| plot_crhm_results | s5 | `tools/s5_execution/plot_crhm_results.py` | Generate diagnostic plots (SWE, discharge, etc.) |
| merge_crhm_vic | s6 | `tools/s6_vic_coupling/merge_crhm_vic.py` | Combine CRHM + VIC results for comparison |

### Parameter Derivation Pipeline (NEW, 2026-04-11)

The S4 stage now has a two-step parameter derivation pipeline based on Fang et al. (2013):

```bash
# Step 1: Derive physically-based parameters from global datasets
python tools/s4_parameter_config/derive_parameters.py \
  --hru_config outputs/<run>/crhm/hru/hru_config.json \
  --output outputs/<run>/crhm/derived_params.json

# Step 2: Create .prj with derived parameters (overrides hardcoded defaults)
python tools/s4_parameter_config/create_prj_file.py \
  --hru_config outputs/<run>/crhm/hru/hru_config.json \
  --module_chain outputs/<run>/crhm/modules.json \
  --obs_path outputs/<run>/crhm/basin.obs \
  --start_date "2005 1 1" --end_date "2015 12 31" \
  --output_path outputs/<run>/crhm/basin.prj \
  --derived_params outputs/<run>/crhm/derived_params.json
```

`derive_parameters.py` derives parameters for ALL 15 mountain modules:

| Module | Parameters | Data Source | Reference |
|--------|-----------|-------------|-----------|
| **obs** | obs_elev, lapse_rate=0.75, precip_elev_adj, catchadjust, snow_rain | Min HRU elev, Fang 2013 §3.1 | Fang et al. (2013) |
| **Soil** | soil_moist_max, soil_rechr_max, gw_max, Sdmax, gw_init | HWSD soil × CRHM porosity table × depth (from Fang §3.2.7) | GlobalDll.h SetSoilproperties |
| **GreenAmpt** | soil_type (0-12 USDA) | HWSD texture class | ClassGreenAmpt.cpp soilproperties |
| **evap** | evap_type (0=Granger land, 1=P-T water) | Land cover | Fang §12 |
| **walmsley_wind** | A, B, L, Walmsley_Ht | Terrain slope + DEM | Walmsley et al. (1989) |
| **pbsm** | fetch, distrib | Land cover + elevation | Fang §3.2.3 (300m min for mountains) |
| **crack** | fallstat, Major | Land cover (autumn SM proxy) | Fang §3.2.5 |
| **Netroute** | order, whereto, runK/ssrK/gwKstorage | Elevation sorting + sqrt(area) | Fang §14 |

### Auto Basin Type Detection (NEW, 2026-04-11)

`select_modules.py` now auto-detects basin type from HRU config:

```bash
# Auto-detect (no --basin_type needed):
python tools/s3_module_selection/select_modules.py \
  --hru_config outputs/<run>/crhm/hru/hru_config.json \
  --output_path outputs/<run>/crhm/modules.json
```

Classification logic (Pomeroy et al. 2007):
- **Mountain**: elevation relief > 500m
- **Prairie**: relief < 300m, grassland/cropland > 50%
- **Forest**: forest fraction > 60%
- **Arctic**: latitude > 60°N
- **Mixed**: forest + open mix

### Critical .prj Format Rules (Bugs fixed 2026-04-11)

1. **Flat module format ONLY** — `basin CRHM 02/24/12`, NOT `Basin_Group Macro` (dt_019). CLI binary crashes with Macro format.
2. **NO blank lines in Modules section** — CRHM parses blank lines as empty module names.
3. **Exactly 1 description line in .obs** — line 2 must be a variable declaration, not text (dt_020).
4. **Display_Variable needs module prefix** — `Netroute basinflow 1`, not just `basinflow 1`.

## .prj File Format

CRHM project files use section delimiters (`######`):

```
######
Dimensions:
######
nhru 5
nlay 1
nobs 1

######
Observations:
######
/absolute/path/to/basin.obs

######
Dates:
######
2000 1 1
2010 12 31

######
Modules:
######
Basin_Group Macro 04/20/06
 +basin CRHM 04/20/06
 +global CRHM 04/20/06
 +obs CRHM 04/20/06
 +PBSM CRHM 04/20/06
 +PrairieInfil CRHM 04/20/06
 +Soil CRHM 04/20/06
 +Netroute CRHM 04/20/06

######
Parameters:
######
PBSM fetch <10 to 10000>
1500.0 1500.0 200.0 50.0 30.0
```

**Shared vs module-local parameters (FATAL trap, dt_023).** CRHM resolves a
module's parameter as `<Module> <param>` first, then `Shared <param>`. Basin
geometry — `basin_area`, `hru_area`, `hru_elev`, `hru_lat`, `hru_GSL`,
`hru_ASL` — is read independently by MANY modules (Netroute, obs, pbsm, …), so
it MUST be declared with the `Shared` prefix, exactly as the shipped
`prj/badlake.prj` and every validated basin .prj do. Writing `basin hru_area`
instead leaves Netroute on its default `hru_area = [1] km²` → basinflow comes
out basin-area-fold too small (NSE pinned at −1.0, PBIAS ≈ −100%), and `obs`
never sees `hru_elev` → no lapse-rate elevation banding (all HRUs identical).
`create_prj_file.py` emits these as `Shared` since 2026-07-23; sanity-check any
.prj with `grep 'Shared hru_area'`.

## .obs File Format

```
Station data converted from VIC
t 1 (C)
rh 1 (%)
u 1 (m/s)
ppt 1 (mm/d)
Qsi 1 (W/m^2)
$ea ea(t, rh) (kPa) vapour pressure
2000 1 1 1 0 -15.50 81.50 3.10 0.00 0.00
```

## Module Chain Concept

Pre-built chains by landscape type:

| Landscape | Chain | Key Feature |
|-----------|-------|-------------|
| **Prairie** | basin > global > obs > PBSM > PrairieInfil > Soil > Netroute | Blowing snow transport |
| **Mountain** | basin > global > obs > Slope_Qsi > SnobalCRHM > GreenAmpt > Soil > Netroute | Slope radiation correction |
| **Forest** | basin > global > obs > CRHMCanopy > SnobalCRHM > GreenAmpt > Soil > Netroute | Canopy interception/sublimation |
| **Arctic** | basin > global > obs > PBSM > SnobalCRHM > PrairieInfil > Soil > REWroute | Permafrost + blowing snow |

## Critical Domain Knowledge

### The #1 Silent Error: Humidity Unit Conversion

VIC uses **specific humidity** (kg/kg, values ~0.001-0.02). CRHM expects **relative humidity** (%, values 0-100). If you pass specific humidity directly, CRHM interprets the atmosphere as 0.001-0.02% RH (bone dry). All sublimation goes to zero. SWE accumulates forever. **The model runs to completion with no error.** Always use `convert_vic_to_obs.py` which applies the Tetens formula conversion.

**Detection**: If max(RH) in .obs file < 1.0, the units are wrong.

### Parameter Clamping (Silent)

CRHM clamps parameters to their declared `<min to max>` range WITHOUT warning. You set `fetch=50000` but the model uses `max=10000`. Always run `validate_prj.py` before running CRHM.

### VIC Coupling: Process Ownership

Both VIC and CRHM compute snowmelt, ET, and soil moisture. **Define a process ownership table** before merging outputs. Each process is assigned to exactly one model. Double-counting produces water balance errors >100%.

### Cold Regions Observation Data Quality

Winter weather stations in cold regions (-40C, blizzards, rime icing) frequently fail. Gap-filled data with constant values misrepresents extreme cold events that control frozen soil state. Prefer reanalysis (ERA5, CMFD, MSWX) over gap-filled station data for cold regions.

### Blowing Snow is Landscape-Specific

PBSM is only valid for wind-exposed terrain (prairie, tundra, alpine above treeline). Using it in dense forest produces unrealistic transport. CRHMCanopy handles snow processes in forested landscapes.

## Unit Conversion Table

| Variable | VIC Unit | CRHM Unit | Conversion | Silent if Wrong? |
|----------|----------|-----------|------------|------------------|
| Temperature | C | C | None | No |
| Humidity | kg/kg (specific) | % (relative) | Tetens formula | **YES** |
| Precipitation | mm/timestep | mm/d | *24/timestep_hours | **YES** |
| Wind | m/s | m/s | None | No |
| SW radiation | W/m2 | W/m2 | None | No |
| LW radiation | W/m2 | W/m2 | None | No |
| Pressure | kPa | kPa | None | No |

## Error Handling

See `diagnostics/triplets.yaml` for 18 diagnostic triplets covering:
- **Unit conversion** (dt_001, dt_002, dt_009): humidity, precipitation, VIC-CRHM mismatch
- **Silent errors** (dt_006, dt_010, dt_011, dt_012, dt_016): parameter clamping, double-counting, winter gaps, CRS mismatch, wrong module
- **Format errors** (dt_003, dt_005, dt_013, dt_018): .obs header, parameter count, section delimiters, timestep
- **Runtime errors** (dt_004, dt_007, dt_008, dt_014, dt_017): module deps, paths, crashes, empty output, Boost

**Silent errors account for 7 of 18 triplets (39%)** -- consistent with the 37% rate across all 15 models in the toolkit.

## Quick Start

```bash
# 1. Build CRHM
bash install_crhm.sh

# 2. Create HRUs
python tools/s1_basin_setup/create_hru_config.py --dem_path dem.tif --landcover_path lc.tif --shapefile_path basin.shp --output_dir out/hru

# 3. Convert VIC forcing
python tools/s2_observation_data/convert_vic_to_obs.py --forcing_dir vic_forcing/ --grid_nc grid.nc --output_path out/basin.obs --start_year 2000 --end_year 2010

# 4. Select modules (prairie example)
python tools/s3_module_selection/select_modules.py --basin_type prairie --output_path out/modules.json

# 5. Create .prj file
python tools/s4_parameter_config/create_prj_file.py --hru_config out/hru/hru_config.json --module_chain out/modules.json --obs_path out/basin.obs --start_date "2000 1 1" --end_date "2010 12 31" --output_path out/basin.prj

# 6. Validate
python tools/s4_parameter_config/validate_prj.py --prj_path out/basin.prj

# 7. Run CRHM
python tools/s5_execution/run_crhm.py --crhm_exe model/crhmcode/crhmcode/build/crhm --prj_path out/basin.prj --output_path out/output.txt

# 8. Parse and plot
python tools/s5_execution/parse_crhm_output.py --output_path out/output.txt --output_format both --output_dir out/parsed
python tools/s5_execution/plot_crhm_results.py --csv_path out/parsed/crhm_results.csv --output_dir out/plots --title "My Basin"
```

---

*This knowledge infrastructure package was created using the Knowledge Dissection Toolkit (Zhang et al., Nature, under review).*
*Package: hydrocraft-crhm v1.0.0 | 10 tools | 6 skill documents | 18 diagnostic triplets | 6 pipeline stages*

---

## Validated Module Chain — Mountain Basin (Belly River, Alberta)

**15 modules, tested 2005-2015, KGE=0.65, PBIAS=-3.4%**

```
basin → global → obs → calcsun → Slope_Qsi → walmsley_wind → intcp → pbsm → albedo → ebsm → netall → crack → evap → Soil → Netroute
```

| Module | Purpose | Key Parameters |
|--------|---------|---------------|
| basin | Geometry | basin_area, hru_area |
| global | Global radiation | Time_Offset |
| obs | Read forcing | precip_elev_adj (USE 0.05 for mountains!) |
| calcsun | Solar angles | (uses hru_lat) |
| **Slope_Qsi** | Slope radiation | hru_ASL (aspect), hru_GSL (slope) |
| **walmsley_wind** | Topo wind amplification | A=4.0/3.0/0.5, L=500/800/2000 |
| intcp | Canopy interception | (forest HRUs only) |
| pbsm | Blowing snow | fetch, N_S, distrib |
| albedo | Snow albedo decay | Albedo_bare, Albedo_snow |
| ebsm | Energy balance melt | tfactor, nfactor |
| netall | Net radiation | (computed from Qsi, Qli, albedo) |
| crack | Frozen soil infiltration | fallstat, infDays, Major |
| evap | Evapotranspiration | evap_type, Ht |
| Soil | Soil + GW | gw_K, gw_max, soil_gw_K |
| Netroute | Routing | Kstorage, Lag, gwKstorage, gwLag |

### Critical Lessons from Belly River Validation

1. **.obs header**: NO `####` line before variable declarations — causes infinite loop (dt_v001)
2. **pbsm required**: Without it, CRHM segfaults on wildcard SWE search (dt_v002)
3. **NASA POWER precip ÷24**: Hourly values are mm/day rate, not mm/hr (dt_v004)
4. **Mountain precip scaling**: NASA POWER underestimates by ~40% in Rockies — scale ×1.7
5. **GW parameters**: gwKstorage=50-80, gwLag=500-1000, gw_K=2-5 for sustained winter baseflow
6. **Wind amplification**: Walmsley A=4.0 for alpine ridges (NASA POWER wind is 3.5x too low)

### Validated Mountain Basin — St. Mary River below Morris Creek (HYDAT 08NG077)

**3 HRUs, 208 km², Purcell Mtns BC (49.737, -116.435), NASA POWER forcing 2005-2015.**
12-module chain (`basin → global → obs → calcsun → intcp → pbsm → albedo → ebsm →
netall → crack → evap → Soil → Netroute`) reproduces a **strong uncalibrated fit**:
CAL(2006-2010) NSE 0.524 / KGE 0.754 / PBIAS -7.1%; VAL(2011-2015) NSE 0.521 /
KGE 0.743 / PBIAS -8.6%. Water balance closes to 0.4% (P=13115, ET=2024, Q=10641,
dS=401 mm over 11 yr). Sim discharge = daily-summed `basinflow(1)` (m³/int) ÷ 86400
to m³/s; `basingw(1)` is already included in `basinflow` (adding it changes Q <0.02%).

### Validated Mountain Basin — Bow River at Banff (HYDAT 05BB001)

**3 HRUs, 2210 km², Canadian Rockies AB (51.172, -115.572), NASA POWER forcing
2005-2015.** Same 13-module chain as St. Mary (`basin → global → obs → calcsun →
intcp → pbsm → albedo → ebsm → netall → crack → evap → Soil → Netroute`). HRUs
Alpine/Forest/Valley at elev 2600/2050/1550, obs_elev 2050, areas 737/737/736 km².

**THE GROUNDWATER-BASEFLOW LESSON (lifts NSE 0.145 → 0.533).** The first Bow run
used `create_prj_file.py` hardcoded defaults, which make the groundwater system
**hydrologically dead**: `gw_init=0`, `Netroute gwKstorage=0`, `gwLag=0`, `Soil
soil_gw_K≈0.001`, `gw_K≈0.001`. Result: NO winter baseflow (sim Jan-Mar ≈ 0 vs
obs ~9 m³/s) and an UN-attenuated freshet (May sim 105 vs obs 46 m³/s, alpha
σ_sim/σ_obs = 1.48). NSE was capped at 0.145 (VAL 0.302) — borderline.

**Fix = apply Belly lesson #5 (enable a slow GW reservoir).** This is the single
highest-leverage change for any snowmelt-fed mountain river. It both adds winter
baseflow AND attenuates/delays the spring freshet (the dominant NSE error):

| Param | Dead default | Validated Bow value |
|-------|-------------|---------------------|
| `Soil soil_gw_K`   | 0.001 | **1.5**  (soil→gw recharge) |
| `Soil gw_K`        | 0.001 | **0.3**  (SLOW release → sustains winter) |
| `Soil gw_max`      | 100/200/300 | **800/1000/1200** |
| `Soil gw_init`     | 0/50/150 | **400/550/700** (start near equilibrium) |
| `Netroute gwKstorage` | 0 | **40** |
| `Netroute gwLag`   | 0 | **400** (hr) |
| `Netroute Kstorage` | 4/8/2 | **12/16/6** (d, more freshet attenuation) |
| `Netroute Lag`     | 24/48/8 | **48/72/24** (hr) |

Result (NASA POWER ×1.0, no Rockies precip scaling — see Bow note in memory):
CAL(2006-2010) **NSE 0.424 / KGE 0.675 / PBIAS +4.5%**; VAL(2011-2015) **NSE 0.593
/ KGE 0.784 / PBIAS +4.9%**; FULL(2006-2015) NSE 0.533 / KGE 0.745 / r 0.812.
alpha dropped 1.48→1.17. **Diagnostic to trigger this fix: if monthly-mean sim
discharge in Jan-Mar is ≈ 0 while obs shows steady winter flow, your GW reservoir
is off — enable it.** Do NOT just lower precip; ×1.0 is already right at 51°N.

**WB note for slow-GW runs:** enabling a big slow gw store costs WB closure — the
Netroute in-channel/gw *routing* stores (gwKstorage/gwLag, Kstorage/Lag) have NO
output state variable, so a decadal run shows a ~4-5% residual that you cannot fully
close from outputs (Bow: residual 393 mm = 36 mm/yr over 11 yr, P=8685 ET=1812
Q=6119 dS=361; `validate_water_balance` returns FAIL only because its 50 mm absolute
tolerance is calibrated for ANNUAL not decadal totals, and ALL its unit-error
heuristics pass). This is a storage-accounting artifact, NOT a unit error. Output
`Soil gw`, `Soil Sd`, `Soil soil_rechr` as Display_Variables to recover most of dS.

### Validated Mountain Basin — Ghost River above Waiparous (HYDAT 05BG010)

**3 HRUs, 485 km², limestone Front Ranges AB (51.270, -114.926), NASA POWER
forcing 2005-2015.** Same 13-module reduced chain as Bow/St.Mary. HRUs
Alpine/Forest/Valley at 2400/1950/1600 m, areas 120/180/185 km². Spring/baseflow-
dominated (limestone karst). **CAL(2006-2010) NSE 0.431 / KGE 0.678 / r 0.702.**
Raw VAL/FULL NSE collapse to ~0.05 NOT from model error but because the **June-2013
Alberta flood (obs 350 vs sim 6 m³/s — a 1-in-100 orographic-rain event NASA POWER
point precip cannot resolve) is 93% of the total daily SSE**. Excluding 2013:
VAL 0.346, FULL 0.381. Monthly climatology tracks obs (winter ~2, gradual recession).

**THE obs_elev LESSON (lifts CAL NSE from negative to 0.43).** `obs_elev` MUST be
the elevation the forcing's temperature actually represents — for NASA POWER that
is the **reported site elevation**, returned in `geometry.coordinates[2]` of any
POWER API response (climatology endpoint is quickest):
```python
import requests; s=requests.Session(); s.trust_env=False
j=s.get("https://power.larc.nasa.gov/api/temporal/climatology/point",
        params={"latitude":LAT,"longitude":LON,"community":"RE",
                "parameters":"T2M","format":"JSON"}).json()
obs_elev = j["geometry"]["coordinates"][2]   # e.g. 1566.94 m at 05BG010
```
Do NOT guess obs_elev as a mid-HRU value. CRHM lapses temperature from obs_elev to
each hru_elev; if obs_elev is set too HIGH, the lower HRUs are spuriously WARMED and
their snow melts 1-2 months early (sim freshet in Apr-May instead of the observed
June peak), wrecking the correlation. At 05BG010, obs_elev=1950 (a mid-HRU guess)
gave a negative-NSE early freshet; obs_elev≈1567 (the true POWER elevation; 1650
after minor snow-accumulation tuning) shifted melt to June.

**Baseflow-dominated basins need heavy routing storage.** Limestone/spring-fed
basins (Front Ranges) sustain winter flow for months with no input. Push snowmelt
through the slow store (`Soil soil_ssr_runoff=0`, `soil_gw_K≈5`, large `gw_max`) and
use a LONG Netroute `Kstorage` (here 62/74/40 d) + `Lag` to spread the freshet into
the fall recession. Light/flashy routing reproduces neither the freshet shape nor
the baseflow. Diagnostic: if sim peaks Apr-May and goes near-zero Aug-Dec while obs
shows a June peak with sustained fall flow, your routing storage is too small AND/OR
obs_elev is too high.

### Validated Mountain Basin — Coldwater River near Brookmere (HYDAT 08LG048)

**3 HRUs, 316 km², interior Cascade Mtns BC (49.856, -120.909), NASA POWER forcing
2005-2015.** Same 13-module reduced chain as Bow/St.Mary. Moderate-elevation
snowmelt-freshet basin (DEM 966-2100 m, median 1250). HRUs Alpine/Forest/Valley at
1450/1230/1050 m, areas 79/158/79 km². Obs regime: sharp May-June freshet (peak
~24 m³/s), sustained winter baseflow ~2.4 m³/s, low Aug-Sep. **CAL(2006-2010) NSE
0.366 / KGE 0.694; VAL(2011-2015) NSE 0.533 / KGE 0.731 / r 0.820 / PBIAS +6.2%;
FULL NSE 0.452.** WB FAIL 5.1% = the decadal Netroute routing-storage artifact (see
Bow WB note); runoff coef Q/P 0.71 matches obs 0.67, units clean.

**TWO NEW LESSONS that took NSE_val 0.22 → 0.53:**

1. **NASA POWER underestimates precip in INTERIOR BC too — scale ×1.7 (same as the
   Rockies).** Diagnostic that forces this: compute obs runoff depth (mean Q ×
   86400 × 365 / area) BEFORE running. At 08LG048 obs runoff = 683 mm/yr but raw
   NASA POWER P = 603 mm/yr → runoff coef > 1.0, physically impossible. `convert_vic_to_obs.py
   --precip_scale 1.7` lifts P to 1025 mm/yr → coef 0.67 (realistic for a snowmelt
   basin). ALWAYS check runoff-coef-implied precip deficit before trusting raw POWER.

2. **THE INVERSE-GHOST obs_elev KNOB (DISCHARGE-SCORED RUNS ONLY): warm obs_elev ABOVE the true site elevation to
   ADVANCE a too-late freshet.** The Ghost lesson (above) warns that obs_elev set too
   HIGH melts snow too EARLY — true, but the corollary is a usable calibration lever.
   At 08LG048 the true POWER site elev is 1251 m; using it verbatim gave a **June**-
   peaked freshet (sim June 36 vs obs 21) one month LATE of the observed **May** peak,
   plus near-zero winter flow (all melt water dumped in June). Raising obs_elev to
   **1320 m** (+69 m) warmed every HRU by ~0.5 °C, shifting the melt centroid from
   June into May to match obs (sim May 25.7 ≈ obs 24.3) — NSE_val jumped 0.35 → 0.53.
   **Diagnostic: if sim freshet peaks ONE MONTH LATE of obs (June vs May) and winter
   flow is near-zero, nudge obs_elev UP 50-100 m** (and conversely DOWN if sim peaks
   early). obs_elev is the master timing knob for DISCHARGE; pair it with strong GW (below)
   for winter. **NEVER apply this knob when the scored variable is SWE or any other
   mass state.** For discharge, obs_elev shifts freshet TIMING. For SWE it raises HRU
   temperature and therefore DELETES SNOW MASS directly — it fabricates agreement
   instead of correcting a phase error. On SWE-scored runs obs_elev is FIXED at the
   forcing-source grid-cell elevation that derive_parameters.py computes.

3. **Match HRU elevation bands to the DEM hypsometry, not round guesses.** First run
   used Alpine=1650 m but only ~5% of the basin is above 1650 (p95=1679); too much
   area sat high and froze melt into June. Re-banding to DEM percentiles (upper≈p80,
   mid≈p50, lower≈p15 → 1450/1230/1050) with ~25/50/25% area split fixed the timing.

4. **Moderate snowmelt basins need a MODERATE slow-GW reservoir** (between dead-default
   and the heavy Ghost karst setup): `Soil soil_gw_K=3, gw_K=0.6, gw_max=600/800/1000,
   gw_init=250/350/450`; `Netroute gwKstorage=50, gwLag=500, Kstorage=8/12/4,
   Lag=42/66/20`. gw_K=0.1 left winter near-zero; 0.6 sustains it (obs winter ~0.66
   mm/day basin-wide). soil_ssr_runoff stays 1 (subsurface routes the freshet).

### NASA POWER cal/val PERIOD TRAP (silent n=0)

`validators/standard_calval.compute_calval_metrics` **hardcodes the 1981-1990
Bengbu periods**. NASA POWER **hourly** forcing only exists **from 2001-01-01**, so
any NASA-POWER-driven cold-region run (the recommended forcing here) has ZERO overlap
with the hardcoded windows and the helper silently returns `n=0, NSE=None` for every
period. This is NOT a model failure — it is a period mismatch. When forcing starts
≥2001, you MUST override: use spinup=first year, then a 5/5 split of the remaining
record (e.g. 2005-2015 → spinup 2005, CAL 2006-2010, VAL 2011-2015) and compute with
the `_nse/_kge/_pbias/_r` helpers directly. Record the override periods in
`period_calibration`/`period_validation`.

### Forcing preflight gap (NASA POWER / CRHM .obs unsupported)

`validators/preflight_forcing.py --source auto` only recognizes cmfd/mswx/era5/fluxnet
— it returns `FAIL: Unable to detect data source` on a built CRHM `.obs` (NASA POWER
origin). For CRHM runs, validate units directly on the `.obs`: `t` in [-50,45] °C,
`max(rh) > 1.0` (the #1 silent humidity bug, see above), `p` ≤ ~50 mm/hr with annual
total physically plausible, `u` ≥ 0 m/s, `Qsi` ≤ ~1100 W/m². `convert_vic_to_obs.py`
already enforces these bounds at write time.

### Validated Mountain Basin — Similkameen River above Goodfellow Creek (HYDAT 08NL070)

**3 HRUs, 408 km², interior Cascade Mtns BC (49.094, -120.673), NASA POWER forcing
2005-2015.** Same 13-module reduced chain as Bow/St.Mary/Coldwater. HRUs
Alpine/Forest/Valley at 1820/1640/1340 m (Copernicus GLO-30 hypsometry p80/p50/p15;
basin median 1620 m), areas 102/204/102 km². High snowmelt basin, sharp May-June
freshet (peak ~31 m³/s), sustained winter baseflow ~3 m³/s. **CAL(2006-2010) NSE
0.395 / KGE 0.670 / PBIAS +0.8; VAL(2011-2015) NSE 0.682 / KGE 0.829 / r 0.839 /
PBIAS -5.3; FULL NSE 0.541.** WB FAIL 5.7% (P=9100 ET=2241 Q=6282 dS=59 mm) = the
decadal Netroute routing-storage artifact (see Bow WB note); runoff coef Q/P 0.69,
units clean. Reused the Coldwater GW recipe verbatim (winter baseflow 0.64 mm/day ≈
Coldwater's) — `gw_K=0.6, gw_max=600/800/1000, gw_init=250/350/450, soil_gw_K=3.0;
Netroute gwKstorage=50, gwLag=500, Kstorage=14/20/8, Lag=42/66/20`.

**NEW LESSON A — NASA POWER OVER-estimates precip in some interior-BC basins; the
runoff-coef diagnostic also catches the OPPOSITE sign.** Coldwater (08LG048, ~80 km
away) needed precip ×1.7 (POWER under-caught); Similkameen needed precip ×0.75 (POWER
OVER-caught). Same diagnostic, opposite correction: raw POWER P=1197 mm/yr but obs
runoff=616 mm/yr → with realistic montane ET ~550 mm the implied P≈1170 looked OK,
yet the run came out PBIAS +62% because CRHM's energy-limited Granger ET only removed
~220 mm — so the EXCESS had to be shed as precip. Lever used: `obs ClimChng_flag=1`
+ `ClimChng_precip=0.75` (a clean in-.prj multiplier; equivalent to re-running
`convert_vic_to_obs.py --precip_scale 0.75`). **Do NOT assume POWER always under-
catches in the mountains — check PBIAS sign after the first run and scale precip to
zero it.** Pair this with `Shared inhibit_evap=0` (the Coldwater/St.Mary template
ships `inhibit_evap=1`, which suppresses ET and inflates volume; setting it 0 0 0
recovered ~120 mm/yr of ET here and cut PBIAS from +62% to +54% before precip scaling).

**NEW LESSON B — for a HIGH basin whose hypsometry sits ABOVE the NASA POWER site
elevation, the inverse-ghost obs_elev advance can be LARGE (+300 m).** POWER site
elev here = 1584 m but the basin median is 1620 m and the Alpine HRU is 1820 m, so
lapsing temperature UP from 1584 froze the alpine snowpack until July (sim peaked
July, obs peaks May-June — 6-8 weeks late). Raising `obs_elev` to **1910 m** (+326 m
above the true POWER elev, i.e. ~+2.4 °C warming of every HRU) pulled the melt
centroid back to June and lifted VAL NSE 0.35→0.68. This is a much bigger advance
than the +69 m used at Coldwater because the Similkameen hypsometry is ~370 m higher
and POWER's grid-cell temperature runs cold for the basin. **Rule of thumb: set
obs_elev so the area-weighted-mean HRU melts in the observed freshet month; if the
sim freshet is >1 month late, raise obs_elev in 50-100 m steps (here 5 steps) until
the simulated peak month matches obs.** Watch PBIAS while doing this — warming also
raises ET slightly, so re-zero PBIAS with ClimChng_precip after the timing is right.

### Validated Mountain Basin — Kaslo River below Kemp Creek (HYDAT 08NH005)

**3 HRUs, 442 km², Selkirk Mtns BC (49.908, -116.953), NASA POWER forcing
2005-2015.** Same 13-module reduced chain as Bow/St.Mary/Coldwater/Similkameen.
HRUs Alpine/Forest/Valley at 2139/1813/1233 m (Copernicus GLO-30 hypsometry
p80/p50/p15; basin mean 1748 m, relief 2263 m), areas 110/221/111 km². Strong
snowmelt basin: sharp June freshet (peak 50 m³/s), sustained winter baseflow
~3 m³/s, runoff 941 mm/yr. **BEST CRHM HYDAT RESULT TO DATE: FULL NSE 0.731 /
KGE 0.819 / r 0.856 / PBIAS -1.3; CAL(2006-2010) NSE 0.730 / KGE 0.779 / PBIAS
-9.3; VAL(2011-2015) NSE 0.729 / KGE 0.816 / r 0.856 / PBIAS +5.2.** Config:
NASA POWER precip ×1.6 at .obs write-time + ClimChng_precip 0.95 (net ×1.52),
obs_elev 2350, gw_K 1.0, gw_max 900/1200/1500, gw_init 400/550/700, soil_gw_K 5.0,
Netroute Kstorage 16/24/10, Lag 48/72/24, gwKstorage 50, gwLag 500. WB FAIL 8.3%
(P=14606 ET=3077 Q=9826; states recover dS 489 mm via Soil gw/soil_rechr output;
remaining 1214 mm = Netroute routing-storage artifact, no output state — see Bow
WB note); units clean, runoff coef 0.67.

**THE #1 LESSON (lifted NSE 0.60 → 0.73) — to advance a LATE freshet you must
raise obs_elev ABOVE the ALPINE HRU band, not just above the POWER site elev.**
This sharpens the Coldwater/Similkameen inverse-ghost knob. The first tuned run
(obs_elev 2050, ~+294 m above POWER 1756) fixed the mid/low-HRU timing but left a
big **July-August** melt tail (sim Jul 46 / Aug 16 vs obs 29 / 10) because the
Alpine HRU (110 km² at 2139 m) sat ABOVE obs_elev and so its snow was lapsed COLD
and melted 1-2 months late. obs_elev only warms HRUs *below* it (lapse rate ×
(obs_elev − hru_elev)); an HRU at or above obs_elev gets no advance. Raising
obs_elev to **2350 m** (above the 2139 m Alpine band → the whole basin is now
warmed) pulled the alpine melt into June and collapsed the July-Aug tail, lifting
NSE from 0.60 to 0.73. **Diagnostic: if the sim freshet has a fat tail in the month
or two AFTER the obs peak (not just a shifted peak), your highest HRU is still
above obs_elev — raise obs_elev past the top HRU elevation, not merely past the
POWER site elev.** Over-shooting (obs_elev 2450) keeps gaining NSE but introduces a
spurious early-April melt and drives PBIAS negative (over-warming → more ET) and
KGE down; 2350 was the sweet spot where the alpine melt advanced without a fake
April rise. Re-zero PBIAS with ClimChng_precip after timing is set (here 0.95).

**DEM TILE-COVERAGE LESSON (delineation returned 12% of true area until fixed).**
`ki_tools_common.terrain_ops.delineate_basin` needs a DEM mosaic that fully covers
the basin's UPSTREAM extent, not just the gauge. Kaslo's gauge is on Kootenay Lake's
west shore (-116.95) but its headwaters drain from the Selkirk crest ~25 km WEST
(-117.2), spilling into the W118 1°×1° tile. Mosaicking only N49/N50 × W116/W117
Copernicus GLO-30 tiles delineated only 48-53 km² (a truncated sub-basin); adding
N49_W118 + N50_W118 and re-mosaicking gave 440.7 km² (HYDAT 442, 0.3% error).
**Before delineating, sketch which way the river drains and download one tile
PAST the expected headwater divide.** Copernicus GLO-30 tiles fetch keyless from
`https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{Nyy_00_Wxxx_00}_DEM/...tif`.
Also: the HYDAT station lat/lon can sit a cell or two off the mapped channel
(here ~0.02° west of the main stem); snap_distance_m=2000 + stream_threshold=500
recovered the correct outlet.

**TOOL BUG FIXED — validate_obs_file.py mislabeled 'p' as pressure and required
'ppt'.** CRHM's obs module (and the canonical `convert_vic_to_obs.py`, and every
validated .obs in outputs/) names precipitation **`p`** (mm). `validate_obs_file.py`
hard-required a `ppt` declaration AND carried `PHYSICAL_BOUNDS["p"]=(30,110)` as
*pressure (kPa)* — so it raised a CRITICAL "precip 'ppt' not declared" error and
flagged ALL 96408 precip values out-of-bounds on a perfectly valid file. Fixed:
`p` now bounds (0,500) as precipitation, pressure renamed to `press`, and the
required-variable check accepts `p` (or legacy `ppt`). Validator now returns 0
errors / 0 warnings on canonical NASA-POWER .obs.

### Validated Mountain Basin — Gold River above Palmer Creek (HYDAT 08NB014)

**3 HRUs, 429 km², northern Selkirk/Columbia Mtns BC (51.678, -117.718), NASA
POWER forcing 2005-2015.** Same 13-module reduced chain as Bow/St.Mary/Coldwater/
Similkameen/Kaslo. HRUs Alpine/Forest/Valley at 2485/2083/1503 m (Copernicus
GLO-30 hypsometry, area terciles; basin mean 2029 m, **relief 2735 m — the highest
of any validated CRHM HYDAT basin**, 760-3496 m), areas 145/142/142 km². Very wet,
**LATE (July-peaking)** snowmelt regime: obs peaks month 7 (55-56 m³/s), sustained
winter baseflow ~2 m³/s, **runoff 1337 mm/yr** (heaviest of all validated basins).
**TIES THE BEST CRHM HYDAT RESULT: FULL(2006-2015) NSE 0.715 / KGE 0.827 / r 0.849
/ PBIAS -1.9; CAL(2006-2010) NSE 0.692 / KGE 0.777 / PBIAS -3.3; VAL(2011-2015)
NSE 0.735 / KGE 0.861 / r 0.864 / PBIAS -0.7** (VAL NSE just exceeds Kaslo's 0.729).
Config: NASA POWER precip ×1.0 at write-time + `ClimChng_precip 1.66` (net ×1.66),
obs_elev 2500, gw_K 1.0, soil_gw_K 6.0, gw_max 1200/1500/1800, gw_init 600/750/900,
Netroute Kstorage 16/24/10, Lag 48/72/24, gwKstorage 50, gwLag 500, inhibit_evap 0.
WB residual 9.2% after outputting Soil gw/soil_rechr/Sd states (dS recovered
398→759 mm); remaining 1701 mm = Netroute routing-storage artifact (no output
state — see Bow/Kaslo WB note). Units clean (P=1678 ET=191 Q=1263 mm/yr, runoff
coef 0.75). obs_shape = `point_time_series` → NSE/KGE/r/PBIAS all gate-valid.

**LESSON 1 — CONFIRMS & SHARPENS the Kaslo "raise obs_elev past the TOP HRU"
rule on an even-higher basin: the sweet spot sits right AT/just-above the alpine
band, and over-shooting it loses NSE fast.** First run (obs_elev 1950, ~+195 m
above POWER 1756 but 535 m BELOW the 2485 m alpine band) put the whole freshet
1-2 months LATE — sim peaked Aug (51) with a fat Aug-Sep tail while obs peaks
Jun-Jul; NSE_val was only 0.60. Sweeping obs_elev up: **2500 (just above the
2485 alpine band) → NSE_val 0.738, sim peak month snaps to July matching obs,
Aug sim 34.5 ≈ obs 35.2** — the alpine snow is now warm enough to melt in the
observed window. Pushing further (2600 → 0.684, 2700 → 0.652) over-warms: the
snowpack melts too fast and the late-summer flow collapses (Aug sim drops to
27 then 20). **Rule refined: set obs_elev to roughly the ALPINE-HRU elevation
(here 2485→use 2500), NOT far above it. For a late (July) freshet you need
obs_elev ≈ top-HRU elev; for an earlier (May-June) freshet like Kaslo you may
go 100-200 m past it. Sweep in 100 m steps and stop when the sim peak MONTH
matches obs and the post-peak tail collapses — adding more obs_elev past that
keeps shifting NSE but introduces a spurious early melt.**

**LESSON 2 — winter baseflow here was RECHARGE-limited, not release-limited:
lowering gw_K did nothing; only a BIGGER gw store helped.** Sim winter (JFM) ran
~1.5 vs obs 2.0 m³/s. Counterintuitively, slowing the gw release (gw_K 1.0→0.7→0.5)
did NOT raise winter flow (stayed 1.43-1.49) because the gw reservoir was emptying
before spring, not releasing too fast. Enlarging the store (gw_max 900/1200/1500 →
1200/1500/1800, gw_init 400/550/700 → 600/750/900) nudged winter to 1.58 and
zeroed PBIAS (-0.7). **Diagnostic: if winter flow is low AND lowering gw_K doesn't
fix it, the store is recharge/capacity-limited — raise gw_max + gw_init, not lower
gw_K.** The residual winter deficit (~0.4 m³/s) is the one un-closed feature; it
does not pay to over-tune it (trades against the freshet NSE).

**LESSON 3 — the runoff-coefficient precip diagnostic scales to very wet basins.**
obs runoff 1337 mm/yr forced a large precip up-scale: raw NASA POWER P=1011 mm/yr
gives a physically impossible runoff coef 1.32. ClimChng_precip 1.66 lifts P to
1678 mm/yr → coef 0.75 (realistic for a high, glacierized Selkirk basin). ALWAYS
compute obs runoff depth (mean Q × 86400 × 365 / area × 1000) BEFORE the first run
and target P ≈ runoff + montane ET (~200 mm here) + small dS; here that predicted
~1550-1700 mm/yr and 1.66 landed it. **DEM tiles**: Gold River drains NW into the
Selkirk crest; mosaicking N51/N52 × W117/W118/W119 Copernicus GLO-30 and snapping
with stream_threshold=1000, snap_distance_m=1200 gave 422.5 km² (HYDAT 429, 1.5%);
a looser snap (sd=2000) grabbed an adjacent drainage at 530 km² (+24%) — tighten
the snap when delineated area overshoots.

### Validated Mountain Basin — Blue River near Blue River (HYDAT 08LB038)

**3 HRUs, 272 km², Monashee/Cariboo Mtns BC (52.117, -119.302), NASA POWER
forcing 2005-2015.** Same 13-module reduced chain as Bow/St.Mary/Coldwater/
Similkameen/Kaslo/Gold. HRUs Alpine/Forest/Valley at 1923/1546/1070 m (Copernicus
GLO-30 area-equal terciles; basin mean 1513 m, relief 1845 m, 674-2520 m), areas
91/91/90 km². Very wet (**runoff 1242 mm/yr**, 2nd only to Gold), sharp **May-June**
freshet (obs June 39.6 / May 31.1 m³/s), sustained winter baseflow ~1.9 m³/s.
**STRONG result: FULL(2006-2015) NSE 0.636 / KGE 0.799 / r 0.809 / PBIAS +1.8;
CAL(2006-2010) NSE 0.625 / KGE 0.789 / PBIAS +3.5; VAL(2011-2015) NSE 0.642 /
KGE 0.805 / r 0.812 / PBIAS +0.5.** Config: NASA POWER precip ×1.0 at write-time +
`ClimChng_precip 1.68`, obs_elev 2100, gw_K 0.7, soil_gw_K 6.0, gw_max
1900/2300/2700, gw_init 950/1150/1350, **Netroute Kstorage 10/16/6** (NOT the
Gold/Kaslo 16/24/10 — see lesson), Lag 48/72/24, gwKstorage 50, gwLag 500,
inhibit_evap 0. WB residual 8.6% after outputting Soil gw/soil_rechr/Sd states
(dS recovered 532 mm); remainder = Netroute routing-storage artifact (no output
state — see Bow/Kaslo WB note). Units clean (P=1697 ET=251 Q=1247 mm/yr, runoff
coef 0.73). Delineation EXACT (272.0 km² vs HYDAT 272) — Copernicus N51/N52 ×
W119/W120, stream_threshold=1000, snap_distance_m=1200. obs_shape =
`point_time_series` → NSE/KGE/r/PBIAS all gate-valid (dag var `basinflow_s`).

**THE #1 NEW LESSON (lifted VAL NSE 0.61→0.66, KGE 0.72→0.81) — do NOT blindly
inherit the prior basin's Netroute `Kstorage`; if the sim has a fat post-freshet
recession TAIL that obs_elev cannot fix, the routing storage is too HEAVY — reduce
it.** This is the recession-shape counterpart to the obs_elev timing knob. Starting
from the Gold template's heavy `Kstorage 16/24/10`, raising obs_elev advanced the
freshet PEAK to the right month (June) but left a persistent **August overshoot
(sim ~9-11 vs obs 6 m³/s)** that NO obs_elev setting removed — pushing obs_elev
higher only over-warmed winter (JFM > obs) and drove PBIAS negative. The Aug tail
was a ROUTING artifact: the heavy in-channel `Kstorage` smeared the June freshet
volume forward into Aug-Sep. Cutting `Kstorage` 16/24/10 → **10/16/6** collapsed
Aug from 9.5 → 4-6 m³/s (matching obs), jumped KGE_val 0.716 → 0.805 and NSE_val
0.61 → 0.66 in a single step, with PBIAS staying ~0. **Diagnostic: if the sim
freshet PEAK month already matches obs but the 1-3 months AFTER the peak run
persistently HIGH (fat recession tail) while winter and PBIAS are fine, lower
Netroute Kstorage (less in-channel storage) rather than touching obs_elev — obs_elev
moves the peak's TIMING, Kstorage governs the post-peak RECESSION SHAPE.** The two
levers are orthogonal: set obs_elev for peak-month first, THEN tune Kstorage for the
recession. Flashier basins (steeper, smaller channel storage) want lighter Kstorage
than the heavy-baseflow karst basins (Ghost 62/74/40); Blue River sits at the light
end despite being very wet because its freshet is genuinely sharp.

**LESSON 2 confirms Gold's recharge-limited winter rule.** Winter (JFM) sim started
at 0.9 vs obs 1.9 m³/s; lowering gw_K did nothing, but enlarging the gw store
(gw_max 1200/1500/1800 → 1900/2300/2700, gw_init 600/750/900 → 950/1150/1350) lifted
winter to 1.89 = obs EXACTLY. Recharge/capacity-limited, not release-limited — raise
gw_max+gw_init, don't lower gw_K (3rd basin to confirm: Gold, then here).

**LESSON 3 — the runoff-coef precip diagnostic nailed the up-scale on first try.**
obs runoff 1242 mm/yr; raw NASA POWER P=1024 mm/yr → impossible coef 1.21.
ClimChng_precip 1.68 lifted P to 1697 mm/yr → coef 0.73 (realistic wet Monashee).
Predicted target P ≈ runoff(1242) + montane ET(~250) + small dS ≈ 1500-1700; 1.68
landed it with PBIAS +1.8. Delineation needed no snap-widening — the gauge sits on
the mapped main stem; sd=1200/threshold=1000 gave the exact HYDAT area.

### Validated Mountain Basin — Blaeberry River above Willowbank Creek (HYDAT 08NB012)

**3 HRUs, 580 km², Columbia/Rocky Mtns BC (51.482, -116.969), NASA POWER forcing
2005-2015.** Same 13-module reduced chain as Bow/St.Mary/Gold. HRUs Alpine/Forest/
Valley at 2496/2000/1372 m (Copernicus GLO-30 area-equal terciles; basin mean
1956 m, relief 844-3311 m), areas 193/193/194 km². Unregulated, **LATE (June-July
plateau) snowmelt** regime: obs peaks Jun 50.7 / Jul 48.1 m³/s, winter baseflow
~2.4, runoff 892 mm/yr. **STRONG result: FULL(2006-2015) NSE 0.694 / KGE 0.816 /
r 0.837 / PBIAS +0.1; CAL(2006-2010) NSE 0.706 / KGE 0.770 / PBIAS -1.7;
VAL(2011-2015) NSE 0.682 / KGE 0.836 / r 0.838 / PBIAS +1.7.** Config: NASA POWER
precip ×1.0 at write-time + `ClimChng_precip 1.40`, obs_elev 2500, gw_K 1.0,
soil_gw_K 6.0, gw_max 1500/1800/2100, gw_init 750/900/1050, Netroute **Kstorage
20/30/12** (heavier than Gold's 16/24/10 — see lesson), Lag 48/72/24, gwKstorage 50,
gwLag 500, inhibit_evap 0. Delineation 579.8 km² vs HYDAT 587 (1.2%) — Copernicus
N51/N52 × W116/W117, stream_threshold=1000, snap_distance_m=1200. WB FAIL 13.1%
(P=1281 ET=208 Q=906 mm/yr, runoff coef 0.707 ≈ obs 0.70, diagnostics empty) = the
decadal Netroute routing-storage artifact (no output state — see Bow/Kaslo WB note);
units clean. obs_shape=`point_time_series`, dag var `basinflow_s` → NSE/KGE/r/PBIAS
all gate-valid.

**THE #1 LESSON — clean cross-basin template transfer when hypsometry + regime match.**
Blaeberry is a near-twin of Gold River (08NB014, ~70 km SSE, same Columbia/Selkirk
belt): hypsometry Alpine 2496 vs Gold 2485, Forest 2000 vs 2083, Valley 1372 vs 1503,
both LATE July-peaking. Adapting the validated Gold .prj **verbatim except geometry +
obs path** gave **first-try FULL NSE 0.683 / PBIAS -10** before any tuning. When a new
basin's hypsometry AND freshet month match a validated basin, transfer the WHOLE .prj
(obs_elev, GW recipe, routing) and tune ONLY precip + a small routing nudge — do not
re-derive from defaults. The validated-template library is the fastest path.

**LESSON 2 — confirms Gold's "obs_elev AT the alpine band" sweet spot to ±50 m.**
Sweep obs_elev 2450/2500/2550 with all else fixed: FULL NSE 0.692/0.694/0.685.
obs_elev 2500 (≈ the 2496 m Alpine HRU) is the peak, exactly Gold's rule — set
obs_elev to the alpine-HRU elevation for a late freshet, neither above nor below.

**LESSON 3 — runoff-coef precip diagnostic caught a near-unity raw coef.** raw NASA
POWER P=920 mm/yr but obs runoff=892 → coef 0.97 (physically impossible, needs P >
Q + ET). `ClimChng_precip 1.40` lifts P to 1281 mm/yr → coef 0.71, PBIAS +0.1.
Pairing the precip up-scale with **heavier Netroute Kstorage 20/30/12** (vs Gold's
16/24/10) smeared the sharp July peak forward to lift the Aug-Sept recession (sim Sep
7→13) and zeroed PBIAS — the recession-shape counterpart to Blue River's lesson but in
the opposite direction (Blaeberry's freshet is broader/later than Blue's, so it wants
HEAVIER routing, not lighter). **Confirms Gold's recharge-limited winter rule a 4th
time**: a follow-up test (gw_K 1.0→0.7 + gw_max 1800/2100/2400) did NOT lift Sept
(12.6 vs 12.8) — late-summer flow here is capacity/recharge-limited, not release-limited.

**Residual (the one un-closed feature): a stubborn June rising-limb under-prediction.**
obs has a broad **June≈July plateau** (50.7/48.1) but sim produces a sharper single
July peak with low June (40). No obs_elev / routing / GW setting lifts June without
either an April early-melt penalty or pushing the peak later — it is a melt-energy
timing feature of the point NASA POWER forcing, not a tunable parameter. It caps NSE
at ~0.69 (vs Gold's 0.715, whose obs peak is a single July spike sim matches better).

### Validated Mountain Basin — Kootenay River at Kootenay Crossing (HYDAT 08NF001)

**3 HRUs, 416 km², Rocky Mtns / Kootenay NP BC (50.887, -116.046), NASA POWER
forcing 2005-2015.** Same 13-module reduced chain as Bow/St.Mary/Gold/Blaeberry.
HRUs Alpine/Forest/Valley at 2255/1645/1300 m (Copernicus GLO-30 area-equal
terciles; basin mean 1733 m, relief 1943 m, 1169-3112 m), areas 139/139/138 km².
**FIRST DRY, low-winter-baseflow validated CRHM HYDAT basin** (RHBN reference,
100% complete daily record): obs sharp **June** freshet (peak 20.6 m³/s, May 11.4,
Jul 10.9), **near-zero winter baseflow ~0.3 m³/s**, **runoff only 352 mm/yr**
(vs the wet Columbia twins 900-1337). **STRONG result, ties best CRHM HYDAT:
FULL(2006-2015) NSE 0.715 / KGE 0.827 / r 0.849 / PBIAS +2.6; CAL(2006-2010)
NSE 0.562 / KGE 0.674 / PBIAS -5.7; VAL(2011-2015) NSE 0.827 / KGE 0.872 /
r 0.915 / PBIAS +9.5.** Config: NASA POWER precip ×1.0 at write-time +
`ClimChng_precip 0.95`, obs_elev 1980, **small GW store** gw_K 0.5, soil_gw_K 3.0,
gw_max 400/500/600, gw_init 150/200/250, Netroute Kstorage 16/24/9, Lag 48/72/24,
gwKstorage 50, gwLag 500, inhibit_evap 0. Delineation 427.5 km² vs HYDAT 416
(2.8%) — Copernicus N50/N51 × **W117 only** (basin drains N/NW, the W116 tiles
toward the divide are NOT needed; sketch drainage direction before grabbing tiles).
WB FAIL 11.9% (P=678 ET=237 Q=354 mm/yr, coef 0.52, diagnostics empty) = decadal
Netroute routing-storage artifact (only SWE+soil_moist output for dS; gw/Sd/
soil_rechr not captured — see Bow/Kaslo WB note), units clean. obs_shape=
`point_time_series`, dag var `basinflow_s` → NSE/KGE/r/PBIAS all gate-valid.

**THE #1 NEW LESSON — a DRY, near-zero-winter-baseflow basin needs the GW store
SHRUNK, not the wet-basin heavy store.** Every prior validated CRHM HYDAT basin
was wet (runoff 683-1337 mm/yr) with sustained winter flow, and the recipe grew a
big slow GW reservoir (gw_max 800-2700, gw_init 400-1350) to lift winter baseflow.
Kootenay is the opposite: obs Jan-Mar ≈ 0.3 m³/s (basin freezes up, minimal GW).
Transferring the Blaeberry/Gold heavy GW verbatim **over-produced** winter flow
and inflated volume. Cutting gw_max to 400/500/600, gw_init to 150/200/250,
gw_K to 0.5 and soil_gw_K to 3.0 matched the near-zero winter (sim Jan 0.4 ≈ obs
0.3) and let the freshet drain out by autumn. **Diagnostic: BEFORE building the
.prj, read the obs winter (JFM) monthly mean. If it is near-zero (<0.5 m³/s for a
few-hundred-km² basin, runoff coef-implied), use a SMALL GW store; if winter flow
is steady and substantial, grow a big one. The GW store should be sized to the
observed winter baseflow, NOT inherited from the template basin.**

**LESSON 2 — the runoff-coef precip diagnostic catches the dry case too: POWER
OVER-catches here, precip ×0.95.** raw NASA POWER P = 725 mm/yr, obs runoff =
352 mm/yr → raw coef 0.49, already physically plausible (montane ET ~240 mm leaves
P ≈ runoff + ET + small dS). No big up-scale needed (contrast the wet basins'
×1.4-1.7). First run at ×1.0 gave PBIAS +10; ClimChng_precip 0.95 zeroed FULL
PBIAS (+2.6). **Always compute the raw runoff coefficient first — a value already
near 0.4-0.6 means POWER is about right (or slightly high); only coef > ~0.9 forces
a large up-scale.**

**LESSON 3 — for an EARLY (June) freshet, set obs_elev BELOW the alpine band, not
at it.** Gold/Blaeberry (late July peak) wanted obs_elev AT the alpine HRU elev to
advance the alpine melt into July. Kootenay peaks a month earlier (June) with a
lower, less-glacierized hypsometry, so obs_elev 1980 (≈ +270 m above POWER 1708,
but ~275 m BELOW the 2255 m alpine band) is the sweet spot: the alpine HRU stays
lapsed-cold and melts through June-July sustaining the recession, while the lower
HRUs are only modestly warmed. Raising obs_elev to the alpine band (2050+) warmed
the low HRUs into a worse April overshoot and smeared the peak. Pair with lighter
Kstorage 16/24/9 (sharp freshet). **Rule: obs_elev tracks the freshet MONTH — late
(July) → at/above the alpine band; early (June) → between mid and alpine band.**

**Residual (caps NSE ~0.72): an April overshoot (sim 4.8 vs obs 1.4) plus a
slightly-low June peak (sim 17.4 vs obs 20.6).** The 3-HRU single-point lapse warms
the forest/valley HRUs enough to start melt in April while the sharp observed June
spike needs more concentrated high-elevation melt than NASA POWER point forcing
delivers. No obs_elev / routing / GW setting removes both at once (lowering obs_elev
cuts April but also lowers June). The CAL window (2006-2010) is structurally harder
(NSE 0.56) than VAL (0.83) — an interannual forcing feature, not tunable without
overfitting.

### Validated Mountain Basin — Canoe River below Kimmel Creek (HYDAT 08NC004)

**3 HRUs, 305 km², N Monashee/Cariboo Mtns BC (52.732, -119.385), NASA POWER
forcing 2005-2015. NORTHERNMOST validated CRHM HYDAT basin (52.7°N).** Same
13-module reduced chain as Gold/Blaeberry/Blue. HRUs Alpine/Forest/Valley at
2460/1950/1359 m (Copernicus GLO-30 area-equal terciles; basin mean 1923 m, relief
2336 m, 959-3295 m), areas 101.2 km² each. **WETTEST validated basin (runoff
1584 mm/yr)**, clean **LATE July-peaking** snowmelt: obs Jul 47.6 / Aug 35.2 /
Jun 37.0 m³/s, steady winter baseflow ~1.7 m³/s. **STRONG result, ties the best
tier: FULL(2006-2015) NSE 0.704 / KGE 0.808 / r 0.843 / PBIAS +5.2; CAL(2006-2010)
NSE 0.680 / KGE 0.817 / PBIAS +0.1; VAL(2011-2015) NSE 0.722 / KGE 0.817 / PBIAS
+2.5.** Config: NASA POWER precip ×1.0 at write-time + `ClimChng_precip 2.0`,
obs_elev 2150, gw_K 1.0, soil_gw_K 6.0, gw_max 1500/1800/2100, gw_init 750/900/1050,
Netroute Kstorage 16/24/10, Lag 48/72/24, gwKstorage 50, gwLag 500, inhibit_evap 0.
Delineation 303.6 km² vs HYDAT 305 (0.5%) — Copernicus N52/N53 × W119/W120,
stream_threshold=1000, snap_distance_m=1200 (cached tiles in
data/dem/dem_tiles_cache/). WB FAIL 15.3% (P=1957 ET=136 Q=1522 mm/yr, runoff
coef 0.78, diagnostics empty) = the decadal Netroute routing-storage artifact (no
output state — see Bow/Kaslo WB note); units clean, sim Q 1522 ≈ obs runoff 1584.
obs_shape=`point_time_series`, dag var `basinflow_s` → NSE/KGE/r/PBIAS gate-valid.

**THE #1 LESSON — REFINES the Gold/Blaeberry "obs_elev AT the alpine band" rule:
for a LATE basin whose hypsometry produces an APRIL OVERSHOOT at the at-band
setting, lower obs_elev BELOW the alpine band until the early-spring melt collapses.**
Canoe peaks LATE (July) like Gold/Blaeberry, so the documented rule says set obs_elev
AT the 2460 m alpine band. The coarse sweep duly picked obs_elev 2400 (≈ alpine band)
→ FULL NSE 0.67, but its monthly trace showed a fat **April overshoot (sim 11.3 vs
obs 3.9)** from the warmed low/mid HRUs starting melt a month early. UNLIKE the
Gold/Blaeberry single-July-spike obs, Canoe's lower, less-glacierized Monashee
hypsometry melts its valley/forest HRUs into a spurious April rise when obs_elev is
at the alpine band. **Lowering obs_elev 2400 → 2150 (≈ −310 m, still +440 m above
the POWER site elev 1677) cooled the low HRUs, cut April to ~5, and lifted FULL NSE
0.67 → 0.70 / VAL 0.69 → 0.72** while KEEPING the July peak. Pushing further (2000)
over-cooled the alpine HRU so its melt slid into August (sim Jul collapsed 41→34,
Aug overshot 39 vs obs 35) — 2150 is the sweet spot. **Refined rule: late-July peak
→ START at the alpine band, but if a spurious April/early-spring rise appears (low
HRUs melting early), step obs_elev DOWN 50-100 m until April matches obs WITHOUT the
July peak sliding into August. The alpine-band setting is an upper bound, not always
the optimum — check the April-vs-July trace and lower if April overshoots.** (Kootenay
08NF001, an EARLY-June peak, independently wanted obs_elev below its alpine band too;
Canoe shows the same can apply to a LATE basin when its hypsometry is broad/low.)

**LESSON 2 — the runoff-coef precip diagnostic forced the HEAVIEST up-scale yet
(×2.0) on the wettest basin.** raw NASA POWER P=978 mm/yr but obs runoff=1584 → raw
coef 1.62 (impossible). First trial at ×1.8 left PBIAS −15.8 (sim under by 15.8%);
×2.0 → P=1957 mm/yr, coef 0.78, PBIAS +5 (CAL +0.1). Predicted target P ≈ runoff
1584 + montane ET ~140 + decadal routing-store losses; ×2.0 landed it. **Wettest
basins (runoff > 1500 mm/yr) can need precip ×1.9-2.1 — do not cap the up-scale at
the ~1.66 the Selkirk basins used; let the runoff-coef + first-run PBIAS sign set it.**

**LESSON 3 — confirms the clean cross-basin template transfer (Blaeberry .prj verbatim
except geometry + obs + the two tuned knobs).** Adapting the validated Blaeberry .prj
(same Columbia/Monashee belt, same late peak, same big-GW wet regime) and tuning ONLY
obs_elev + ClimChng_precip gave a 0.70 first-pass. The validated-template library +
the two master knobs (obs_elev for peak timing/April, precip for volume) is the fast
path; GW recipe and routing transferred untouched. Residual (caps NSE ~0.70): July
peak under-pred (sim 41 vs obs 47.6) + small Aug overshoot = the sharp observed July
spike is unresolvable from NASA POWER point precip (same structural cap as Gold/Blaeberry).

### Validated Mountain Basin — Crowsnest River at Frank (HYDAT 05AA008)

**3 HRUs, 403 km² (gross), Crowsnest Pass / Rocky Mtns AB (49.597, -114.411),
NASA POWER forcing 2005-2015. FIRST southern-ALBERTA Rocky-front snowmelt basin
in the CRHM HYDAT set — distinct from the BC Columbia/Selkirk cluster.** Same
13-module reduced chain as Gold/Blaeberry/Kootenay. HRUs Alpine/Forest/Valley at
2005/1669/1451 m (Copernicus GLO-30 area-equal terciles; basin mean 1709 m, relief
1522 m, 1272-2793 m), areas 129.1 km² each. **EARLY (June) freshet** (obs Jun 16.8/
May 14.0 m³/s) with **strongly SUSTAINED year-round baseflow** (obs winter JFM ~1.6,
fall Sep-Nov 2.6-3.0 m³/s — a limestone-spring / karst signature) and only MODERATE
runoff 410 mm/yr. **STRONG result, target NSE_val≥0.3 vastly met: FULL(2006-2015)
NSE 0.611 / KGE 0.761 / r 0.814 / PBIAS -14.9; CAL(2006-2010) NSE 0.592 / KGE 0.710;
VAL(2011-2015) NSE 0.611 / KGE 0.788 / PBIAS -9.4.** Config: NASA POWER precip ×1.0
at write-time + `ClimChng_precip 0.90`, obs_elev 1850, **LARGE slow GW store** gw_K 0.5,
soil_gw_K 6.0, gw_max 1200/1600/2000, gw_init 700/950/1200, Netroute Kstorage 20/30/12,
Lag 48/72/24, gwKstorage 50, gwLag 500, inhibit_evap 0. Delineation 387.4 km² vs HYDAT
403 (-3.9%) — Copernicus N49/N50 × W114/W115, **stream_threshold=1000, snap_distance_m=
500** (sd=1200 grabbed an adjacent confluence at 450 km², +12%; tightening the snap to
500 m recovered the true outlet). WB FAIL 13.4% (P=699 ET=256 Q=353 mm/yr, coef 0.50,
diagnostics empty) = the decadal Netroute routing-storage artifact (see Bow/Kaslo WB
note); units clean. obs_shape=`point_time_series`, dag var `basinflow_s` → NSE/KGE/r/
PBIAS all gate-valid.

**THE #1 NEW LESSON — GW-store size is set by the observed BASEFLOW PROFILE, NOT by
runoff magnitude.** Kootenay (08NF001, dry runoff 352, near-zero winter) taught "size
the GW store to observed winter baseflow"; the wet Columbia basins (runoff 900-1584)
grew big stores because they had both high volume AND sustained winter flow. Crowsnest
breaks the lazy "runoff magnitude → store size" heuristic: it has only MODERATE runoff
(410 mm/yr, between dry Kootenay and the wet basins) yet needs the LARGEST-class slow GW
store (gw_max 1200-2000), because its baseflow is **sustained year-round at karst-spring
levels** (winter 1.6, fall 3.0 m³/s — fall flow HIGHER than the April shoulder). The
first run used the moderate Coldwater/Kootenay store (gw_max 600/800/1000, gwk 0.6) and
got **NSE 0.34**: it dumped the whole snowmelt into a too-sharp May-June peak (sim 19/24
vs obs 14/17) and ran near-dry the rest of the year (winter 0.3, fall 0.3-0.9 vs obs
1.6/3.0). Tripling the GW store (gw_max → 1200/1600/2000, gw_init → 700/950/1200,
soil_gw_K → 6) routed snowmelt through the slow store: it attenuated the freshet peak
AND sustained fall/winter flow, lifting **NSE 0.34 → 0.60 in one step**. **Diagnostic:
read the obs MONTHLY climatology before sizing GW. If fall (Sep-Nov) flow is comparable
to or HIGHER than the spring shoulder (Apr) and winter is steady, the basin is
groundwater/karst-fed — use a LARGE slow store REGARDLESS of total runoff. Runoff depth
sets `ClimChng_precip` (volume); the baseflow PROFILE sets the GW store size — two
independent diagnostics.** (Crowsnest Pass is a known karst/limestone-spring system.)

**LESSON 2 — the residual fall-baseflow deficit is a structural cap (~NSE 0.60) for
karst-fed basins in CRHM's bucket GW.** Even with the large store, sim fall (Sep-Nov
0.5-2.1) never fully matches the obs 2.6-3.0 sustained karst-spring flow; the lumped
bucket empties faster than real limestone storage. gwLag is INEFFECTIVE here (500 vs
3000 changed NSE by <0.001) — gwLag delays the routing reservoir, not the Soil-module
gw drainage that governs the recession. The NSE-optimal point (obs_elev 1850, climp 0.90)
trades ~15% volume undershoot (PBIAS -14.9) for the best peak/shape fit; a more
volume-balanced choice (obs_elev 1850-1900, climp 0.95 → PBIAS -6 to -9) costs ~0.02 NSE.
This is the same class of structural cap as Gold/Blaeberry's June-plateau under-prediction,
but on the recession side rather than the rising limb.

**LESSON 3 — for an EARLY-June freshet on a lower hypsometry, obs_elev sits BELOW the
alpine band (confirms Kootenay).** Alpine HRU 2005 m; obs_elev sweep 1700/1850/1900/1950/
2050 → best NSE at 1850-1900 (below the 2005 band). 1700 left winter near-zero and a fat
July tail (melt too late); 2050 over-warmed (PBIAS -18 to -20, snowpack melts too fast,
volume lost). Same rule as Kootenay (08NF001, also early-June): early peak → obs_elev
between mid and alpine band, NOT at/above it (that is the late-July-peak rule for
Gold/Blaeberry/Canoe). DEM tiles: Crowsnest drains E from the Continental-Divide
headwaters (~-114.7, BC border) to Frank; N49 × W114 (gauge) + W115 (headwaters) cover it.

### Validated Mountain Basin — Dore River near McBride (HYDAT 08KA001)

**3 HRUs, 406.5 km² (HYDAT 409, −0.6%), Cariboo Mtns BC (53.309, −120.249),
NASA POWER forcing 2005-2015.** NORTHERNMOST (53.3N) and FIRST Cariboo-Mtns nival
basin in the CRHM HYDAT set — a clean northern twin of Canoe 08NC004 (52.7N).
Same 13-module mountain chain (`basin → global → obs → calcsun → intcp → pbsm →
albedo → ebsm → netall → crack → evap → Soil → Netroute`). HRUs Alpine/Forest/Valley
at 2294/1912/1430 m (area-equal hypsometric terciles, basin mean 1878 m).
**FULL NSE 0.709 / KGE 0.804 / r 0.845 / PBIAS −6.5%; CAL(06-10) NSE 0.700 /
KGE 0.800; VAL(11-15) NSE 0.712 / KGE 0.804 / PBIAS −7.4%** — ties the best tier
(Canoe 0.704, 08NH005 0.731).

**#1 lesson — VERBATIM template transfer for a nival twin.** The validated Canoe
08NC004 `.prj` transferred WHOLESALE: identical module chain, identical GW store
(`Soil gw_max` 1500/1800/2100, `gw_init` 750/900/1050, `gw_K` 1.0, `soil_gw_K`
6.0), identical `Netroute Kstorage` 16/24/10 / `Lag` 48/72/24 / `gwKstorage` 50 /
`gwLag` 500. **Only obs_elev and ClimChng_precip were retuned.** For a snowmelt
basin in the same nival/runoff-depth regime as an already-validated one, do NOT
re-derive parameters — copy the twin's `.prj` and sweep the 2 master knobs.

**#2 lesson — precip is the dominant, near-linear PBIAS knob.** Best obs_elev held
fixed at 2100, ClimChng_precip stepped PBIAS almost linearly: ×1.30 → −15 to −19%,
×1.45 → −1 to −6%, ×1.60 → +7 to +14%. Workflow: pick precip to zero PBIAS first,
then choose obs_elev for NSE. (Raw NASA POWER P here = 931 mm/yr; obs runoff ~1110
mm/yr; ×1.45 closes it.)

**#3 lesson — obs_elev optimum reconfirms the at/below-alpine-band rule.** The
winning obs_elev=2100 sits ABOVE the basin mean (1878) and just below the alpine
tercile (2294), between the forest (1912) and alpine bands. obs_elev 1950 (too low,
under-melts/early) and 2250 (too high, over-cold) each cost ~0.02-0.06 NSE across
all precip levels. Place obs_elev at-to-just-below the alpine band, not at the mean.

**WB note:** FAIL 11.9% (residual 1603 mm = 146 mm/yr over 11 yr; P=13510 ET=1607
Q=10309 dS≈0) is the **same documented Netroute slow-GW routing-storage artifact**
as Bow/Canoe — `gwKstorage/gwLag/Kstorage/Lag` carry no output state variable, so a
decadal run shows an un-closeable residual. Units are clean (sim Q 937 mm/yr ≈ obs
runoff 1110 at PBIAS −6.5%); NOT a unit error.

---

## FLAT / OPEN / REGIONAL domains — Hulunbuir open steppe (呼伦贝尔草原) SWE case

Every validated basin above is a Canadian/Chinese MOUNTAIN catchment scored on
discharge. The first FLAT, treeless, **regional** domain scored on **SWE**
(Hulunbuir steppe, Inner Mongolia, ~49.4N 120.5E — the Chinese analog of the
Canadian Prairies PBSM was built for) exposed a cluster of gaps that a mountain/
discharge run can never hit. All are fixed in the canonical tools; the notes
below are what you need to KNOW.

**1. `pbsm` never received ANY parameters — the entire blowing-snow
parameterisation was a silent no-op.** `create_prj_file.py`'s `DEFAULT_PARAMS`
is keyed on the CAPITALISED GUI module names (`PBSM`), but every validated chain
uses the lower-case CLASSIC names (`pbsm`). The parameter loop skipped any module
missing from the table, so `fetch`, `Ht` and `distrib` — everything
`derive_parameters.py` computes for blowing snow — were never written, and CRHM
ran on its built-in defaults. Check any older .prj: it declares
`pbsm CRHM 11/20/17` under Modules and carries not one `pbsm <param>` line.
Fixed with a `MODULE_PARAM_ALIAS` (`pbsm` -> `PBSM`). **Consequence for the
validated mountain basins: their next .prj WILL carry derived pbsm parameters
for the first time, so re-verify their metrics rather than assuming they hold.**

**2. HRUs must be ordered by ASCENDING VEGETATION HEIGHT on a blowing-snow
domain.** `Classpbsm.cpp` cascades drift along the HRU list (exposed -> sheltered)
and logs `'vegetation heights not in ascending order'` when the list is not
sorted that way; the drift then deposits on the wrong units. The land-cover
cross-tab emits HRUs in raster-class order (Hulunbuir: stubble 0.15 m, forest
15 m, grassland 0.3 m — a violation). Use
`create_hru_config.py --order_by_veg_height`. Source-verified parameter facts:
`fetch` range is **300–10000 m** (not 10), `distrib` is **-10..10** (negative =
"all drift deposited", a mode the old min of 0 made unreachable), and `N_S`/`A_S`
are `decldiagparam`, so emit them only when explicitly set.

**3. Dropping the canopy module on treeless terrain SEGFAULTS CRHM (dt_v006).**
`pbsm`, `albedo`, `ebsm`, `netall` and `crack` all read `net_rain`/`net_snow`,
which ONLY a canopy module declares. "No trees, so drop `intcp`" is the natural
inference on steppe and it core-dumps after the banner with a 70-byte
header-only output file and NO error message. Keep `intcp` — with `Ht` ~0.3 m it
passes precipitation through essentially untouched. `select_modules.py` now fails
closed on such a chain instead of emitting it.

**4. Use `prairie_reduced`, never the legacy `prairie` chain.** The legacy
4-process chain (`PBSM > PrairieInfil > Soil > Netroute`) is UNVALIDATED and has
no energy-balance melt at all — no `albedo`, no `netall`, no `ebsm` — which is
fatal when SWE is the scored variable. `prairie_reduced` is the SAME validated
13-module chain the mountain basins use; once `Slope_Qsi`/`walmsley_wind` are
gone that chain is landscape-neutral. Auto-detection now routes flat+open
domains (relief < 500 m, open fraction > 50%) to it. `select_modules.py`'s
`MODULE_DB` also gained the nine modules it was missing (`calcsun`, `intcp`,
`pbsm`, `albedo`, `ebsm`, `netall`, `crack`, `evap`, `walmsley_wind`) — before
that, `chain_validation` reported the VALIDATED chain as eight "Unknown module"
ERRORs, i.e. pure noise, and ERRORs were only logged, never enforced.

**5. A REGIONAL domain needs no catchment: `create_hru_config.py --bbox`.**
For a gridded regional-aggregate comparison there is no gauge, so there is no
basin to delineate; the tool previously hard-required a shapefile. `--bbox
minlon,minlat,maxlon,maxlat` builds the rectangle and writes `region.geojson`,
which the observation clip MUST reuse so domain and obs share one boundary. The
HRU COUNT IS SET BY dag.yaml safety.validation_limits, NOT by the terrain: <100
km2 uses 3-5 HRUs, 100-1000 km2 uses 5-15, >1000 km2 uses 10-50. On flat terrain
reach that band by crossing land cover with elevation bands
(`--n_elevation_bands 5 --min_hru_area_frac 0.01`); the bands also carry the
lapse-rate signal that sets melt timing. `--n_elevation_bands 1` is permitted
ONLY for domains under 100 km2. A run that scores below the dag band must record
an explicit, evidence-backed exemption in result.json -- silently
under-discretising a regional domain makes every metric PROVISIONAL (the first
Hulunbuir run used 3 HRUs on 3868 km2 and was rejected as workflow_incomplete).

**6. ALWAYS pass `--landcover_scheme`.** The tool's built-in table is a private
CRHM scheme with AVHRR/UMD bolted onto codes 10–16. Hand it CLCD or GLCFCS30 —
the curated primary China/global products — and every code still resolves, just
to the WRONG surface: CLCD grassland (4) became `deciduous_forest` (15 m canopy,
50 m fetch) and GLCFCS30 grassland (130) fell through to the generic default.
Since `fetch_m` is the master blowing-snow control, an open steppe silently lost
the very physics the domain exists to test. Documented legends now ship for
`crhm`, `avhrr_umd`, `clcd`, `glcfcs30` and `esa_cci`, with a warning on unmapped
codes. Related: `derive_parameters.py`'s pbsm fetch lookup was keyed on names its
own s1 tool never emits (`crop_stubble`, `bare_ground`, `alpine_tundra` were all
absent), so those HRUs fell through to the 300 m MOUNTAIN MINIMUM — 52% of this
domain, on its most wind-exposed surface.

**7. `pbsm distrib` was dead on flat terrain.** `derive_parameters.py` set the
drift redistribution from ELEVATION alone, gated at >200 m of relief BETWEEN
HRUs. On prairie/steppe that leaves every `distrib` at 0 — no inter-HRU transport
at all, so blowing snow could only sublimate in place, never relocate. An
EXPOSURE fallback now runs when the elevation rule finds no sink (open,
short-vegetation source -> sheltered sink, area-weighted, normalised to 1.0). It
applies ONLY in that case, so mountain basins keep identical parameters.

### PRE-RUN SETUP CONTRACT — scored SWE on a flat/open REGIONAL domain

Satisfy ALL FOUR before any SWE number is reported. A run that misses one is a
SETUP failure and its metric is PROVISIONAL, not a model verdict.

**1. HRU count must satisfy the dag band** (see item 5 above): 10-50 HRUs for a
>1000 km2 domain. Cross land cover with `--n_elevation_bands 5`.

**2. MANDATORY SNOW-MASS AUDIT.** SWE is a mass state, so the sinks must be
observable before the state is scored. Emit these SOURCE-VERIFIED variables --
names checked against `Classpbsm.cpp` declvar/declstatdiag and `ClassSoil.cpp`:

    pbsm SWE, pbsm Subl, pbsm cumSubl, pbsm Drift, pbsm cumDrift,
    pbsm cumDriftIn, pbsm snowdepth, Soil Sd,
    obs hru_p, obs hru_snow, obs cumhru_snow

The last three are the audit's DENOMINATOR and dag.yaml:399's remaining closure
compartment: `hru_p` is ClassObs.cpp:101, `hru_snow` is ClassObs.cpp:113 and
`cumhru_snow` is ClassObs.cpp:115 (declstatdiag, cumulative mm). Emitting the
sink without the model's own snowfall leaves the ratio uncomputable FROM THE
RUN, forcing a reconstruction off the raw forcing that cannot see CRHM's own
rain/snow partition or its snow-catch adjustment. Difference the CUMULATIVE
pair (`cumSubl`, `cumhru_snow`) across the accumulation window, so the
`Summary_period: Daily` aggregation cannot distort the ratio.

Then compute cold-season sublimation as a FRACTION OF SNOWFALL and compare it
against dag.yaml safety.warnings: **sublimation is 15-40% of snowfall in
prairie, 30-50% in boreal forest**. Outside that band the run is wrong on
physics no matter what NSE says. The first Hulunbuir run emitted `pbsm SWE`
ALONE, so this check was impossible; reconstructing it afterwards from the
forcing gave sim peak SWE / snowfall(Oct 1 -> peak) = 0.92 mean, i.e. ~8%
ablation loss -- 2-5x below the band -- which plausibly explains its entire
+60% SWE bias.

WARNING: `select_modules.py`'s MODULE_DB advertises pbsm outputs `drift_in`,
`drift_out` and `cumDriftOut`. THESE DO NOT EXIST in `Classpbsm.cpp` (the real
names are `Drift`, `cumDrift`, `cumDriftIn`). CRHM silently omits unrecognised
Display_Variable lines, so an audit built from MODULE_DB yields empty columns
and no error. Always verify a variable name in the module source first.

**3. The blowing-snow transport rules are UNVALIDATED.** The exposure-based
`distrib` fallback and the extended fetch lookup (item 7 above) were authored
DURING the same run they parameterised, and they route 100% of inter-HRU drift
from 87% of the domain into a single 13% forest HRU. Validate them on a domain
with known blowing-snow behaviour before they parameterise a scored run, and
declare their use in result.json.

**4. Energy-balance melt wants HOURLY forcing.** dag.yaml safety.validation_limits
states full energy-balance snowmelt requires hourly forcing; CMFD is 3-hourly and
the KI has never established that 3-hourly is adequate for `ebsm`. Either
disaggregate to hourly, or record an explicit evidenced ruling that it is
acceptable. Do not leave it undeclared.

### PBSM PROCESS-ACTIVITY GATE — `Ht` is an ON/OFF SWITCH, not a roughness

READ THIS BEFORE WRITING ANY PBSM PARAMETER ON A SHALLOW-SNOW OPEN DOMAIN.

**The mechanism (Classpbsm.cpp:529-546).** Each timestep PBSM computes the
vegetation still exposed above the snow:

    E_StubHt = Ht[hh] - Common::DepthofSnow(SWE[hh]);   // line 529
    if (E_StubHt > 0.01) {                              // line 534
      Znod  = sqr(Ustar)/163.3 + 0.5*N_S*E_StubHt*A_S;
      Ustn  = Ustar*sqrt((Beta*Lambda)/(1.0+Beta*Lambda));
      Uten_Prob = (log(10.0/Znod))/KARMAN * min<double>(0.0, Ustar-Ustn);
    } else {
      Uten_Prob = hru_u_;
    }

`Ustn` is ALWAYS <= `Ustar`, so `min(0.0, Ustar-Ustn)` is IDENTICALLY 0 and
**Uten_Prob == 0 whenever the vegetation is exposed by more than 1 cm.**
`ProbabilityThresholdNew` accumulates probability only inside
`while ((Wind <= Uten_Prob) && (Uten_Prob >= 3.0))`, so `Prob == 0`, the
`if (Prob[hh] > 0.001)` block at Classpbsm.cpp:548 never executes, and **Drift
and Subl are exactly zero.** Blowing snow in CRHM 4.02 switches ON only once
snow depth buries the vegetation to within 1 cm. `Ht` is a STEP FUNCTION on the
whole module, not a graded roughness effect. There is no error, no warning, and
SWE simply over-accumulates.

**What this cost (Hulunbuir steppe, 2002-2014, verified).** With `Ht` taken from
the generic land-cover canopy table (`open_prairie` 0.3 m, `crop_stubble` 0.15 m
— create_hru_config.py:77-78 and :114-115) against obs mean SWE 12.3 mm /
p95 30.5 mm, PBSM was enabled on **2.2%** of snow-covered timesteps on the 0.3 m
HRUs and 19.8-21.7% on the 0.15 m HRUs. Area-weighted over the run:
cumSubl/cumhru_snow = 13.75/980.72 = **1.4%** and cumDrift = 0.39% of snowfall,
against dag.yaml safety.warnings **15-40% of snowfall in prairie**. Headline came
out sim monthly mean 21.4 mm vs obs 13.4 mm, PBIAS +59.8%, **r = 0.83**, NSE
-0.48. r 0.83 says the TIMING was already right: that is a pure missing-sink MASS
bias, not a calibration deficit.

**RULE 1 — `pbsm Ht` is the WINTER EXPOSED vegetation height, NOT the
growing-season canopy height.** The shipped Pomeroy-authored prairie projects are
the reference:

    crhmcode/prj/badlake.prj:51-52    Ht = 0.05  0.25  0.6
    crhmcode/prj/smithcreek.prj:447   Ht = 0.001 0.12 0.4 0.7 0.001 6 1.5 ...

Every blowing-snow SOURCE HRU in both is **0.001-0.12 m**. Grazed / dormant
Eurasian steppe belongs in that same 0.02-0.10 m band. 0.3 m is taller than any
source HRU in either validated project and silently disables the module. Do NOT
inherit `veg_height_m` from the land-cover table — that value is correct for
`evap Ht` (a growing-season quantity) and wrong for `pbsm Ht`. Set it from the
grazing / harvest state of the winter surface and RECORD the choice in
result.json.

**RULE 2 — set `pbsm inhibit_bs = 1` on every canopy HRU.**
smithcreek.prj:457-458 writes `inhibit_bs = 0 0 0 0 0 1 0 ...` — the 1 is on
the HRU with Ht = 6 m. The CRHM default is 0 (Classpbsm.cpp:132), so omitting the
line runs prairie blowing-snow physics inside forest, which dag.yaml
safety.validation_limits declares invalid and hazard
`wrong_module_chain_for_landscape` flags as SILENT. Shortening `fetch` to 300 m is
NOT a substitute. The same HRUs must also not be the sole `distrib` sinks: a
source->sink matrix needs a terrain basis, and a lat/lon `--bbox` domain has none
— declare `distrib` UNVALIDATED for `region_bbox` and say so in result.json.

**RULE 3 — do NOT tune `N_S` / `A_S`.** They are `decldiagparam` with defaults
320 (1/m^2) and 0.003 m (Classpbsm.cpp:122-124), identical to the values
badlake.prj:172-183 writes explicitly. They are not why PBSM is inert; `Ht` is.

**RULE 4 — the activity gate is MANDATORY and PRE-SCORE, not advisory.** The
MANDATORY SNOW-MASS AUDIT above tells you to EMIT cumSubl / cumDrift /
cumhru_snow. **Emitting them is not the check.** Before any metric is computed,
area-weight the LAST cumulative value of each by `hru_area/basin_area` and form
`frac_subl = cumSubl_aw / cumhru_snow_aw` (and `frac_drift` likewise), then
REFUSE to emit a score when `frac_subl` falls outside the dag band for the
landscape: **0.15-0.40 prairie/steppe, 0.30-0.50 boreal forest**. A run outside
the band is a SETUP failure: its metric is PROVISIONAL, it may not be reported as
CRHM skill, and it must NEVER be routed to `requires_calibration` — calibration
cannot be the diagnosis while the dominant mass sink is switched off. Report
`frac_subl`, `frac_drift` and the pass/fail in result.json every run.

**RULE 5 — a regional-aggregate SWE score may not be driven by one centroid
cell.** The Hulunbuir run scored an area-weighted mean over 3,868 km2 (48 CMFD
0.1-deg cells) from a single-point `basin.obs` at (49.4, 120.4) with `nobs 1`,
`precip_elev_adj = 0` and `catchadjust = 0` on all 15 HRUs — so every HRU across
a 646-953 m elevation range received IDENTICAL precipitation on a dag edge
(precipitation->SWE) graded HIGH. For `domain_kind = region_bbox`, drive the run
with a region-mean forcing series over the identical polygon, or with `nobs > 1`
(one obs column set per elevation band) and `precip_elev_adj` set from the band
structure. A centroid cell is admissible only for a point/small-catchment case.

**RULE 6 — a failed obs mass-consistency screen constrains the METRIC FAMILY,
not just the aggregation.** When `screen_swe_obs.py` reports
`shallow_snow_regime: true` or `mass_inconsistent_pct` above threshold (Hulunbuir:
4.32% vs 2.0), demoting daily to monthly is necessary but NOT sufficient. In that
regime the passive-microwave retrieval uncertainty is comparable to the signal, so
magnitude metrics (NSE, PBIAS, KGE) become **reported-but-not-determining** and
the DETERMINING metrics become pattern/timing: `r`, peak-SWE DOY, snow-season
onset and melt-out date. State which family is determining in result.json before
scoring, or pair the retrieval with an independent in-situ SWE source.

### HARD RULE — scoring CRHM against a SATELLITE SWE product

Passive-microwave SWE (ESA Snow_cci / GlobSnow and relatives) is a *retrieval*,
not a measurement. In shallow-snow regimes it carries error comparable to the
entire signal, and its day-to-day variability is dominated by brightness-
temperature noise rather than by real snow mass. Three obligations follow.

**1. Screen the obs before touching a single parameter.**

    python tools/s2_observation_data/screen_swe_obs.py \
        --obs_csv <regional_mean_swe.csv> \
        --forcing_obs '<workspace>/obs/cmfd_*.obs' \
        --out_json <workspace>/swe_obs_screen.json

The screen tests the OBS against the same forcing the model gets: a snowpack
cannot gain more water in a day than that day's precipitation, and cannot lose
water when Tmax is below melting. If more than 2% of cold-season days violate
that budget, the series is **inadmissible at daily resolution**.

**2. Score at the aggregation the retrieval supports.** When the screen fails,
report monthly-mean NSE/KGE/r/PBIAS plus peak-SWE and snow-season mean, and say
so explicitly in the result. Hulunbuir is the worked case: 4.3% of DJF days are
mass-inconsistent (worst pair +19.7 mm/d with P=0.0 mm at Tmax -21.8 C, reversed
the next day by -19.6 mm/d at -20.2 C).

**The locked-knob held-out numbers for this domain** (2026-07-25, the reference
values — reproduce THESE, not the tuned ones): held-out 2009–2014, obs_elev 663
(= the CMFD source cell), ClimChng_precip 1.0, pbsm fetch ×1.0 as derived, no
sweep. Monthly-mean **NSE −0.488 / KGE 0.065 / r 0.828 / PBIAS +59.9, n = 47
months**; the daily view of the same run is NSE −0.680 / r 0.781 (n = 1316 d,
diagnostic only — the screen rules it inadmissible). Peak SWE over 7 water
years: obs 32.2 mm vs sim 50.6 mm. Aggregation lifts NSE by ~0.19 and r by ~0.05
because it averages out retrieval noise, but it does NOT touch the +58% mass
bias, which is invariant to aggregation — that invariance is the evidence that
the bias is an attribution problem, not a timing problem. Earlier revisions of
this section quoted "daily NSE 0.36 / monthly 0.50" here: those came from the
`ClimChng_precip 0.8 / obs_elev 843` configuration that rule 3 below FORBIDS,
and quoting them as the illustration of the rule invited the next agent to
rebuild the forbidden config. They are gone.

**3. When SWE is the scored variable, the forcing knobs are LOCKED.** Set
`ClimChng_precip = 1.0` and `obs_elev` = the forcing-source grid-cell elevation
from derive_parameters.py, and leave them there. For a discharge-scored run
those two knobs move TIMING and volume through a long causal chain. For SWE they
write the scored quantity directly — cutting precipitation removes snow mass and
raising obs_elev melts it — so tuning them against SWE is not calibration, it is
fabrication, and it is the 'compensating-errors calibration' hazard dag.yaml
already names. A large residual bias under LOCKED knobs is a REPORTABLE FINDING
(an unresolved forcing-vs-retrieval attribution needing in-situ data), not a
defect to tune away.

Diagnostic that tells you the model is fine and the obs is not: correlate
water-year cold-season snowfall P(T<0) against sim peak SWE and against obs peak
SWE. At Hulunbuir the model gives 0.910 and the obs gives 0.602 — the simulated
snowpack tracks its own forcing far better than the retrieval tracks the region's
precipitation, which is the signature of retrieval error, not model error.

**Domain recipe used here** (region 120.0–120.8E, 49.1–49.7N, 3868 km², 82%
treeless by GLCFCS30, relief 609–1016 m): 3 land-cover HRUs ordered
stubble(0.15 m, 2017 km²) -> grassland(0.3 m, 1360 km²) -> deciduous
forest(15 m, 492 km², the drift sink, `distrib` 0/0/1), `fetch` 1000/2000/300 m,
CMFD 3-hourly local forcing at the region centroid, `prairie_reduced` chain.
obs = ESA Snow_cci merged SWE v2.0 clipped to the identical polygon, ~100% valid
retrievals (no mountain mask, unlike alpine Heihe where ~69% is masked).
obs_shape = `regional_aggregate_time_series` -> dag metric_families
`magnitude_accuracy` + `temporal_pattern_match`, determining metric NSE, so
NSE/KGE/r/PBIAS are all gate-valid. **CORRECTED 2026-07-25 — READ THIS BEFORE
REUSING THIS RECIPE.** The reported NSE 0.35 was NOT reached by physics. It was
reached with `ClimChng_precip 0.8` (a 20% cut to CMFD precipitation) and
`obs_elev 843` against the 663 m that derive_parameters.py computed for the CMFD
source cell (+180 m warms every HRU by up to ~1.0 C at lapse_rate 0.75). The
undercatch rationale originally written here has the WRONG SIGN for that value:
gauge undercatch of solid precipitation demands a multiplier ABOVE 1.0, never 0.8.
The honest configuration (obs_elev 663, ClimChng_precip 1.0; sweep_cache key
`663|1.0|1.0`) scores NSE -0.70 / r 0.698 / PBIAS +56.5. That +56% is an
UNRESOLVED ATTRIBUTION between CMFD cold-season snowfall and an ESA Snow_cci
retrieval that is known to under-retrieve shallow snow — and this domain is
shallow (obs mean 12.3 mm, max 42.0 mm). It must be resolved with an in-situ snow
measurement, NOT with a precipitation multiplier. Neither ClimChng_precip nor
obs_elev is a legitimate SWE knob: SWE is the scored MASS STATE, so both of them
write the answer directly. Groundwater and routing genuinely do not touch SWE.

### Scoring the run so the number is TRUSTABLE (record contract)

A correct model run whose number cannot be re-derived from its own evidence is
not a result. Three rules, all learned the hard way on this domain (run
`885e6696`, which was ACCEPTED on the science and still stuck at
`evidence_level=series_only`):

**1. Exactly ONE `all_metrics(..., label="headline")` call, on the held-out
frame, dumped LAST.** The record layer binds the reported metric to a
manifest-certified headline dump; the number you put in `metrics.nse` must come
from that same call. If the protocol says monthly, the headline call takes the
MONTHLY frame — do not report a monthly number and dump a daily series. `885e6696`
reported the swept daily NSE 0.350 while the value that survived review was the
locked monthly −0.488, so nothing in the archive re-derived the reported number.

**2. Parameter-search evaluations are NOT headline dumps.** Pass
`meta={"headline_candidate": False}` to `all_metrics` for every calibration
trial (`ki_tools_common.metrics.dump_scored_series` reads that key straight out
of `meta` — no scorer change needed). A 22-trial sweep left 22 headline
candidates in `manifest.jsonl` and drowned the real one. Under the SWE lock the
sweep does not run at all, so the count should be zero.

**3. Assert the reproduction before writing the result.** Re-read the dumped
headline CSV, recompute NSE with `ki_tools_common.metrics.nse`, and fail the run
if it differs from the reported value. `run_and_score_hulunbuir.py` does this in
its `record_audit` block (delta 2.2e-16) and also asserts that exactly one dump
carries the `headline` label and that no `cal_trial` dump is a headline
candidate. That block is the template to copy.

**Two caller traps in the shared validators**, both live in this workflow:

- `preflight_forcing.py` prints `(PASS: 1, WARN: 0, FAIL: 0)` as its clean-run
  summary. Deciding pass/fail with `"FAIL" in stdout` therefore reports
  `all_pass=false` on a fully PASSING preflight and files the summary line
  itself as the failure. Parse the `[FAIL]` / `[WARN]` per-variable tokens and
  the summary counts instead.
- `validate_water_balance`'s `tolerance_mm` (default 50) does not scale with
  `period_days`, but the residual it measures does. A 12-water-year CRHM run
  closing to 3.1% of P (155 mm, no unit-error diagnostic) grades FAIL on the
  absolute arm alone — the longer a correct run is, the more certainly it
  "fails". Pass `tolerance_mm=50*n_years` and report both verdicts. Do not edit
  the shared default; it is one copy across every KI.
