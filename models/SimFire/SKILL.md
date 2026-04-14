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
**Last updated**: 2026-03-26
**Stats**: 4 tools, 5 skill docs, 15+ diagnostic triplets, ~10,600 lines Python source

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
| S5 | Execution | `run_simfire.py` | Run the simulation via Python API or `run_game.py` |
| S6 | Output Analysis | `parse_simfire_output.py` | Extract fire spread statistics, burn maps, and time series |
| S7 | Validation | — | Compare against observed fire perimeters or published benchmarks |
| S8 | Coupling | — | Feed fire maps to SimHarness for RL training |

**Parallelism**: Stages S2 and S3 can run in parallel. S4 depends on both.

---

## Tools Reference

| Tool | Stage | Script | Lines | Purpose |
|------|-------|--------|-------|---------|
| LandFire Converter | S2 | `tools/convert_landfire_to_simfire.py` | ~280 | Convert LandFire GeoTIFF fuel/elevation to SimFire layers |
| Wind Converter | S3 | `tools/convert_wind_to_simfire.py` | ~200 | Convert external wind data to SimFire wind arrays |
| Execution Wrapper | S5 | `tools/run_simfire.py` | ~250 | Run SimFire with config, capture outputs |
| Output Parser | S6 | `tools/parse_simfire_output.py` | ~300 | Extract burn statistics, export CSV/plots |

---

## Internal Unit System

SimFire uses **US customary units** internally, matching the original Rothermel paper.

### Unit Convention Table

| Variable | Internal Unit | Common Input Unit | Conversion |
|----------|--------------|-------------------|------------|
| Distance | feet (ft) | meters (m) | × 3.28084 |
| Fuel load (w_0) | lb/ft² | kg/m² | × 0.2048 |
| Fuel depth (δ) | ft | m | × 3.28084 |
| Surface-area-to-volume (σ) | ft²/ft³ | m²/m³ | × 0.3048 |
| Wind speed (U) | ft/min | mph | × 88 |
| Wind speed (U) | ft/min | m/s | × 196.85 |
| Heat content (h) | BTU/lb | kJ/kg | × 0.4299 |
| Particle density (ρ_p) | lb/ft³ | kg/m³ | × 0.06243 |
| Moisture (M_f) | fraction | percent | ÷ 100 |
| Pixel scale | ft/pixel | m/pixel | × 3.28084 |
| Update rate | min/step | — | direct |
| Rate of spread (R) | ft/min | m/s | ÷ 196.85 |
| Elevation | ft | m | × 3.28084 |
| Area dimensions | meters | — | direct (config) |

### CRITICAL UNIT TRAPS

| Trap | Symptom | Root Cause | Severity |
|------|---------|------------|----------|
| Wind in mph instead of ft/min | Fire barely spreads or doesn't move | Wind speed 88× too low | **Silent** |
| Wind in m/s instead of ft/min | Fire barely spreads | Wind speed ~197× too low | **Silent** |
| Fuel load in kg/m² instead of lb/ft² | Extreme fire spread | Fuel load ~5× too high | **Silent** |
| Moisture as percent (50) instead of fraction (0.50) | Fire never spreads | Moisture clamped at M_x | **Silent** |
| Elevation in meters instead of feet | Slope factor too small | Slope gradient 3.3× too low | **Silent** |
| Pixel scale mismatch | Fire jumps or crawls | Spread rate scaled by wrong pixel size | **Silent** |
| Operational area in feet instead of meters | Downloads wrong LandFire extent | Area dimensions 3.3× too small | **Degraded** |

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

**Environment (per-pixel or uniform):**
| Symbol | Name | Unit | Typical |
|--------|------|------|---------|
| M_f | Fuel moisture | fraction | 0.001–0.08 |
| U | Midflame wind speed | ft/min | 7–47 |
| U_dir | Wind direction (from) | degrees | 0–360 |

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
  headless: false            # true for batch/RL mode
  record: true               # save GIF
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
      position: (25, 25)     # (row, col) in pixels
  max_fire_duration: 5       # frames before sprite pruning
  diagonal_spread: true      # 8-directional (vs 4)

environment:
  moisture: 0.03             # fuel moisture fraction (3%)

wind:
  function: perlin            # simple | perlin | cfd
  simple:
    speed: 7                  # ft/min
    direction: 90.0           # degrees (0=N, 90=E)
  perlin:
    speed:
      seed: 2345
      range_min: 7            # ft/min
      range_max: 47           # ft/min
    direction:
      seed: 650
      range_min: 0.0          # degrees
      range_max: 360.0
```

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
| dt_001 | silent | unit_conversion | Wind speed in mph instead of ft/min |
| dt_002 | silent | unit_conversion | Wind speed in m/s instead of ft/min |
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
