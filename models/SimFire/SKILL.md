---
name: simfire
description: >-
  Rothermel surface fire spread model (USDA Forest Service RMRS-GTR-371; Anderson FBFM-13
  fuel models). Covers Surface wildfire spread over a 2-D gridded landscape via the
  Rothermel rate-of-spread equation; Per-pixel fuel (FBFM-13), elevation/slope, prescribed
  wind, and fuel-moisture forcing of spread. Use when the task involves running,
  configuring, calibrating or interpreting SimFire.
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

# SimFire — Wildfire Spread Simulation (Knowledge Infrastructure)

**Package**: simfire-wildfire v2.0.1
**Target Model**: SimFire 2.0.1 (Rothermel Surface Fire Spread)
**Domain**: Wildfire simulation, fire behavior prediction, reinforcement learning
**Authors**: MITRE Fireline (Welsh, Dotter, Doyle, Gandikota, Kempis, Schambach, Tapley, Threet)
**Last updated**: 2026-08-09
**Stats**: 6 tools, 5 skill docs, 25 diagnostic triplets, ~10,600 lines Python source

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for weather forcing documentation.
See `data_ki/MTBS/SKILL.md` for fire perimeter observations.


## Overview

SimFire is a Python-based wildfire simulation framework built on the **Rothermel Surface Fire Spread Model** (USDA Forest Service RMRS-GTR-371). It uses PyGame for real-time visualization and supports three terrain/fuel data modes:

- **Operational**: Real-world data from USGS LandFire (30 m resolution, FBFM-13 fuel models)
- **Functional**: Procedurally generated terrain and fuel using Perlin noise or analytical functions
- **Historical**: Replay of actual fire perimeter data via BurnMD integration

The simulator serves as the environment for the MITRE Fireline reinforcement learning pipeline, where agents learn wildfire suppression strategies. SimFire connects to **SimHarness** (RL training harness) and **BurnMD** (historical fire data).

**Key capabilities:**
- Physics-based fire spread using Rothermel equation (13 standard FBFM fuel models)
- Spatially-varying wind fields (Perlin noise, CFD Navier-Stokes, or constant)
- Three mitigation types: fireline, scratchline, wetline (with RoS attenuation)
- Headless mode for batch simulation and RL training
- Output as NPY arrays, HDF5 files, GIF animations, or fire spread graphs

---

## Installation

### From PyPI (recommended)
```bash
python -m venv venv && source venv/bin/activate
pip install simfire
```

### From source
```bash
git clone https://github.com/mitrefireline/simfire.git
cd simfire
pip install poetry
poetry install
```

### Key Dependencies
| Package | Purpose | Version |
|---------|---------|---------|
| pygame | Rendering and display | >=2.1.2 |
| numpy | Array operations, fire maps | >=1.22.4 |
| matplotlib | Plotting and graphs | >=3.5.2 |
| h5py | HDF5 data output | >=3.7.0 |
| landfire | USGS LandFire data access | >=0.5.0 |
| geotiff | GeoTIFF raster reading | >=0.2.10 |
| geopandas | Geospatial data handling | >=0.14.4 |
| opencv-python | Image processing | >=4.7.0 |
| noise | Simplex/Perlin noise generation | >=1.2.2 |
| PyYAML | Configuration parsing | >=6.0 |
| Pillow | Image manipulation, GIF export | >=9.1.1 |

### Python Version
Requires Python ~3.9 (poetry constraint).

### Test Run
```bash
python -c "
from simfire.sim.simulation import FireSimulation
from simfire.utils.config import Config
config = Config('configs/functional_config.yml')
sim = FireSimulation(config)
sim.run('10m')
print('Fire map shape:', sim.fire_map.shape)
print('Unique statuses:', set(sim.fire_map.flatten()))
"
```

---

