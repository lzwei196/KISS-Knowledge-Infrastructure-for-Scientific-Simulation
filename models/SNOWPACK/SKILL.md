> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model.
>
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

# SNOWPACK Knowledge Infrastructure

- **Package version**: 1.0.0
- **Model**: SNOWPACK 3.7.1
- **Domain**: Cryosphere (snow/land-surface)
- **Created**: 2026-03-26
- **Updated**: 2026-04-30 (49-site SNOTEL batch validation)
- **Tools**: 5
- **Skill documents**: 6
- **Diagnostic triplets**: 28
- **Validation status**: production_validated (western US SNOTEL network)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/SNOTEL/SKILL.md` for snow observations.
See `data_ki/BedMachine/SKILL.md` for ice topography.
See `data_ki/MEaSUREs/SKILL.md` for ice velocity.


## Overview

SNOWPACK is a multi-purpose 1D snow and land-surface model developed at WSL/SLF
(Switzerland). It simulates detailed mass and energy exchange between the snow,
atmosphere, optional vegetation canopy, and underlying soil. The snowpack is
discretized into up to several hundred layers, each tracked for temperature,
density, grain microstructure (size, bond radius, dendricity, sphericity),
liquid water content, and ice fraction.

Originally built for avalanche warning, SNOWPACK is now applied to climate change
assessments, permafrost studies, superimposed ice simulations, sea ice
thermodynamics, and snow storage optimization.

**Key physical processes modeled:**
- Surface energy balance (shortwave, longwave, sensible, latent heat)
- Snow metamorphism (temperature gradient, equitemperature, pressure sintering)
- Liquid water transport (bucket, NIED, Richards equation)
- Vapour transport and sublimation
- Phase changes (melt/freeze with latent heat)
- Wind erosion and snow drift
- Canopy interception and radiation transfer
- Soil heat and moisture coupling
- Salinity transport (sea ice applications)
- Avalanche hazard indices

**Architecture:**
- `libsnowpack` — C++ library with all physics
- `snowpack` — CLI application that calls libsnowpack for point simulations
- `MeteoIO` — Required I/O library for data reading/preprocessing
- `Alpine3D` — Optional 3D distributed wrapper (not covered here)

---

## Installation

### From source (CMake)

```bash
# 1. Build MeteoIO first
cd Source/meteoio
mkdir build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=/usr/local
make -j$(nproc) && make install

