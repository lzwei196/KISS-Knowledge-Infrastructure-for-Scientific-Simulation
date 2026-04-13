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

# GeoClaw Knowledge Infrastructure

**Package:** geoclaw-ki v1.0
**Model:** GeoClaw (part of Clawpack)
**Domain:** Ocean / Coastal / Tsunami / Storm Surge
**Creator:** auto_dissect
**Last Updated:** 2026-03-26
**Stats:** 4 tools, 5 skill docs, 18 diagnostic triplets, ~1,200 lines of Python
**Validation Status:** example_validated (bowl-slosh analytical solution)

---

## 1. Overview

GeoClaw is a finite-volume solver for the 2D shallow water equations with
adaptive mesh refinement (AMR), designed for geophysical flow simulations
including tsunamis, storm surges, and dam-break floods.  It is part of the
Clawpack (Conservation Laws Package) suite and is implemented as a hybrid
Fortran/Python system: Fortran handles the numerical core (Riemann solvers,
AMR, time stepping) while Python manages configuration, topography I/O,
output processing, and visualization.

**Key Physical Processes:**
- Depth-integrated shallow water equations (mass + momentum conservation)
- Adaptive mesh refinement for multi-scale resolution (ocean → nearshore)
- Wetting/drying at shorelines with robust dry-state handling
- Manning friction for bottom drag
- Coriolis forcing for large-scale flows
- Okada earthquake source model for tsunami generation
- Storm surge forcing (parametric or data-driven wind + pressure fields)
- Boussinesq dispersive wave corrections
- Multi-layer stratified shallow water equations

**Equation System (2D):**
```
∂h/∂t  + ∂(hu)/∂x + ∂(hv)/∂y = 0
∂(hu)/∂t + ∂(hu² + ½gh²)/∂x + ∂(huv)/∂y = -gh·∂B/∂x + friction + Coriolis
∂(hv)/∂t + ∂(huv)/∂x + ∂(hv² + ½gh²)/∂y = -gh·∂B/∂y + friction + Coriolis
```
Where h = water depth (m), u/v = velocity (m/s), B = bathymetry (m), g = 9.81 m/s².

---

## 2. Installation

**Dependencies:**
- Python ≥ 3.8 with NumPy, matplotlib, scipy
- Fortran compiler (gfortran recommended)
- Clawpack suite: clawutil, pyclaw, visclaw, amrclaw, geoclaw
- Optional: NetCDF4 for NetCDF topo/output support

**Install from PyPI:**
```bash
pip install clawpack
```

**Install from source:**
```bash
git clone https://github.com/clawpack/clawpack.git
cd clawpack && git submodule update --init
pip install -e .
```

**Environment variables (required):**
```bash
export CLAW=/path/to/clawpack
export FC=gfortran          # Fortran compiler
```

**Test installation:**
```bash
cd $CLAW/geoclaw/examples/tsunami/bowl-slosh
make new                    # compile and run (~30 seconds)
make plots                  # generate figures
```

---

## 3. Pipeline

GeoClaw follows a 7-stage simulation pipeline:

| Stage | ID | Tool | Description | Parallelism |
|-------|----|------|-------------|-------------|
| 1 | s1_bathymetry | `convert_bathymetry.py` | Prepare topography/bathymetry files | Independent |
| 2 | s2_earthquake_source | (manual) | Define fault parameters / dtopo | Requires s1 |
| 3 | s3_configuration | `generate_setrun.py` | Create setrun.py with all parameters | Requires s1,s2 |
| 4 | s4_compilation | (Makefile) | Compile Fortran sources → xgeoclaw | Independent |
| 5 | s5_execution | `run_geoclaw.py` | Run the simulation | Requires s1-s4 |
| 6 | s6_output_analysis | `parse_geoclaw_output.py` | Extract output to CSV / analyze | Requires s5 |
| 7 | s7_visualization | (visclaw) | Generate plots and animations | Requires s6 |

---

## 4. Unit Trap Table

These are the most common unit-related errors that cause silent failures or
incorrect results.  Each entry links to a diagnostic triplet ID.

| Variable | Expected Unit | Common Wrong Unit | Impact | Triplet |
|----------|--------------|-------------------|--------|---------|
| Bathymetry elevation | meters (m) below/above datum | feet, fathoms | Depth 3× wrong → wrong wave speed | dt_001 |
| Topography coordinates | meters (coord_sys=1) OR degrees (coord_sys=2) | Mixed units | Domain mismatch, empty solution | dt_002 |
| Time | seconds (s) | minutes, hours | Simulation duration 60× off | dt_003 |
| Manning coefficient | dimensionless (s/m^{1/3}) | — | Friction too high/low → wrong inundation | dt_004 |
| Sea level | meters relative to datum | feet, cm | Initial water surface wrong | dt_005 |
| Gravity | m/s² (9.81) | ft/s² (32.2) | Wave speed √(gh) wrong by √3 | dt_006 |
| Earth radius | meters (6367500.0) | km (6367.5) | Lat-lon metric terms 1000× off | dt_007 |
| Wind speed (surge) | m/s | knots, mph, km/h | Storm forcing 2× off | dt_008 |
| Pressure (surge) | Pa (Pascals) | mbar, hPa | Pressure gradient 100× off | dt_009 |
| Fault slip (dtopo) | meters | cm | Tsunami amplitude 100× off | dt_010 |
| CFL number | 0.0–1.0 | >1.0 | Numerical instability / NaN | dt_011 |
| dry_tolerance | meters (small, e.g. 1e-3) | 0 or very large | Wet/dry interface failure | dt_012 |