## Pipeline Stages

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| S1 | Configuration | — | Create YAML config with area, display, simulation, terrain, wind, fire, environment sections |
| S2 | Terrain Setup | `convert_landfire_to_simfire.py` | Acquire fuel model and elevation data (operational) or generate procedurally (functional) |
| S3 | Wind Setup | `convert_wind_to_simfire.py` | Configure wind fields: constant, Perlin noise, or CFD |
| S4 | Environment | — | Set fuel moisture content (M_f) and fire initial position |
| S4b | Environment | `derive_fire_environment.py` | Dead fuel moisture from NASA POWER T/RH (Simard 1968 EMC, peak burning period) — replaces the hard-coded `moisture: 0.03` |
| S5 | Execution | `run_simfire.py` | Run the simulation via Python API or `run_game.py` |
| S6 | Output Analysis | `parse_simfire_output.py` | Extract fire spread statistics, burn maps, and time series; Sorensen / kappa / **CSI** / POD / FAR / Overestimation Index, plus the paired per-pixel evidence CSV |
| S7 | Validation | `mtbs_perimeter_to_grid.py` | Select MTBS fires + size their SimFire domains; rasterise a perimeter onto the EXACT simulated grid |
| S8 | Coupling | — | Feed fire maps to SimHarness for RL training |

**Parallelism**: Stages S2 and S3 can run in parallel. S4 depends on both.

---

## Tools Reference

| Tool | Stage | Script | Lines | Purpose |
|------|-------|--------|-------|---------|
| LandFire Converter | S2 | `tools/convert_landfire_to_simfire.py` | ~280 | Convert LandFire GeoTIFF fuel/elevation to SimFire layers |
| Wind Converter | S3 | `tools/convert_wind_to_simfire.py` | ~200 | Convert external wind data to SimFire wind arrays |
| Execution Wrapper | S5 | `tools/run_simfire.py` | ~250 | Run SimFire with config, capture outputs |
| Output Parser | S6 | `tools/parse_simfire_output.py` | ~450 | Extract burn statistics + spatial-agreement metrics, export CSV/plots |
| Fire Environment | S4b | `tools/derive_fire_environment.py` | ~180 | Weather-derived dead fuel moisture (Simard 1968 EMC) |
| MTBS Validation | S7 | `tools/mtbs_perimeter_to_grid.py` | ~330 | MTBS fire selection + perimeter rasterisation onto the simulated grid |

---

## Internal Unit System

SimFire's Rothermel implementation works in **US customary units** internally,
matching the original Rothermel paper. **YAML config inputs do NOT all use
internal units** — the loader converts certain fields. Verified against the
v2.0.1 source and the official MITRE config docs (`docs/source/config.md`).

### YAML config input units (what YOU write)

| YAML field | Input unit | Internal conversion site |
|---|---|---|
| `wind.simple.speed` | **mph** | `config.py:860` calls `mph_to_ftpm` |
| `wind.simple.direction` | **degrees clockwise from N, "TO" direction** (90 = wind blowing toward East) | `rothermel.py:104`: `wind_angle = 90 − U_dir`; max RoS at `angle_of_travel == U_dir` |
| `wind.perlin.speed.range_min/max` | **mph** | `config.py:897-901` calls `mph_to_ftpm` |
| `wind.perlin.direction.range_min/max` | degrees, same "TO" convention | (no conversion) |
| `wind.cfd.speed` | **m/s** (boundary condition); resulting array is converted via `scale_ms_to_ftpm` | `config.py:891` |
| `environment.moisture` | fraction (0.03 = 3%, NOT a percent) | direct |
| `area.pixel_scale` | **feet** per pixel | direct |
| `operational.height/width` | **meters** | direct |
| `operational.resolution` | meters | direct |

### Internal Rothermel calculation units (after the loader)

| Variable | Internal Unit |
|---|---|
| Distance | feet |
| Fuel load `w_0` | lb/ft² |
| Fuel depth `δ` | ft |
| Surface-area-to-volume `σ` | ft²/ft³ |
| Wind speed `U` | ft/min |
| Wind direction `U_dir` | degrees clockwise from N, "to" convention |
| Heat content `h` | BTU/lb |
| Particle density `ρ_p` | lb/ft³ |
| Moisture `M_f` | fraction |
| Rate of spread `R` | ft/min |
| Elevation | ft |

### CRITICAL UNIT TRAPS (re-verified 2026-04-29 against v2.0.1 source)