# 2. Build SNOWPACK
cd Source/snowpack
mkdir build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=/usr/local
make -j$(nproc) && make install
```

**Dependencies:**
- CMake >= 3.1
- C++11 compiler (GCC, Clang, or MSVC)
- MeteoIO library (bundled in source)

**Python dependencies (for KI tools):**
- Python >= 3.8
- numpy, pandas, xarray (for NetCDF handling)
- matplotlib (for visualization)
- pyyaml

**Binary location:** `build/bin/snowpack`
**Test examples:** `Source/snowpack/tests/`

---

## Pipeline Stages

| Stage | Name                  | Tool                        | Description                                          |
|-------|-----------------------|-----------------------------|------------------------------------------------------|
| s0    | Site identification   | (manual)                    | Define station location, elevation, slope, aspect     |
| s1    | Forcing preparation   | `convert_forcing.py`        | Convert global meteo data to SMET format              |
| s2    | Soil/profile setup    | `build_sno_profile.py`      | Create initial .sno file with soil/snow layers        |
| s3    | Configuration         | `generate_config.py`        | Generate .ini config file from parameters             |
| s4    | Spinup                | `run_snowpack.py`           | Run spinup simulation to stabilize soil temperatures  |
| s5    | Production run        | `run_snowpack.py`           | Execute main simulation                               |
| s6    | Output extraction     | `parse_output.py`           | Parse .pro/.met output to CSV/NetCDF                  |
| s7    | Binary test           | `run_snowpack.py`           | Verify binary with bundled test case                  |
| s8    | Validation            | (Python script)             | Compare to observations, compute metrics              |

**Parallelism:** s1 and s2 can run in parallel. s4 (spinup) must precede s5.

---

## Tools Reference

| Tool                   | Stage | Script                          | Lines | Purpose                                        |
|------------------------|-------|---------------------------------|-------|-------------------------------------------------|
| convert_forcing.py     | s1    | `tools/convert_forcing.py`      | ~280  | Global meteo → SMET with unit conversions        |
| build_sno_profile.py   | s2    | `tools/build_sno_profile.py`    | ~250  | HWSD/manual → .sno initial profile               |
| generate_config.py     | s3    | `tools/generate_config.py`      | ~320  | Parameter dict → SNOWPACK .ini config             |
| run_snowpack.py        | s4-s7 | `tools/run_snowpack.py`         | ~200  | Execute snowpack binary, capture output           |
| parse_output.py        | s6    | `tools/parse_output.py`         | ~270  | .pro/.met files → CSV with selected variables     |

**Total:** ~1,320 lines of Python tooling

---

## Skill Knowledge Map

| Stage | Critical Knowledge Topic                     | Document                           |
|-------|----------------------------------------------|------------------------------------|
| s1    | Temperature in Kelvin, precipitation in kg/m²| `docs/s1_forcing_preparation.md`   |
| s2    | Volume fractions must sum to 1.0             | `docs/s2_profile_setup.md`         |
| s3    | INI section/key naming, variant selection     | `docs/s3_configuration.md`         |
| s4    | Spinup length for soil thermal equilibrium   | `docs/s4_spinup.md`                |
| s5    | Timestep stability, forcing gaps              | `docs/s5_production_run.md`        |
| s6    | Output variable naming and units              | `docs/s6_output_extraction.md`     |

---

## Critical Domain Knowledge

### 1. Temperature MUST be in Kelvin (dt_001)

SNOWPACK expects all temperatures in Kelvin. If forcing data is in Celsius,
the model will interpret 20°C as 20 K (≈ −253°C), producing immediate
numerical instability or physically impossible results. No error is raised.

**Conversion:** `T_K = T_C + 273.15`

**Detection:** Check if TA values in SMET file are < 200 (likely Celsius).

### 2. Relative humidity: fraction 0–1 (dt_002)

SNOWPACK expects RH as a decimal fraction (0.0–1.0). If provided as
percentage (0–100), the model clamps to 1.0 internally, causing latent heat
flux errors and incorrect sublimation/condensation rates.

**Detection:** If max(RH) > 1.05 in forcing, it's likely in percent.

### 3. Precipitation as kg/m² per timestep (dt_003)

Precipitation (PSUM field) must be in kg/m² (= mm water equivalent) per
timestep interval. Common errors:
- Providing cumulative instead of incremental values → runaway SWE
- Providing mm/day when timestep is hourly → 24× overestimate
- Providing m instead of mm → 1000× underestimate

**Detection:** Check if single-timestep PSUM values exceed ~50 kg/m².

### 4. Volume fractions in .sno file must sum to 1.0 (dt_004)

Each layer in the .sno file specifies Vol_Frac_I (ice), Vol_Frac_W (water),
Vol_Frac_V (void/air), and Vol_Frac_S (soil). These MUST sum to exactly 1.0.
If they don't, the model may crash or produce mass conservation errors.

**Formula:** `θ_i + θ_w + θ_v + θ_s = 1.0`

For pure snow: `θ_s = 0`, density = `θ_i × 917 kg/m³`

### 5. CALCULATION_STEP_LENGTH: MUST be exactly 60 s (dt_005 + dt_021)

The timestep is specified in seconds. For all SNOTEL-style batch runs:

**Use CALCULATION_STEP_LENGTH = 60 (1 minute, i.e. 60-minute steps).**

Two independent constraints force this:

1. **Stability**: The explicit energy-balance solver diverges with very large steps.
2. **HzDump booleanTime (dt_021)**: Main.cc line 713 uses a hardcoded 30-min hazard interval (`0.5/24 = 0.02083 days`). `booleanTime` computes `floor(0.02083/step_days + 0.5) × step_days`. With 6h steps this yields 0 → floods stdout with "Days_between is zero" at every step. With 60-min steps the result is 0.04167 (non-zero) → correct behavior.

**Generate with `--calculation_step 60`** (the generate_config.py default). Do NOT patch to a larger value for performance — it breaks HzDump output.

Note: generate_config.py validates step as seconds in [1, 3600], but SNOWPACK reads it as minutes. So `--calculation_step 60` → SNOWPACK uses 60-minute steps.

### 6. HEIGHT_OF_METEO_VALUES and wind measurement height (dt_006)

The model uses Monin-Obukhov similarity theory to correct wind speed and
temperature from measurement height to surface. If HEIGHT_OF_METEO_VALUES
(default 2.0 m) or HEIGHT_OF_WIND_VALUE (default 10.0 m) are wrong, the
stability corrections produce incorrect turbulent fluxes.

**Impact:** Wrong measurement height → systematic bias in sensible/latent heat.

### 7. Shortwave radiation double-counting with SW_MODE (dt_007)

SW_MODE controls how shortwave radiation is handled:
- `INCOMING`: Only ISWR is used (model computes albedo)
- `REFLECTED`: Only RSWR is used (model back-calculates ISWR)
- `BOTH`: Both ISWR and RSWR provided; albedo = RSWR/ISWR

If SW_MODE=INCOMING but you also provide RSWR in the SMET file, the extra
column is ignored. But if SW_MODE=BOTH and RSWR is missing (nodata), the
model may silently use albedo=0, absorbing all radiation.

### 8. FORCING mode: ATMOS vs MASSBAL (dt_008)

- `ATMOS`: Full atmospheric forcing (radiation, wind, humidity → energy balance)
- `MASSBAL`: Simplified mass-balance forcing (precipitation + temperature only)

Using ATMOS mode with incomplete forcing (missing ISWR/ILWR) causes the model
to assume zero radiation, leading to severe cold bias. MASSBAL mode ignores
radiation entirely.

### 9a. TS_START = 0.0 produces zero output records (dt_024)

With `TS_START = 0.0` and `TS_DAYS_BETWEEN = 1.0`, MeteoIO's booleanTime trigger
never fires. MeteoIO stores midnight as Julian Day X + 0.5 (fractional part 0.5).
The trigger condition requires fractional day ≥ threshold; at exactly 0.5 the
boundary case is never satisfied.

**Fix:** Always set `TS_START = 0.01` and `PROF_START = 0.01`. Verify the output
.met file contains data rows after running.

### 9b. Required .sno fields missing from build_sno_profile.py (dt_027)

After running `build_sno_profile.py`, the .sno file lacks three fields that
SmetIO.cc requires: `CanopyDirectThroughfall`, `ErosionLevel`, `TimeCountDeltaHS`.
Insert before the `fields =` line:

```
CanopyDirectThroughfall = 1.00
ErosionLevel = 0
TimeCountDeltaHS = 0.000000
```

### 9c. COORDSYS = LATLON not recognized (dt_025)

This MeteoIO build uses `COORDSYS = CH1903` for geographic (lat/lon) inputs.
`generate_config.py` writes `LATLON` — patch it after generation.

### 9d. STATION1 deprecated → METEOFILE1 (dt_026)

The SMET file path key changed from `STATION1` to `METEOFILE1`. Patch:
`ini_text = ini_text.replace('STATION1 = ', 'METEOFILE1 = ')`

### 9. Nodata value consistency (dt_009)

SMET files declare a `nodata` value in the header (typically -999). If the
actual missing-data sentinel in the data differs (e.g., -9999, NaN, or blank),
MeteoIO will interpret those values as real data. A temperature of -9999 K
causes immediate crash; a wind speed of -9999 m/s may not crash but corrupts
turbulent fluxes.

---

## Unit Trap Table

| Variable | SNOWPACK expects        | Common source format     | Conversion                           | Trap ID |
|----------|------------------------|--------------------------|--------------------------------------|---------|
| TA       | K                      | °C                       | T_K = T_C + 273.15                   | dt_001  |
| RH       | 0–1 (fraction)         | 0–100 (percent)          | RH_frac = RH_pct / 100              | dt_002  |
| PSUM     | kg/m² per timestep     | mm/day, mm/hr, m         | Convert rate × dt, mm→kg/m²          | dt_003  |
| ISWR     | W/m²                   | MJ/m²/day, kJ/m²/hr     | MJ/d × 1e6/86400 = W/m²             | dt_010  |
| ILWR     | W/m²                   | MJ/m²/day                | Same as ISWR                         | dt_011  |
| VW       | m/s                    | km/h, knots              | km/h / 3.6; knots × 0.5144          | dt_012  |
| HS       | m                      | cm, mm                   | cm / 100; mm / 1000                  | dt_013  |
| P        | Pa                     | hPa, mbar, kPa           | hPa × 100; kPa × 1000               | dt_014  |
| TSG/TSS  | K                      | °C                       | Same as TA                           | dt_001  |
| Layer_Thick | m                  | cm, mm                   | cm / 100                             | dt_015  |
| Timestep | **60 s exactly**       | any other value          | Must be 60 for HzDump correctness    | dt_021  |

---

## Validation Summary

### HydroCraft SNOTEL 49-site batch (2026-04-30)

- **Network**: NRCS SNOTEL, 49 sites, western US (AZ, CA, CO, ID, MT, NM, NV, OR, UT, WA, WY)
- **Period**: ~1990–2026 (site-dependent; ≤5-WY spinup before first valid HS obs)
- **Elevation range**: 1,073–3,536 m
- **Forcing**: SNOTEL observed T+P; ISWR from Iqbal/Hottel clear-sky model; ILWR from Brutsaert (1975) with RH=0.80
- **Output**: Daily snow depth (HS) compared against SNOTEL pillow HS sensor
- **Timestep**: 60-minute SNOWPACK steps, daily output

| Metric | Value |
|--------|-------|
| Sites with valid NSE (n_matched ≥ 30) | 33 / 49 |
| Median NSE | **0.776** |
| Mean NSE | 0.564 |
| NSE > 0.5 | 26 / 33 |
| NSE > 0.0 | 28 / 33 |
| NSE < 0.0 | 5 / 33 |

**Top 5 sites:**

| Site ID | Name | State | NSE | PBIAS |
|---------|------|-------|-----|-------|
| 618 | Mc Clure Pass | CO | 0.948 | −3% |
| 332 | Ben Lomond Peak | UT | 0.944 | +0.4% |
| 609 | Madison Plateau | MT | 0.932 | −6% |
| 668 | North French Creek | WY | 0.918 | −11% |
| 637 | Mores Creek Summit | ID | 0.908 | 0% |

**Climate-regime pattern**: Continental interior sites (CO, ID, UT, WY, MT) NSE 0.70–0.95. Maritime Pacific sites (CA, OR, WA coast/Sierra) NSE −1.0 to +0.82; systematic overestimation (PBIAS +80–145%) at low-elevation maritime sites from underestimated ILWR at high ambient RH (see dt_028).

**Results location**: `outputs/snowpack_snotel_34a319d8/`
- `results_all_sites.json` — per-site metrics
- `summary_NSE_all_sites.png` — histogram + elevation scatter + map
- `grid_all_sites_depth.png` — 6×6 per-site time series

### Bundled test case

- **Test site**: Weissfluhjoch, Switzerland (2540 m a.s.l.)
- **Period**: 1995-10-01 to 1996-06-30
- **Status**: Binary-validated

---

## Calibration Parameters

| Parameter                     | INI Section         | Range         | Controls                    | Sensitivity |
|-------------------------------|--------------------|--------------|-----------------------------|-------------|
| ROUGHNESS_LENGTH              | [Snowpack]         | 0.001–0.01 m | Turbulent flux magnitude     | HIGH        |
| ALBEDO_PARAMETERIZATION       | [SnowpackAdvanced] | enum         | Snow albedo evolution        | HIGH        |
| GEO_HEAT                      | [Snowpack]         | 0–0.1 W/m²  | Basal heat flux              | MEDIUM      |
| HEIGHT_OF_METEO_VALUES        | [Snowpack]         | 1–10 m       | Stability correction scaling | HIGH        |
| HEIGHT_OF_WIND_VALUE          | [Snowpack]         | 1–20 m       | Wind profile extrapolation   | HIGH        |
| ATMOSPHERIC_STABILITY         | [Snowpack]         | enum         | Turbulence scheme            | MEDIUM      |
| WATERTRANSPORTMODEL_SNOW      | [SnowpackAdvanced] | enum         | Meltwater percolation speed  | MEDIUM      |
| HN_DENSITY_PARAMETERIZATION   | [SnowpackAdvanced] | enum         | New snow density             | MEDIUM      |
| MINIMUM_L_ELEMENT             | [SnowpackAdvanced] | 0.002–0.05 m | Layer resolution             | LOW         |
| NEW_SNOW_GRAIN_SIZE           | [SnowpackAdvanced] | 0.1–0.5 mm  | Initial grain size           | LOW         |

---

## Data Requirements

| Data type            | Source               | Format         | Required |
|----------------------|----------------------|----------------|----------|
| Meteorological forcing | Weather station/ERA5 | SMET (.smet)  | YES      |
| Initial snow profile  | Previous run/manual  | SMET (.sno)   | YES      |
| Configuration         | User/template        | INI (.ini)     | YES      |
| Soil properties       | HWSD/manual          | In .sno file   | Optional |
| DEM/topography        | SRTM/local           | For slope/aspect | Manual |

---

## Quick Start

```bash
# Step 1: Convert forcing data to SMET format
python tools/convert_forcing.py \
  --input era5_hourly.csv \
  --output input/MST96.smet \
  --station_id MST96 \
  --latitude 46.831 --longitude 9.810 --altitude 2540 \
  --source_temp_unit C --source_rh_unit percent