---

## 5. Tools Reference

| Tool | Script | Lines | Purpose |
|------|--------|-------|---------|
| Bathymetry Converter | `tools/convert_bathymetry.py` | ~250 | Convert DEM/ASCII/NetCDF to GeoClaw topo format |
| Configuration Generator | `tools/generate_setrun.py` | ~350 | Generate setrun.py from JSON parameters |
| Execution Wrapper | `tools/run_geoclaw.py` | ~200 | Compile and run GeoClaw with error checking |
| Output Parser | `tools/parse_geoclaw_output.py` | ~300 | Extract fort.q/gauge files → CSV |

---

## 6. Critical Domain Knowledge

These are non-obvious facts that cause silent failures if violated.
Each is cross-referenced to a diagnostic triplet.

### 6.1 Coordinate System Consistency (dt_002)
All topography files, domain bounds, gauge locations, and AMR regions
MUST use the same coordinate system.  If `coordinate_system=2` (lat-lon),
all spatial values must be in degrees.  If `coordinate_system=1` (Cartesian),
all must be in meters.  Mixing causes the solver to run but produce
nonsensical results with no error message.

### 6.2 Topography Sign Convention (dt_001)
GeoClaw uses the convention that **bathymetry is negative below sea level
and positive above sea level**.  ETOPO data follows this convention, but
many other DEM sources use positive-down for ocean depth (e.g., GEBCO before
2019).  If the sign is wrong, the "ocean" appears as a mountain and the
solver produces zero flow.

### 6.3 Manning Coefficient Scale (dt_004)
Manning's n is typically 0.01–0.06 for natural channels.  Values > 0.1 cause
extreme friction that halts the flow within a few cells.  Values < 0.001
produce nearly frictionless flow.  The coefficient is spatially variable
when using `friction_data.variable_friction = True`.

### 6.4 AMR Refinement Ratios Must Be Integer (dt_013)
Refinement ratios (e.g., `refinement_ratios_x = [4, 4]`) must be positive
integers.  The length of the ratio array must equal `amr_levels_max - 1`.
A mismatch causes a Fortran runtime error that can be cryptic.

### 6.5 Topography Must Cover the Entire Domain (dt_014)
If topography files do not cover the entire computational domain, GeoClaw
will extrapolate or use zero bathymetry for uncovered regions.  This can
create artificial walls or cliffs at topo boundaries.

### 6.6 Output Format Affects File Size (dt_015)
ASCII output (`output_format='ascii'`) is human-readable but can produce
very large files for fine AMR grids.  Binary output (`output_format='binary'`)
is ~4× smaller but requires Python tools to read.

### 6.7 dry_tolerance Controls Wet/Dry Interface (dt_012)
The `dry_tolerance` parameter (default 1e-3 m) determines the minimum depth
to consider a cell "wet."  Setting it too small causes numerical oscillations
at shorelines.  Setting it too large misses thin water layers.

### 6.8 CFL Number Must Be < 1 (dt_011)
The Courant-Friedrichs-Lewy number (`cfl_desired`) should be 0.75–0.9.
Values ≥ 1.0 cause numerical instability.  GeoClaw aborts if CFL exceeds
`cfl_max` (default 1.0) during a time step.

### 6.9 Fault Slip Units for Tsunami Source (dt_010)
The Okada model expects fault parameters in specific units: slip in meters,
depth in km, strike/dip/rake in degrees, length/width in km.  Using cm
for slip produces a tsunami 100× too small — the simulation runs but the
wave height is negligible.

---

## 7. Input Formats

### 7.1 Topography Files

**Type 1 (xyz ASCII):** Three columns: x, y, z (one point per line)
```
-122.5  37.0  -1500.0
-122.4  37.0  -1480.0
```

**Type 2 (Header + Grid):** Header with grid metadata, then z values
```
ncols  100
nrows  80
xll    -122.5
yll    36.5
cellsize  0.01
nodata_value  -9999
-1500.0 -1480.0 ...
```

**Type 3 (ESRI ASCII Grid):** Same as Type 2 with `xllcenter`/`yllcenter`

**Type 4 (NetCDF):** CF-compliant NetCDF with x, y, z variables

### 7.2 Dynamic Topography (dtopo) Files

Used for earthquake-induced seafloor deformation.  Format includes
time-dependent z-displacement: (t, x, y, dz).