| Trap | Symptom | Root cause | Severity |
|------|---------|------------|----------|
| Wind speed in **ft/min** in YAML simple.speed (intending internal unit) | Fire spreads way too fast / fills grid in minutes | SimFire reads value as mph and converts ×88 → 88× too high | **Silent** |
| Wind speed in **m/s** in YAML simple.speed | Fire spreads ~2.24× faster than intended (10 m/s ≈ 22 mph; SimFire treats 10 as 10 mph) | Magnitude treated as mph | **Silent** |
| Wind direction interpreted as "FROM" (meteorological convention) | Fire spreads OPPOSITE to expected | YAML direction is "TO direction" — see rothermel.py:104. `direction=90` means wind blows TO East | **Silent** |
| Perlin range_min/max written in ft/min | Wind field 88× too strong | Same as simple.speed: mph_to_ftpm applied internally | **Silent** |
| Fuel load in kg/m² instead of lb/ft² | Extreme fire spread | Fuel load ~5× too high | **Silent** |
| Moisture as percent (3) instead of fraction (0.03) | Fire never spreads | Moisture/extinction ratio clamped → eta_M = 0 | **Silent** |
| Elevation in meters instead of feet (when injecting custom DEM) | Slope factor too small | Slope gradient 3.28× too low | **Silent** |
| Operational area in feet instead of meters | Downloads wrong LandFire extent | Area 3.28× too small | **Degraded** |
| `tools/convert_wind_to_simfire.py` output used directly in YAML | Wind 88× too strong | Tool produces ft/min .npy arrays for spatial-wind use cases (CFD, custom layers); the simple/perlin YAML paths take **mph** scalars | **Silent** |

---

## Rothermel Fire Spread Model — Quick Reference

### Input Parameters

**Fuel (per-pixel, from FBFM-13):**
| Symbol | Name | Unit | Range |
|--------|------|------|-------|
| w_0 | Oven-dry fuel load | lb/ft² | 0.034–0.321 |
| δ | Fuel bed depth | ft | 0.2–6.0 |
| M_x | Dead fuel moisture of extinction | — | 0.12–0.40 |
| σ | Surface-area-to-volume ratio | ft²/ft³ | 1145–3500 |

**Fuel Particle (constant):**
| Symbol | Name | Unit | Default |
|--------|------|------|---------|
| h | Low heat content | BTU/lb | 8000 |
| S_T | Total mineral content | — | 0.0555 |
| S_e | Effective mineral content | — | 0.01 |
| ρ_p | Oven-dry particle density | lb/ft³ | 32 |

**Environment (per-pixel or uniform, *internal* units after YAML conversion):**
| Symbol | Name | Internal unit | YAML unit | Typical |
|--------|------|------|------|---------|
| M_f | Fuel moisture | fraction | fraction | 0.001–0.08 |
| U | Midflame wind speed | ft/min | **mph** (simple.speed) | 5–50 mph |
| U_dir | Wind direction | degrees from N, "TO" convention | same | 0–360 |

**Topography (per-pixel):**
| Symbol | Name | Unit | Source |
|--------|------|------|--------|
| slope_mag | Slope magnitude | gradient | Computed from elevation |
| slope_dir | Slope aspect | radians | Computed from elevation |

### Rate of Spread Formula

```
R = (I_R × ξ × (1 + φ_w + φ_s)) / (ρ_b × ε × Q_ig)   [ft/min]
```

Where:
- `I_R` = Reaction intensity (BTU/ft²·min)
- `ξ` = Propagating flux ratio
- `φ_w` = Wind factor
- `φ_s` = Slope factor
- `ρ_b` = Bulk density (lb/ft³)
- `ε` = Effective heating number
- `Q_ig` = Heat of preignition (BTU/lb)

### 13 Standard Fuel Models (FBFM)

| ID | Name | w_0 | δ | M_x | σ |
|----|------|-----|---|-----|---|
| 1 | Short Grass | 0.034 | 1.0 | 0.12 | 3500 |
| 2 | Grass/Timber/Shrub | 0.092 | 1.0 | 0.15 | 2784 |
| 3 | Tall Grass | 0.138 | 2.5 | 0.25 | 1500 |
| 4 | Chaparral | 0.230 | 6.0 | 0.20 | 1739 |
| 5 | Brush | 0.046 | 2.0 | 0.20 | 1683 |
| 6 | Dormant Brush | 0.069 | 2.5 | 0.25 | 1564 |
| 7 | Southern Rough | 0.046 | 2.5 | 0.40 | 1552 |
| 8 | Closed Timber Litter | 0.069 | 0.2 | 0.30 | 1889 |
| 9 | Hardwood/Pine Timber | 0.133 | 0.2 | 0.25 | 2484 |
| 10 | Timber/Understory | 0.138 | 1.0 | 0.25 | 1764 |
| 11 | Light Logging Slash | 0.069 | 1.0 | 0.15 | 1182 |
| 12 | Medium Logging Slash | 0.184 | 2.3 | 0.20 | 1145 |
| 13 | Heavy Logging Slash | 0.321 | 3.0 | 0.25 | 1159 |