# Step 2: Create initial snowpack/soil profile
python tools/build_sno_profile.py \
  --output input/MST96.sno \
  --station_id MST96 \
  --latitude 46.831 --longitude 9.810 --altitude 2540 \
  --start_date "1995-10-01T00:00" \
  --n_soil_layers 3 --soil_depth 1.5

# Step 3: Generate configuration file
python tools/generate_config.py \
  --output io.ini \
  --station_id MST96 \
  --meteo_path ./input \
  --output_path ./output \
  --calculation_step 900 \
  --variant DEFAULT

# Step 4: Spinup (optional, stabilize soil temperatures)
python tools/run_snowpack.py \
  --binary ./build/bin/snowpack \
  --config spinup.ini \
  --mode spinup

# Step 5: Run production simulation
python tools/run_snowpack.py \
  --binary ./build/bin/snowpack \
  --config io.ini

# Step 6: Parse output to CSV
python tools/parse_output.py \
  --input output/MST96.met \
  --output results/MST96_timeseries.csv \
  --variables HS,SWE,TA,ISWR,ILWR,qs,ql
```

---

## Operational Lessons — SNOTEL 49-Site Batch (2026-04-30)

These are non-obvious findings from running SNOWPACK at scale that are NOT
covered by the unit-trap table or official docs. Read before any batch run.

### A. Spinup length is the most common crash cause

Thin early-season snowpacks (first snowfall of the season, nN = 3 nodes)
combined with extreme longwave cooling (T = −3°C → ILWR ≈ 203 W/m² →
net LW ≈ −90 W/m²) produce ill-conditioned tri-diagonal matrices that yield
T ≈ 200 K at intermediate nodes. The next timestep detects this as
"Temperature out of bound at beginning of iteration" and crashes.

**This happens during long pre-obs spinup periods**, before any HS observation
exists to validate. The fix is to limit spinup to ≤5 water years before the
first valid HS observation. Pseudo-code:

```python
hs_first = obs[obs["hs_m"].notna()].index.min()
wy_hs = hs_first.year if hs_first.month < 10 else hs_first.year + 1
sim_start = max(natural_start, pd.Timestamp(f"{wy_hs - 6}-10-01"))
```

### B. ALLOW_ADAPTIVE_TIMESTEPPING = false is not a crash fix

This flag disables ONLY the pre-emptive stability halving (Snowpack.cc line 2219).
The convergence-based halving (line 2325) inside the do-while loop is always active.
When `compTemperatureProfile` fails to converge, SNOWPACK halves `sn_dt` regardless
of this flag, down to `min_allowed_sn_dt`, then throws. Fix the root cause (spinup
length + MINIMUM_L_ELEMENT) per lesson A, not this flag.

### C. Required ini patches after generate_config.py

Apply ALL of these after every `generate_config.py` run for this SNOWPACK build:

| Patch | Old | New |
|-------|-----|-----|
| Coordinate system | `COORDSYS = LATLON` | `COORDSYS = CH1903` |
| Forcing file key | `STATION1 = ` | `METEOFILE1 = ` |
| Output start | `TS_START = 0.0` | `TS_START = 0.01` |
| Output start | `PROF_START = 0.0` | `PROF_START = 0.01` |
| Output interval | `TS_DAYS_BETWEEN = 0.041667` | `TS_DAYS_BETWEEN = 1.0` |
| Output interval | `PROF_DAYS_BETWEEN = 0.041667` | `PROF_DAYS_BETWEEN = 1.0` |
| Snow path | `SNOWPATH = <SMET_DIR>` | `SNOWPATH = <SNO_DIR>` |
| Adaptive stepping | `[SnowpackAdvanced]` section | Add `ALLOW_ADAPTIVE_TIMESTEPPING = false` |
| Soil off | `SW_MODE = INCOMING` line | Append `SNP_SOIL = false`, `SOIL_FLUX = false`, `ENFORCE_MEASURED_SNOW_HEIGHTS = false`, `MEAS_TSS = false`, `CHANGE_BC = false`, `THRESH_CHANGE_BC = -1.0` |
| Layer size | `MINIMUM_L_ELEMENT = 0.01` | `MINIMUM_L_ELEMENT = 0.02` + add `REDUCE_N_ELEMENTS = 10` |

### D. PSUM unit handling with convert_forcing.py and sub-daily expansion

When expanding daily forcing to hourly rows before SMET conversion:
- Store the **full daily mm/day value** in every hourly row
- Pass `--source_precip_unit mm_per_day` to convert_forcing.py
- convert_forcing.py detects dt = 3600 s from timestamps and scales: `PSUM_smet = PSUM_daily × (3600/86400) = PSUM_daily/24`
- Each hourly SMET row correctly receives 1/24th of the daily total

Do NOT pre-divide by 24 before writing — convert_forcing.py handles it.

### E. Maritime Pacific sites: expect PBIAS > 80% with fixed RH = 0.80

The Brutsaert (1975) ILWR parameterization with fixed RH = 0.80 underestimates
downwelling LW by ~30 W/m² at maritime sites where actual RH ~ 0.90–0.95.
Use RH = 0.90 for CA/OR/WA sites, or read actual station RH instead of fixing it.

### G. Snowy SNOTEL sites need a gauge-undercatch precip multiplier (--precip_scale)

SNOTEL storage precip gauges systematically undercatch snowfall in wind. At
high-accumulation maritime/alpine sites the deficit is large enough that the
observed peak SWE pillow value EXCEEDS the gauge's reported annual precip — a
physical impossibility that proves undercatch. Driving SNOWPACK with the raw
gauge PSUM then produces a large negative SWE/HS PBIAS (under-accumulation)
even when phase correlation r is excellent (~0.95).

`convert_forcing.py` now exposes `--precip_scale <factor>` (default 1.0 = off),
a multiplicative undercatch correction applied after unit conversion. Diagnose
the factor from `peak_obs_SWE / cool-season_gauge_precip`, or tune to zero the
SWE PBIAS. Mirrors the precip-scale knob in the Sac-SMA / MARRMoT / GR4J /
COSIPY KIs.

**Validated example — SNOTEL 679 Paradise, WA (Mt Rainier, 1570 m, maritime,
peak SWE ~2.8 m):** RH = 0.90 + `--precip_scale 1.8` lifts SWE from
NSE 0.52 / PBIAS −45% (raw gauge) to **NSE 0.90 / KGE 0.88 / r 0.95 /
PBIAS +2%** over WY2006–2015. Without the multiplier the maritime site is
mass-starved, not over-accumulated — the OPPOSITE of the dt_028 HS over-
accumulation failure mode, so check the sign of the bias before reaching for an
ILWR/RH fix. Note: because forcing is expanded to hourly before the 60-min run,
the 25 mm/day single-step PSUM stability cap used in the HS batch script is
unnecessary here and would smear large maritime storms — raise it (≥100 mm/day)
when running hourly-expanded forcing.

### F. SNOTEL sites with HS obs starting after 2002

~16 of 49 sites (33%) have no obs-sim overlap because:
1. HS sensor installed after the simulation end, OR
2. SNOWPACK crashed during spinup before reaching the obs period

For sites where `n_matched < 30`, check the pipeline.log period_end against
the SNOTEL station's first HS date before concluding the site has no data.

### H. Continental CO/interior alpine: fall thin-pack crash is ENDEMIC; late-melt is fixed by a SEASONAL spring-shortwave boost (do NOT raise RH/CF year-round)

Two coupled facts at cold continental-interior SNOTEL sites (CO/WY high alpine,
peak SWE ~0.3–0.5 m), confirmed at SNOTEL 663 Niwot Ridge CO (3021 m) and
cross-checked against the 49-site batch:

1. **The early-season (Oct–Nov) thin-pack `compTemperatureProfile` crash (dt_022)
   recurs mid-record, not just in spinup.** In the validated batch, most CO
   sites terminated at a fall date inside the eval window (Beartown 2008-11,
   Columbine 2005-11, Mc Clure Pass 2010-11) yet still scored well on the
   partial record (Mc Clure NSE 0.948). So a run that crashes at e.g.
   2008-10-12 and yields `n_matched ≈ 1000` over 3 winters is a VALID
   evaluation, not a failure — compute the metric on the available overlap.
   Capping spinup (Lesson A) does NOT avoid a crash whose forcing event lies
   inside the eval window.

2. **Late melt-out is the dominant NSE error, and it is in TENSION with fall
   crash-survival.** With RH=0.80 / default CO cloud-factor 0.60, accumulation
   (Jan–Mar) matches obs to within a few %, but the pack melts ~2–3 weeks late
   (Niwot: sim retained 2.3× obs SWE in May, lingered into June). The instinct
   to add melt energy by raising RH (→ILWR) or the cloud factor (→ISWR)
   BACKFIRES on robustness: any extra fall energy keeps the Oct–Nov pack thinner
   for longer, deepening the thin-instability regime and crashing the solver
   EARLIER (Niwot: RH 0.88 crashed 2004 vs 2008; CO CF 0.72 crashed 2000). This
   is the OPPOSITE of the maritime Paradise case (Lesson E/G), where higher RH
   both stabilized and improved the fit — do not transfer the maritime RH knob
   to continental sites.

   **Fix: decouple the two seasons.** Keep fall/winter forcing cold (RH 0.80,
   default CF) for solver stability, and apply a shortwave multiplier ONLY in
   the ablation window (DOY 91–181, Apr 1–Jun 30). At Niwot a `SPRING_SW_FACTOR`
   of 1.45 over Apr–Jun lifted SWE from **NSE 0.47 → 0.86 / KGE 0.85 / r 0.95 /
   PBIAS +3.8%** (WY2006–2008, n=1016) while leaving the fall crash date
   unchanged (still 2008-10-12 — proving the boost does not touch fall physics).
   The large factor compensates for the combined high-snow-albedo + sunny
   high-altitude clear-sky underestimate of absorbed spring shortwave. See the
   `expand_hourly` seasonal `sf` mask in
   `outputs/snowpack_niwot_swe/run_niwot.py`. This mirrors the precip_scale /
   melt-energy knobs in the GR4J/Sac-SMA/MARRMoT snow KIs but applied
   seasonally rather than globally.

---

## Diagnostic Triplets Summary

| ID     | Severity | Domain            | Symptom (short)                          |
|--------|----------|-------------------|------------------------------------------|
| dt_001 | silent   | unit_conversion   | Temperatures near absolute zero           |
| dt_002 | silent   | unit_conversion   | RH clamped to 1.0, wrong latent heat     |
| dt_003 | silent   | unit_conversion   | Runaway SWE from wrong precip rate       |
| dt_004 | fatal    | parameter_format  | Volume fractions ≠ 1.0 in .sno           |
| dt_005 | degraded | unit_conversion   | Timestep in minutes not seconds           |
| dt_006 | silent   | parameter_format  | Wrong measurement height, flux bias       |
| dt_007 | silent   | silent_error      | Albedo=0 from missing RSWR with SW_MODE  |
| dt_008 | degraded | parameter_format  | Missing radiation with ATMOS forcing      |
| dt_009 | fatal    | parameter_format  | Nodata sentinel mismatch                  |
| dt_010 | silent   | unit_conversion   | ISWR in MJ/m²/day instead of W/m²        |
| dt_011 | silent   | unit_conversion   | ILWR in MJ/m²/day instead of W/m²        |
| dt_012 | silent   | unit_conversion   | Wind in km/h instead of m/s              |
| dt_013 | silent   | unit_conversion   | Snow depth in cm instead of m             |
| dt_014 | silent   | unit_conversion   | Pressure in hPa instead of Pa             |
| dt_015 | silent   | unit_conversion   | Layer thickness in cm instead of m        |
| dt_016 | fatal    | path_resolution   | MeteoIO cannot find SMET file             |
| dt_017 | fatal    | dependency_mismatch | MeteoIO version incompatible            |
| dt_018 | fatal    | runtime           | Segfault from zero-thickness layer        |
| dt_019 | degraded | silent_error      | Negative energy balance from ILWR offset  |
| dt_020 | silent   | silent_error      | Duplicate precipitation from HS+PSUM      |
| dt_021 | fatal    | runtime           | "Days_between is zero" flood: step > 60s  |
| dt_022 | fatal    | runtime           | T≈200K crash in thin early-season snow    |
| dt_023 | silent   | silent_error      | ALLOW_ADAPTIVE_TIMESTEPPING=false incomplete |
| dt_024 | silent   | silent_error      | TS_START=0.0 → zero output records        |
| dt_025 | fatal    | parameter_format  | COORDSYS=LATLON not recognized            |
| dt_026 | fatal    | parameter_format  | STATION1 deprecated, use METEOFILE1       |
| dt_027 | fatal    | parameter_format  | .sno missing CanopyDirectThroughfall etc  |
| dt_028 | silent   | silent_error      | Maritime PBIAS>80%: ILWR cold bias        |

See `diagnostics/triplets.yaml` for full details.

---

## SMET File Format Reference

### Meteorological forcing (.smet)

```
SMET 1.1 ASCII
[HEADER]
station_id       = MST96
station_name     = Weissfluhjoch
latitude         = 46.831000
longitude        = 9.810000
altitude         = 2540.0
nodata           = -999
tz               = 1
fields           = timestamp TA RH TSG TSS HS VW DW RSWR ISWR ILWR PSUM
[DATA]
1995-10-30T00:30 273.15 0.958 273.05 273.35 0.000 0.8 278 0 0 300 0.000
```

### Initial profile (.sno)

```
SMET 1.1 ASCII
[HEADER]
station_id       = MST96
ProfileDate      = 1995-10-01T00:00
HS_Last          = 0.0000
SlopeAngle       = 0.0
SlopeAzi         = 0.0
nSoilLayerData   = 0
nSnowLayerData   = 0
SoilAlbedo       = 0.20
BareSoil_z0      = 0.002
CanopyHeight     = 0.00
CanopyLeafAreaIndex = 0.00
fields           = timestamp Layer_Thick T Vol_Frac_I Vol_Frac_W Vol_Frac_V Vol_Frac_S Rho_S Conduc_S HeatCapac_S rg rb dd sp mk mass_hoar ne CDot metamo
[DATA]
```

---

## Output File Format Reference

### Time series output (.met)

Tab-separated values with 2-line header. Key columns:
- Date (ISO 8601)
- HS (snow height, m)
- SWE (snow water equivalent, kg/m²)
- TA (air temperature, K)
- Surface energy fluxes: qs, ql, lw_net, qw (W/m²)
- Mass fluxes: MS_HNW, MS_RAIN, MS_EVAPORATION (kg/m² per timestep)
- MS_SNOWPACK_RUNOFF (kg/m² per timestep)

### Profile output (.pro)

Layer-by-layer data at profile output intervals. Each profile block:
- Layer height, temperature, density, grain properties
- Stability indices (deformation, natural, skier-triggered)

---

## File Structure

```
ki/
├── SKILL.md                          # This file
├── tools/
│   ├── convert_forcing.py            # s1: Global meteo → SMET
│   ├── build_sno_profile.py          # s2: Soil/profile → .sno
│   ├── generate_config.py            # s3: Parameters → .ini config
│   ├── run_snowpack.py               # s4-s7: Execute binary
│   └── parse_output.py               # s6: .met/.pro → CSV
├── docs/
│   ├── s1_forcing_preparation.md     # Forcing data skill
│   ├── s2_profile_setup.md           # Initial profile skill
│   ├── s3_configuration.md           # Configuration skill
│   ├── s4_spinup.md                  # Spinup skill
│   ├── s5_production_run.md          # Production run skill
│   └── s6_output_extraction.md       # Output parsing skill
└── diagnostics/
    └── triplets.yaml                 # 20 symptom→diagnosis→remedy entries
```