### 7.3 Configuration (setrun.py)

Python script that creates a `ClawRunData` object.  The `setrun()` function
defines all parameters and returns the data object.  Key parameter groups:
- `clawdata` — grid, time stepping, numerical method
- `geo_data` — physics (gravity, friction, coordinates)
- `topo_data` — topography file list
- `dtopo_data` — dynamic topography file list
- `amrdata` — AMR levels, refinement ratios, regions
- `gaugedata` — monitoring point locations

---

## 8. Output Formats

### 8.1 Solution Files (fort.qNNNN)

Each frame NNNN contains all AMR grid patches at that output time.
Variables per cell:
- `q[0]` = h (water depth, meters)
- `q[1]` = hu (x-momentum, m²/s)
- `q[2]` = hv (y-momentum, m²/s)
- Surface elevation: η = h + B (computed, not stored)

### 8.2 Gauge Files (fort.gauge)

Time series at specified monitoring points.
Columns: `level  time  q[0]  q[1]  q[2]  eta  aux[0]`

### 8.3 FGout Files (fixed grid output)

Interpolated solution on a fixed uniform grid at specified times.
Useful for comparison with tide gauges or other observations.

### 8.4 FGmax Files (maximum values)

Tracks maximum values over the entire simulation:
- Maximum depth, surface elevation, speed
- Arrival time of first wave

---

## 9. Calibration Parameters

Parameters listed in order of sensitivity for tsunami/surge applications:

| Parameter | Default | Range | Sensitivity |
|-----------|---------|-------|-------------|
| Manning coefficient | 0.025 | 0.01–0.06 | High — controls inundation extent |
| dry_tolerance | 1e-3 m | 1e-4–1e-2 | Medium — affects shoreline |
| sea_level | 0.0 m | varies | High — sets initial water surface |
| wave_tolerance | 1e-2 | 1e-3–1e-1 | Medium — controls AMR triggering |
| cfl_desired | 0.75 | 0.5–0.9 | Low — affects time step size |
| amr_levels_max | 2 | 1–6 | High — resolution at coast |
| friction_depth | 1e6 | 20–1e6 | Low — depth limit for friction |
| speed_limit | 50 m/s | 20–100 | Low — caps unrealistic velocities |

---

## 10. Quick Start

```bash
# 1. Install clawpack
pip install clawpack

# 2. Set environment
export CLAW=$(python -c "import clawpack; print(clawpack.__path__[0])")

# 3. Run bowl-slosh test case
cd $CLAW/geoclaw/examples/tsunami/bowl-slosh
python maketopo.py
make .exe
make .output
make .plots

# 4. Parse output
python tools/parse_geoclaw_output.py \
  --output-dir $CLAW/geoclaw/examples/tsunami/bowl-slosh/_output \
  --format csv --outfile results.csv

# 5. Check gauge output
head _output/fort.gauge
```

---

## 11. Diagnostic Triplets Summary

| Domain | Count | Examples |
|--------|-------|---------|
| Unit conversion | 5 | Bathymetry sign, coordinate mismatch, time units |
| Parameter format | 4 | AMR ratios, CFL bounds, topo coverage |
| Runtime errors | 4 | NaN divergence, memory overflow, Fortran crash |
| Silent errors | 3 | Wrong inundation, missing friction, gauge outside domain |
| Dependency | 2 | Missing Fortran compiler, clawpack not found |

See `diagnostics/triplets.yaml` for the full 18-entry diagnostic database.

---

## 12. File Structure

```
ki/
├── SKILL.md                           # This file
├── tools/
│   ├── convert_bathymetry.py          # Topo/bathy format converter
│   ├── generate_setrun.py            # setrun.py generator from JSON
│   ├── run_geoclaw.py                # Execution wrapper
│   └── parse_geoclaw_output.py       # Output → CSV parser
├── docs/
│   ├── s1_bathymetry_preparation.md  # Stage 1 skill doc
│   ├── s2_earthquake_source.md       # Stage 2 skill doc
│   ├── s3_configuration.md           # Stage 3 skill doc
│   ├── s5_execution.md              # Stage 5 skill doc
│   └── s6_output_analysis.md        # Stage 6 skill doc
└── diagnostics/
    └── triplets.yaml                  # 18 symptom→diagnosis→remedy entries
```

---

## 13. Coupling Points

GeoClaw can be coupled with other models at these interfaces:

| Coupling Point | External Model | Interface |
|----------------|---------------|-----------|
| Bathymetry input | GEBCO, ETOPO, SRTM | topo files (Type 1-4) |
| Storm forcing | WRF, HWRF, IBTrACS | surge.data (wind + pressure fields) |
| Earthquake source | USGS CMT, custom faults | dtopo files via Okada model |
| Downstream routing | HEC-RAS, CaMa-Flood | Gauge output → boundary conditions |
| Wave input | SWAN, WaveWatch III | Boundary condition files |
| Inundation mapping | GIS (QGIS, ArcGIS) | FGmax output → raster |