Non-burnable: 91 (Urban), 92 (Snow/Ice), 93 (Water), 98 (Agriculture), 99 (Barren)

---

## Configuration File Format

SimFire uses YAML configuration files with these sections:

```yaml
area:
  screen_size: [225, 450]   # [height, width] in pixels
  pixel_scale: 50            # feet per pixel

display:
  fire_size: 2               # sprite size (pixels)
  control_line_size: 2
  agent_size: 4
  rescale_factor: 2          # display zoom multiplier

simulation:
  update_rate: 1             # minutes per simulation step
  runtime: "15h"             # total duration (supports "Xd Xh Xm")
  headless: false            # true for batch/RL mode (also requires SDL_VIDEODRIVER=dummy)
  record: true               # save GIF (PyGame, only meaningful when not headless)
  save_data: true            # save fire maps
  data_type: "npy"           # "npy" or "h5"
  sf_home: "~/.simfire"      # cache directory

mitigation:
  ros_attenuation: false     # true=reduce RoS, false=zero RoS at lines

operational:
  seed: null                 # null=use lat/lon, int=random location
  latitude: 38.422           # top-left corner
  longitude: -118.266
  height: 2000               # meters (area extent)
  width: 2000                # meters
  resolution: 30             # must be 30 (LandFire native)
  year: 2020                 # LandFire year: 2019, 2020, 2022

terrain:
  topography:
    type: operational        # operational | functional | historical
  fuel:
    type: operational

fire:
  fire_initial_position:
    type: static
    static:
      position: (25, 25)     # (X, Y) = (COLUMN, ROW) in pixels — NOT (row, col).
                             # simulation.py _create_fire_map does
                             #   x, y = fire_initial_position; fire_map[y, x] = BURNING
                             # and _load_fire's `random` branch draws pos_x from
                             # screen_size[1] (width). See dt_025.
  max_fire_duration: 5       # frames before sprite pruning
  diagonal_spread: true      # 8-directional (vs 4)

environment:
  moisture: 0.03             # fuel moisture fraction (3%)

wind:
  function: simple            # simple | perlin | cfd
  simple:
    speed: 20                 # **mph** (NOT ft/min). config.py:860 calls mph_to_ftpm
    direction: 90.0           # degrees clockwise from N, "TO direction".
                              # 90 = wind blowing TOWARD east, NOT meteorological "from east"
  perlin:
    speed:
      seed: 2345
      range_min: 5            # **mph** (NOT ft/min). config.py:897-901 calls mph_to_ftpm
      range_max: 30            # **mph**
    direction:
      seed: 650
      range_min: 0.0          # degrees, same "TO direction" convention
      range_max: 360.0
```

---

## Output Description

SimFire produces a 2D `fire_map` numpy array (shape: height x width) where each pixel holds a BurnStatus integer (0=unburned, 1=burning, 2=burned, 3-5=mitigation lines). When `save_data: true`, the fire map is written as either `.npy` (numpy binary) or `.h5` (HDF5) files controlled by the `data_type` config parameter. Setting `record: true` saves an animated GIF of the fire progression. The `save_spread_graph()` method exports a fire spread adjacency graph. Use `parse_simfire_output.py` to extract burned area (pixel count and hectares), fire perimeter length, spread rate time series, and per-fuel-model burn statistics to CSV.

---

## Burn Status Values

| Value | Name | Meaning |
|-------|------|---------|
| 0 | UNBURNED | Not yet reached by fire |
| 1 | BURNING | Currently on fire |
| 2 | BURNED | Fire has passed |
| 3 | FIRELINE | Hand crew control line (attenuates RoS by 980 ft/min) |
| 4 | SCRATCHLINE | Light fuel removal (attenuates by 490 ft/min) |
| 5 | WETLINE | Water/retardant (attenuates by 245 ft/min) |

---

## Python API Quick Start

```python
from simfire.sim.simulation import FireSimulation
from simfire.utils.config import Config

# Load config and create simulation
config = Config("configs/operational_config.yml")
sim = FireSimulation(config)

# Run headless for 1 hour
sim.run("1h")

# Access fire map (numpy array of BurnStatus values)
fire_map = sim.fire_map  # shape: (height, width)

# Count burned pixels
import numpy as np
burned = np.sum(fire_map == 2)
burning = np.sum(fire_map == 1)
print(f"Burned: {burned}, Still burning: {burning}")

# Save outputs
sim.save_gif()
sim.save_spread_graph()

# Reset and re-run
sim.reset()
sim.run("2h")
```

---

## S7 — Validating against an observed fire perimeter (MTBS)

The end-to-end recipe, verified 2026-08-09 on six 2020 Great Basin wildfires.
`tools/mtbs_perimeter_to_grid.py` owns both halves of the dag's hard caveat
("compared maps must share grid size and georeferencing").

```python
import mtbs_perimeter_to_grid as mtbs
from convert_landfire_to_simfire import install_lfps2_shim
from convert_wind_to_simfire import FBFM13_DEPTH_FT, nasa_power_simple_wind
from derive_fire_environment import derive_moisture

# 1. Pick fires and size a domain for each (rejects are RECORDED, not dropped)
manifest = mtbs.cmd_select(args)          # bbox, year, acre band, span cap

# 2. LFPS v2 (the shipped `landfire` client is dead — dt_020)
install_lfps2_shim(email="you@example.org")

# 3. Weather-derived environment, NOT the example literals
env  = derive_moisture(lat, lon, ig_date)                 # dt_022
cfg  = Config(config_path)                                # downloads LandFire
depth = FBFM13_DEPTH_FT[dominant_burnable_fbfm]
wind = nasa_power_simple_wind(lat, lon, ig_date,           # dt_021
                              fuel_bed_depth_ft=depth,
                              start_offset_hours=12 - lon / 15)

# 4. Georeference from the CACHED GeoTIFF, never from the config lat/lon
crs, transform, shape = mtbs.grid_reference(tif, rows, cols)   # dt_023
obs = mtbs.cmd_rasterize(...)             # -> observed_perimeter.npy

# 5. Score
from parse_simfire_output import compute_accuracy_metrics, write_paired_pixels
```

### Choosing `max_fire_duration` at 30 m (LandFire) resolution

`max_fire_duration` is a **numerical propagation horizon, not a physical
residence time**. `RothermelFireManager._prune_sprites` deletes a burning
sprite after that many updates and `update()` returns `GameStatus.QUIT` the
instant zero sprites remain, while a neighbour only ignites once accumulated
`burn_amounts` reaches the inter-pixel distance. So the front dies prematurely
unless

```
max_fire_duration x update_rate x RoS  >=  pixel_scale x sqrt(2)
```

The shipped examples use 4-5 with `pixel_scale: 50` ft. At LandFire's 30 m
(98 ft) pixel that demands RoS >= 28 ft/min, which a realistic 1.6 mph midflame
wind in FBFM 2 does not reach — the 2020 SLINK fire died after ONE pixel.
**Verify convergence rather than guessing**: with `update_rate: 10`,
`max_fire_duration` of 12, 36 and 96 all produced the identical 12 428 burned
pixels for the 2020 BISHOP fire, i.e. 12 is already non-truncating and the
fire's self-extinction is physical, not numerical.

### What an uncalibrated operational run actually scores

Six 2020 Great Basin wildfires (SLINK, NUMBERS, MOUNTAIN VIEW, POODLE, BISHOP,
STEWART CANYON), gridded at 30 m, ignited at the MTBS perimeter centroid, run
unsuppressed to self-extinction, weather from NASA POWER:

| pooled over 2 998 271 pixels | value |
|---|---|
| Sorensen | 0.171 |
| Cohen's kappa | 0.144 |
| CSI | 0.093 |
| POD / FAR | 0.096 / 0.208 |
| Overestimation Index | -0.78 |
| burned-area PBIAS | -87.9 % |

That is **below** the Giannaros (2020) operational acceptance threshold of 0.40
for both SC and KC. The dominant error is omission: surface-only Rothermel with
a spatially uniform, temporally constant midflame wind from a 0.5 deg reanalysis
self-extinguishes after ~36 h, whereas the MTBS perimeter is a multi-day final
extent driven by wind events, spotting and crown fire that SimFire does not
represent. Treat these numbers as the uncalibrated baseline for the KI, not as a
target to tune toward.

---

## Coupling Points

| # | Source | Target | Variable | Format |
|---|--------|--------|----------|--------|
| 1 | LandFire | SimFire | Fuel model rasters | GeoTIFF → FBFM-13 array |
| 2 | LandFire | SimFire | Elevation rasters | GeoTIFF → elevation array (ft) |
| 3 | SimFire | SimHarness | Fire map, observations | numpy arrays via API |
| 4 | SimHarness | SimFire | Agent actions | (x, y, action_type) tuples |
| 5 | BurnMD | SimFire | Historical fire perimeters | HistoricalDataLayer |
| 6 | External wind | SimFire | Wind speed/direction | ft/min, degrees arrays |

---

## Diagnostic Triplets Summary

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | silent | unit_conversion | wind.simple.speed written in ft/min not mph → 88× too strong (corrected 2026-04-29) |
| dt_002 | silent | unit_conversion | wind.simple.speed written in m/s not mph → ~2.24× off |
| dt_003 | silent | unit_conversion | Fuel load in kg/m² instead of lb/ft² |
| dt_004 | silent | unit_conversion | Moisture as percent instead of fraction |
| dt_005 | silent | unit_conversion | Elevation in meters instead of feet |
| dt_006 | degraded | parameter | Pixel scale mismatch with actual resolution |
| dt_007 | fatal | runtime | PyGame display init fails in headless environment |
| dt_008 | silent | parameter | Fuel model 0 or negative mapped to non-burnable |
| dt_009 | degraded | runtime | Fire doesn't spread due to M_f >= M_x |
| dt_010 | silent | unit_conversion | Operational area dimensions wrong units |
| dt_011 | degraded | parameter | diagonal_spread=false halves effective spread rate |
| dt_012 | fatal | dependency | LandFire API unavailable or rate-limited |
| dt_013 | silent | parameter | CFD wind not converged (too few training iterations) |
| dt_014 | degraded | runtime | GIF save fails due to insufficient memory |
| dt_015 | silent | parameter | max_fire_duration too low causes premature burnout |
| dt_016 | silent | unit_conversion | wind.perlin.speed.range_* in ft/min not mph (corrected 2026-04-29) |
| dt_017 | silent | unit_conversion | Burn-area calc uses wrong pixel_scale or skips ft²→ac |
| dt_018 | silent | convention | wind.simple.direction is "TO direction", not meteorological "from" — head fire goes opposite expected |
| dt_019 | fatal | runtime | `operational:` (and `wind.cfd`/`wind.perlin`) are read UNCONDITIONALLY — omitting them raises KeyError even in functional mode |
| dt_020 | fatal | dependency | `landfire` 0.5.0's ArcGIS GPServer endpoint is RETIRED; use the LFPS v2 shim in `convert_landfire_to_simfire.install_lfps2_shim()` |
| dt_021 | silent | parameter | `wind.simple.speed` is the **midflame** wind, not the 10 m/2 m met wind — apply the log profile + Albini-Baughman WAF |
| dt_022 | silent | unit_conversion | `ki_tools_common.humidity.specific_humidity_to_rh` wants KELVIN; `load_forcing` gives Celsius → RH collapses to 0 |
| dt_023 | silent | parameter | simfire treats 0.0002778 deg as 30 m in BOTH lat and lon → the domain is silently truncated east-west; request native Albers + widen the AOI |
| dt_024 | fatal | dependency | `geotiff`/`tifffile` need `zarr>=3,<3.2`; both zarr<3 and zarr>=3.2 raise the same misleading "zarr X < 3 is not supported" |
| dt_025 | silent | convention | `fire_initial_position` is **(X, Y) = (col, row)**, not (row, col) — a transposed ignition point |

See `diagnostics/triplets.yaml` for full symptom→diagnosis→remedy details.

---

## File Structure

```
ki/
├── SKILL.md                              # This file
├── knowledge_infrastructure.yaml         # Machine-readable schema
├── tools/
│   ├── convert_landfire_to_simfire.py    # LandFire → SimFire fuel/elevation
│   ├── convert_wind_to_simfire.py        # External wind → SimFire format
│   ├── run_simfire.py                    # Execution wrapper
│   └── parse_simfire_output.py           # Output extraction and analysis
├── docs/
│   ├── s1_configuration.md               # Config file creation skill
│   ├── s2_terrain_setup.md               # Terrain and fuel data acquisition
│   ├── s3_wind_setup.md                  # Wind field configuration
│   ├── s4_execution.md                   # Running the simulation
│   └── s5_output_analysis.md             # Interpreting and validating results
├── diagnostics/
│   └── triplets.yaml                     # 15+ diagnostic triplets
└── workflow/
    └── workflow.md                        # Pipeline workflow diagram
```
