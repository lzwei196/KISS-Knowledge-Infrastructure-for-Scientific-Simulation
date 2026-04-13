# CE-QUAL-W2 — Knowledge Dissection Plan

**Package**: `hydrocraft-cequalw2-reservoir` v0.1.0
**Target model**: CE-QUAL-W2 v4.5 (or latest v4.x)
**Priority**: HIGH — HydroCraft has GLM (1D lake) but lacks 2D reservoir capability for elongated reservoirs where longitudinal gradients matter (Three Gorges, Danjiangkou)
**Created**: 2026-03-23
**Author**: Jianyun Zhang Research Group, Hohai University

---

## 1. Model Overview

### What CE-QUAL-W2 Does

CE-QUAL-W2 (Corps of Engineers Quality Model for Wide and Two-dimensional) is a **2D laterally-averaged hydrodynamic and water quality model** developed by the U.S. Army Corps of Engineers (USACE) and Portland State University (PSU). It solves the equations of fluid motion in the longitudinal (x) and vertical (z) dimensions, assuming lateral (y) homogeneity.

**Core physics**:
- **2D hydrodynamics**: Laterally-averaged momentum, continuity, and free-surface equations on a longitudinal-vertical grid. Uses hydrostatic pressure assumption.
- **Thermal stratification**: Full energy balance including shortwave/longwave radiation, evaporation, conduction, sediment heat exchange. Vertically and longitudinally resolved temperature fields.
- **Density currents**: Models selective withdrawal, density-driven inflows (plunging, interflow, overflow), and internal seiches driven by longitudinal density gradients.
- **Multi-branch topology**: Reservoirs with complex geometry (main stem + arms/tributaries) are represented as a connected branch network. Each branch has its own segment-layer grid.
- **Water quality**: 21+ state variables including temperature, dissolved oxygen, BOD/CBOD, nutrients (NH4, NO3, PO4, TN, TP), algae (up to 10 groups), organic matter, sediment diagenesis, pH, alkalinity, total dissolved gas, zooplankton, macrophytes, and generic constituents.
- **Ice cover**: Dynamic ice formation, growth, and decay.
- **Selective withdrawal**: Models withdrawal from specific elevations (critical for dam operations).

### Technical Specifications

| Attribute | Value |
|-----------|-------|
| Language | Fortran 90/95 (primary), with pre/post-processing tools in various languages |
| Current version | v4.5 (PSU, 2024); USACE version v3.72/4.0 also in use |
| Primary developer | Scott Wells, Portland State University |
| USACE maintainer | Thomas Cole, ERDC-EL |
| Reference papers | Cole & Wells (2006, 2018), Wells (2019, 2021) |
| License | Public domain (US government work); PSU version has open distribution |
| Repository | https://github.com/EnvironmentalSystems/CE-QUAL-W2 (PSU v4.5, open source) |
| USACE distribution | https://www.erdc.usace.army.mil/Software/ (v3.72, registration required) |
| Config format | Fixed-width text control file (`w2_con.npt`) + multiple auxiliary input files |
| Forcing format | Fixed-width text (meteorological, inflow, outflow, WQ constituent files) |
| Output format | Fixed-width text (snapshot, profile, time series) + optional NetCDF (v4.5) |
| Timestep | Adaptive (CFL-limited), typically 1-60 seconds |
| Spatial dimensions | 2D laterally-averaged (longitudinal x vertical) |
| Grid structure | Segments (longitudinal) x Layers (vertical), with variable widths |
| Branches | Up to 100+ branches (main stem + tributaries/arms) |
| Water bodies | Multiple connected water bodies (e.g., cascade reservoirs) |
| Companion tools | W2Viewer, AGPM (Automated Grid Pre-processor), PSU preprocessors |

### Key Difference from GLM (1D)

| Feature | GLM (1D) | CE-QUAL-W2 (2D) |
|---------|----------|------------------|
| **Spatial representation** | Single water column (depth only) | Longitudinal-vertical grid (distance x depth) |
| **Lateral averaging** | N/A (no horizontal) | Assumes lateral homogeneity |
| **Reservoir shape** | Cylindrical/conical approximation | Actual cross-section widths at each segment-layer cell |
| **Inflow routing** | Density insertion at one depth | Inflow enters at specific segment, density-driven routing through reservoir |
| **Longitudinal gradients** | Not modeled | Explicitly resolved (key for elongated reservoirs) |
| **Selective withdrawal** | Single elevation | Multi-level, multi-structure withdrawal with mixing |
| **Multi-branch** | Single basin | Connected branch network (arms, tributaries) |
| **Water quality** | AED2 library (optional plugin) | Built-in WQ (21+ constituents, tightly coupled) |
| **Grid complexity** | ~Minutes to set up | Hours to days (bathymetry digitization, branch connectivity) |
| **Typical runtime** | Seconds to minutes | Minutes to hours (adaptive timestep, CFL-limited) |
| **Best suited for** | Round/compact lakes, quick assessments | Elongated reservoirs, rivers, estuaries, detailed WQ studies |

**When to use CE-QUAL-W2 instead of GLM**:
- Reservoir length-to-width ratio > 5:1 (longitudinal gradients significant)
- Need to model inflow routing through the reservoir (e.g., turbidity currents)
- Multiple inflow tributaries entering at different locations along the reservoir
- Selective withdrawal from multiple dam outlets at different elevations
- Need longitudinal temperature/WQ profiles (not just vertical)
- Reservoir has arms/branches with distinct characteristics
- Regulatory water quality modeling (USACE/EPA standards)

**When GLM is sufficient**:
- Compact/round lakes (Taihu, most natural lakes)
- Quick thermal stratification assessment
- Global/regional screening studies (faster setup)
- Ice cover focus (GLM's ice model is well-validated)

---

## 2. Why CE-QUAL-W2 is Critical for HydroCraft

### Gap Analysis

GLM (validated on Miyun Reservoir, 2026-03-22) provides 1D vertical lake modeling. However, China's most important reservoirs are **elongated**:

| Reservoir | Length (km) | Width (km) | L:W Ratio | Max Depth (m) | Why 2D Matters |
|-----------|-----------|-----------|-----------|---------------|----------------|
| **Three Gorges** (三峡) | 660 | 1.1 | 600:1 | 175 | Turbidity currents from Yangtze, selective withdrawal, cascade operation |
| **Danjiangkou** (丹江口) | 80+ | ~5 | 16:1 | 80 | South-to-North Water Transfer source, water quality critical |
| **Xiaolangdi** (小浪底) | 130 | ~2 | 65:1 | 165 | Yellow River sediment management, density currents |
| **Longyangxia** (龙羊峡) | 150 | ~3 | 50:1 | 190 | Highest dam on Yellow River, cold-water releases |
| **Ertan** (二滩) | 101 | ~1 | 100:1 | 240 | Yalong River cascade, thermal pollution downstream |

For these reservoirs, 1D models like GLM are physically inadequate because:
1. **Inflow routing**: Sediment-laden inflows from the Yangtze travel 100+ km through Three Gorges before reaching the dam. GLM cannot model this transit.
2. **Longitudinal temperature gradients**: Water near the upstream end of a reservoir can be several degrees warmer/colder than near the dam.
3. **Selective withdrawal effects**: Three Gorges has multi-level outlets at 90m, 120m, and 155m. The downstream temperature depends on which outlet is used and where the thermocline is relative to each outlet.
4. **Tributary arms**: Danjiangkou has distinct Han River and Dan River arms with different water quality.

### Strategic Value

CE-QUAL-W2 makes HydroCraft the first AI platform capable of **2D reservoir simulation** — from precipitation (VIC) through river routing (CaMa-Flood) through 2D reservoir hydrodynamics and water quality (CE-QUAL-W2) to downstream impact assessment. Combined with GLM for compact lakes, HydroCraft covers the full spectrum of lentic water bodies.

### Synergy with GLM

The two models are complementary:
- **GLM** for rapid screening, compact lakes, global studies (fast setup, seconds to run)
- **CE-QUAL-W2** for detailed engineering studies on elongated reservoirs (complex setup, minutes to hours to run)
- Shared forcing pipeline (both use CMFD/MSWX meteorology)
- Shared coupling interface (both receive CaMa-Flood inflows, both produce outflow to CaMa-Flood)
- The agent can auto-select based on reservoir geometry: L:W > 5 suggests CE-QUAL-W2; L:W < 5 suggests GLM

---

## 3. Installation Plan

### Source Code Acquisition

**Recommended**: PSU v4.5 from GitHub (open source, actively maintained):
```bash
git clone https://github.com/EnvironmentalSystems/CE-QUAL-W2.git
```

**Alternative**: USACE v3.72 from ERDC (requires registration, more conservative but well-documented):
```
https://www.erdc.usace.army.mil/Software/
```

The PSU v4.5 is recommended because:
- Open source on GitHub (no registration barrier)
- More active development (Scott Wells' group)
- Includes modern Fortran features, optional NetCDF output
- Better documentation of recent changes
- Backwards-compatible with v3.x input files (mostly)

### Compilation from Fortran Source

CE-QUAL-W2 is written in Fortran 90/95. Compilation requires:

**Dependencies**:
- Fortran compiler: `gfortran` (GNU) or `ifort` (Intel)
- C compiler: `gcc` (for C interface routines, if any)
- NetCDF-Fortran library (optional, for NetCDF output in v4.5)
- Make / CMake (build system)

**Compilation steps** (estimated):
```bash
# Install dependencies
sudo apt install gfortran libnetcdf-dev libnetcdff-dev

# Clone source
git clone https://github.com/EnvironmentalSystems/CE-QUAL-W2.git
cd CE-QUAL-W2

# Build (exact steps depend on the repository structure)
# Option A: If Makefile provided
cd src
make

# Option B: If CMakeLists.txt provided
mkdir build && cd build
cmake ..
make -j$(nproc)

# Option C: Manual compilation (if no build system)
gfortran -O2 -o w2.exe *.f90 -lnetcdff -lnetcdf
```

**Known Fortran compilation pitfalls**:
- CE-QUAL-W2 source may assume Intel Fortran compiler (`ifort`) syntax in some files
- Fixed-form vs free-form Fortran source files may be mixed (.f vs .f90)
- Character string widths: some versions use CHARACTER*72 for file paths (Fortran path truncation trap from PREFLIGHT.md)
- Array dimension limits may be hardcoded as PARAMETER statements — check and increase for large reservoirs
- Some versions require specific compiler flags (-ffixed-line-length-132, -fdefault-real-8)

### Target Installation Location

```
model/ce_qual_w2/
  bin/w2.exe                     # CE-QUAL-W2 executable
  src/                           # Source code (for recompilation)
  examples/                      # Reference examples
    DeGray/                      # DeGray Lake, Arkansas (classic USACE example)
    RiverSystem/                 # River example
    Branch/                      # Multi-branch example
  docs/                          # User manual PDF
    CE-QUAL-W2_User_Manual.pdf
```

### Python Dependencies

```
numpy, pandas, xarray, netCDF4, geopandas, shapely, matplotlib, scipy
```

All already available in the HydroCraft venv. No additional Python packages needed for core operation. The model binary is standalone Fortran — Python tools are for pre/post-processing only.

### Pre/Post-Processors

CE-QUAL-W2 has several companion tools. Assess which to install:

| Tool | Source | Purpose | Priority |
|------|--------|---------|----------|
| W2Viewer | PSU website | Windows GUI for viewing output | LOW (we'll build Python tools) |
| AGPM | PSU | Automated grid pre-processor | MEDIUM (evaluate if useful for bathymetry) |
| PSU preprocessors | GitHub repo | Various input file generators | HIGH (may contain useful algorithms to wrap) |
| w2_post | In repo? | Post-processing utilities | HIGH (wrap if available) |

---

## 4. Input/Output File Format Analysis

### CE-QUAL-W2 Input Files (Fixed-Width Text)

CE-QUAL-W2 uses a **large number of input files**, all in fixed-width Fortran-readable format. This is the single biggest complexity difference from GLM (which uses one namelist file + CSV).

#### Master Control File: `w2_con.npt`

The main configuration file. Contains ~50+ card groups (sections) that define the entire simulation. Each card has a fixed-width format with 8-character fields.

**Critical card groups** (partial list):

| Card Group | Purpose | Key Parameters |
|------------|---------|---------------|
| `TITLE` | Simulation title (3 lines) | Text description |
| `GRID` | Grid dimensions | NWB (water bodies), NBR (branches), IMX (max segments), KMX (max layers) |
| `TIME` | Simulation period | TMSTRT (Julian start), TMEND (Julian end), YEAR |
| `CALCU` | Calculation controls | CONSTITUENTS (active constituents on/off) |
| `BRANCH` | Branch geometry | US (upstream segment), DS (downstream segment), slope, friction |
| `INIT CND` | Initial conditions | T2I (initial temp), ELBOT (bottom elevation) |
| `MET DATA` | Meteorological file paths | METFN (met file name per water body) |
| `INFLOW` | Inflow configuration | Branch/tributary inflow file paths, NSTR (number of structures) |
| `OUTFLOW` | Outflow/withdrawal | NSTR, outlet elevations, widths |
| `HYD COEF` | Hydraulic coefficients | AX (longitudinal eddy viscosity), DX (longitudinal dispersion), CBHE (bottom heat exchange) |
| `CONSTITU` | Constituent switches | On/off for each WQ constituent |
| `EX COEF` | Extinction coefficients | EXH2O (pure water), EXSS, EXOM, BETA (shortwave fraction) |
| `OUT FILE` | Output file controls | Snapshot, profile, time series, spreadsheet output |

**Format example** (8-character fixed-width fields):
```
GRID     NWB  NBR  IMX  KMX NPROC CLOSEC
           1    2   48   32     1    OFF
```

#### Bathymetry File: `bth_wb1.npt` (per water body)

Defines the cross-section widths at every segment-layer cell. This is the most labor-intensive input.

Format: Each row is one layer depth. Columns are segment widths (m) at that depth.

```
$ Segment:    2       3       4       5       6   ...
     0.00  200.0   250.0   300.0   350.0   280.0
     1.00  195.0   245.0   295.0   340.0   275.0
     2.00  190.0   238.0   285.0   330.0   268.0
     ...
```

**Critical**: This is a matrix of (KMX layers) x (IMX segments) values. For a large reservoir like Three Gorges, this could be 100 layers x 600 segments = 60,000 values. Automated generation from DEM/bathymetry data is essential.

#### Meteorological File: `met_wb1.npt` (per water body)

Fixed-width columns with daily or sub-daily weather data:

| Column | Variable | Unit |
|--------|----------|------|
| JDAY | Julian day (decimal) | day of year |
| TAIR | Air temperature | deg C |
| TDEW | Dewpoint temperature | deg C |
| WIND | Wind speed | m/s |
| WDIR | Wind direction | degrees (or radians, version-dependent) |
| CLOUD | Cloud cover | 0.0-10.0 (tenths, **NOT fraction 0-1**) |
| SRO | Shortwave radiation (optional) | W/m^2 |

**Unit traps**:
- Cloud cover is 0-10 (tenths), NOT 0-1 fraction and NOT 0-100 percent
- Wind direction may be in radians or degrees depending on version
- TDEW is dewpoint, not relative humidity. Conversion: `TDEW = (237.3 * ln(VP/0.6108)) / (17.27 - ln(VP/0.6108))`
- Julian day is decimal (e.g., 1.5 = noon on Jan 1), NOT integer day number

#### Inflow File: `qin_br1.npt` (per branch)

Fixed-width columns:
```
JDAY       QIN
  1.00    150.0
  2.00    148.5
  3.00    155.2
```

| Variable | Unit | Notes |
|----------|------|-------|
| QIN | m^3/s | Inflow discharge |
| TIN | deg C | Inflow temperature (separate file: `tin_br1.npt`) |
| CIN | varies | Constituent concentrations (separate file: `cin_br1.npt`) |

#### Other Input Files

| File Pattern | Purpose | One per... |
|-------------|---------|-----------|
| `bth_wb*.npt` | Bathymetry widths | Water body |
| `met_wb*.npt` | Meteorology | Water body |
| `qin_br*.npt` | Inflow discharge | Branch |
| `tin_br*.npt` | Inflow temperature | Branch |
| `cin_br*.npt` | Inflow constituents | Branch |
| `qot_*.npt` | Outflow discharge | Structure |
| `qdt_*.npt` | Distributed tributary flow | Branch |
| `tdt_*.npt` | Distributed tributary temp | Branch |
| `shd_wb*.npt` | Shade/topographic shading | Water body |
| `vpr_wb*.npt` | Vertical profile output control | Water body |
| `spr_wb*.npt` | Snapshot output control | Water body |
| `wsc_wb*.npt` | Wind sheltering coefficients | Water body |

### CE-QUAL-W2 Output Files

| File | Content | Format |
|------|---------|--------|
| `snp_wb*.opt` | Snapshots (full 2D field at specified times) | Fixed-width text |
| `prf_wb*.opt` | Vertical profiles at specified locations | Fixed-width text |
| `tsr_*.opt` | Time series at specified segment-layer cells | Fixed-width text |
| `spr_wb*.opt` | Spreadsheet-format output | Tab/comma-delimited |
| `w2l.opt` | Warning/log messages | Text |
| `pre.opt` | Preprocessor output (grid verification) | Text |
| `*.nc` | NetCDF output (v4.5 option) | NetCDF4 |

---

## 5. Pipeline Stages

### Stage Overview

| # | Stage ID | Name | Description | Est. Tools |
|---|----------|------|-------------|------------|
| 0 | s0_config | Configuration | Reservoir selection, period, forcing source, WQ toggle | 0 (manual) |
| 1 | s1_bathymetry | Bathymetry & Grid | DEM/cross-section data to segment-layer grid + `bth_wb*.npt` | 3 |
| 2 | s2_branch_topology | Branch Connectivity | Define branches, upstream/downstream segments, slopes | 1 |
| 3 | s3_met_forcing | Meteorological Forcing | CMFD/MSWX to CE-QUAL-W2 met format | 1 |
| 4 | s4_inflow | Inflow Preparation | CaMa-Flood/VIC discharge + temperature to inflow files | 2 |
| 5 | s5_outflow | Outflow Configuration | Dam operation rules, selective withdrawal elevations | 1 |
| 6 | s6_init_conditions | Initial Conditions | Initial temperature/WQ profiles (longitudinal + vertical) | 1 |
| 7 | s7_hydraulic_params | Hydraulic Parameters | Eddy viscosity, dispersion, friction, bottom heat exchange | 1 |
| 8 | s8_wq_config | Water Quality Configuration | Constituent activation, rate coefficients, algae groups | 1 |
| 9 | s9_control_file | Control File Assembly | Build `w2_con.npt` from all upstream stage outputs | 1 |
| 10 | s10_execution | Model Execution | Run CE-QUAL-W2 binary, monitor, validate output | 1 |
| 11 | s11_output_analysis | Output Analysis | Parse snapshots/profiles/timeseries, visualize 2D fields | 3 |
| 12 | s12_calibration | Calibration | Multi-objective calibration (T, DO, nutrients) | 1 |
| 13 | s13_coupling | Upstream/Downstream Coupling | CaMa-Flood inflow, GLM comparison, dam breach WQ | 1 |

### Stage Dependencies

```
s0_config
  |
  +---> s1_bathymetry -----+
  |       |                |
  |       v                |
  |     s2_branch_topology |
  |                        |
  +---> s3_met_forcing ----+
  |                        |
  +---> s4_inflow ---------+
  |                        |
  +---> s5_outflow --------+---> s9_control_file ---> s10_execution
  |                        |                                |
  +---> s6_init_conditions +                                v
  |                        |                       s11_output_analysis
  +---> s7_hydraulic_params+                                |
  |                        |                                v
  +---> s8_wq_config ------+                       s12_calibration
                                                            |
                                                            v
                                                   s13_coupling
```

**Parallelism**: Stages s1 through s8 can largely run in parallel after s0 (with s2 depending on s1). Stage s9 depends on all of s1-s8. Stage s10 depends on s9.

---

## 6. Detailed Stage Specifications

### s0_config: Configuration

**User inputs required**:
- Reservoir name or coordinates (lat/lon of dam)
- Simulation period (start_year, end_year)
- Forcing dataset (CMFD / MSWX / NASA POWER)
- Enable water quality (yes/no, and which constituents)
- Dam operation mode (observed releases / rule-based / constant)
- Calibration data availability (temperature profiles, DO, nutrients)

**Key decisions at this stage**:
- Grid resolution: segment length (typically 250-2000 m) and layer thickness (typically 0.5-2.0 m)
- Number of water bodies and branches
- Active constituents (temperature always on; DO, nutrients, algae optional)
- Output frequency and variables

### s1_bathymetry: Bathymetry & Grid Generation

**Purpose**: Convert reservoir geometry (DEM, cross-sections, published data) into the segment-layer grid and `bth_wb*.npt` files.

This is the **most complex and labor-intensive stage** of CE-QUAL-W2 setup. For HydroCraft automation, we need:

1. **DEM-based approach** (for any reservoir worldwide):
   - Clip DEM (China 90m or Copernicus GLO-30) to reservoir extent
   - Identify the reservoir thalweg (deepest path from upstream to dam)
   - Generate cross-sections at regular intervals along the thalweg
   - Extract widths at each elevation from cross-section intersections with DEM
   - Build the segment-layer width matrix

2. **Published bathymetry** (for well-studied reservoirs):
   - Literature/databases with surveyed cross-sections
   - National Dam Safety Administration data (China)

3. **Idealized geometry** (quick estimation):
   - From HydroLAKES: total area, max depth, volume
   - Assume trapezoidal cross-section with linearly varying width along length
   - Useful for initial screening before detailed bathymetry is available

**Bathymetry file format**: Matrix of widths (m) with rows = layers (top to bottom), columns = segments (upstream to downstream). Include boundary segments (segments 1 and IMX) with zero width.

**Grid sizing guidelines**:

| Reservoir Length | Segment Length | Typical IMX |
|-----------------|---------------|-------------|
| < 10 km | 250-500 m | 20-40 |
| 10-50 km | 500-1000 m | 20-100 |
| 50-200 km | 1000-2000 m | 50-200 |
| > 200 km (Three Gorges) | 1000-2000 m | 200-660 |

| Max Depth | Layer Thickness | Typical KMX |
|-----------|----------------|-------------|
| < 20 m | 0.5-1.0 m | 20-40 |
| 20-100 m | 1.0-2.0 m | 20-100 |
| > 100 m | 1.0-2.0 m | 50-200 |

### s2_branch_topology: Branch Connectivity

**Purpose**: Define the multi-branch network (main stem, arms, tributaries).

**Key parameters per branch**:
- `UHS`: Upstream head segment
- `DHS`: Downstream head segment (of the receiving branch; negative = external boundary)
- `US`: Upstream active segment
- `DS`: Downstream active segment
- `SLOPE`: Average channel slope (m/m)
- `STEFR`: Friction slope method
- `NSTR`: Number of outlet structures on this branch

**Branch connectivity rules**:
- Each branch is a linear sequence of segments
- Branches connect at specific segments (confluence points)
- Water body boundaries separate branches with different properties
- The dam is at the downstream end of the most downstream branch

**Multi-branch examples relevant to HydroCraft**:
- **Danjiangkou**: 2 branches (Han River main stem + Dan River arm)
- **Three Gorges**: Could be modeled as 1 very long branch or 3-5 sub-branches at major tributaries
- **Miyun**: 2 branches (Chaohe + Baihe arms)

### s3_met_forcing: Meteorological Forcing

**Purpose**: Convert HydroCraft forcing data to CE-QUAL-W2 `met_wb*.npt` format.

**Unit conversions** (CRITICAL):

| CE-QUAL-W2 Variable | CE-QUAL-W2 Unit | CMFD/MSWX Source | Conversion |
|---------------------|-----------------|------------------|------------|
| TAIR | deg C | AIR_TEMP (deg C) | Direct |
| TDEW | deg C | VP (kPa) | `TDEW = (237.3 * ln(VP/0.6108)) / (17.27 - ln(VP/0.6108))` |
| WIND | m/s | WIND (m/s) | Direct |
| WDIR | degrees or radians | Not in CMFD/MSWX | Default 0.0 or 270 (westerly); **check version** |
| CLOUD | 0-10 (tenths) | Not direct in CMFD | Derive from SW radiation: `CLOUD = 10 * (1 - SW_actual / SW_clearsky)` |
| SRO | W/m^2 (optional) | SW_DOWN (W/m^2) | Direct (if measured SW is provided, better than cloud-derived) |

**Unit trap**: Cloud cover in **tenths (0-10)**, NOT fraction (0-1) and NOT percent (0-100). This is a classic CE-QUAL-W2 silent error. If cloud cover is given as 0-1 fraction, the model sees nearly clear sky always, resulting in too much shortwave radiation and warm-biased temperatures.

**Julian day format**: CE-QUAL-W2 uses decimal Julian day (JDAY) where 1.0 = midnight Jan 1, 1.5 = noon Jan 1, 2.0 = midnight Jan 2. This is the **day of year**, NOT Julian Date (astronomical). Conversion from datetime: `JDAY = day_of_year + hour/24 + minute/1440`.

**Met file format** (fixed-width):
```
$Met file for water body 1
  JDAY      TAIR      TDEW      WIND      WDIR     CLOUD       SRO
  1.000    -5.200    -8.100     3.100   270.000     7.000     0.000
  1.125    -5.500    -8.400     2.800   270.000     7.000     0.000
  1.250    -5.800    -8.700     2.500   270.000     7.000    85.600
```

### s4_inflow: Inflow Preparation

**Purpose**: Convert CaMa-Flood/VIC discharge and water quality to CE-QUAL-W2 inflow files.

**Files to generate per inflow**:
1. `qin_br*.npt` — discharge (m^3/s) vs Julian day
2. `tin_br*.npt` — inflow temperature (deg C) vs Julian day
3. `cin_br*.npt` — constituent concentrations vs Julian day (if WQ enabled)

**Inflow types in CE-QUAL-W2**:
- **Branch inflows**: Enter at the upstream end of a branch (major tributaries)
- **Tributary inflows**: Enter at a specific segment along a branch (side streams)
- **Distributed tributary inflows**: Diffuse lateral inflow along multiple segments (ungauged runoff)

**Temperature estimation** (when observed inflow temperature is unavailable):
- Same approach as GLM: `T_inflow = a * T_air + b` (regression coefficients vary by climate)
- CE-QUAL-W2 can also compute equilibrium temperature internally

**Constituent concentrations** (if WQ enabled):
- Dissolved oxygen: estimate from saturation at inflow temperature
- Nutrients: from SWAT+ output or literature values
- Suspended solids: from sediment rating curve

### s5_outflow: Outflow Configuration

**Purpose**: Configure dam outlets, spillways, and withdrawal structures.

**CE-QUAL-W2 outlet types**:
1. **Line sink**: Withdrawal from a horizontal line at a specified elevation
2. **Point sink**: Withdrawal from a single point (segment, layer)
3. **Floating offtake**: Withdrawal from near the water surface
4. **Overflow/spillway**: When water surface exceeds a specified elevation

**Key parameters**:
- `NSTR`: Number of outlet structures per branch
- `KTSTR`: Top layer of withdrawal zone
- `KBSTR`: Bottom layer of withdrawal zone
- `STEFR`: Structure elevation (m ASL)
- `WSTR`: Structure width (m)

**Selective withdrawal**: CE-QUAL-W2's selective withdrawal algorithm is critical for modeling temperature release from dams. The withdrawal zone depends on:
- Outlet elevation relative to thermocline
- Withdrawal rate relative to available head
- Density stratification strength

**For Chinese reservoirs**: Multi-level outlet structures are common (e.g., Three Gorges has outlets at 90m, 120m, and 155m). The tool must support time-varying switching between outlets.

### s6_init_conditions: Initial Conditions

**Purpose**: Set initial water surface elevation, temperature profiles, and (optionally) constituent concentrations for all segments and layers.

**Key difference from GLM**: CE-QUAL-W2 requires **2D initial conditions** (longitudinal x vertical), not just 1D vertical profiles. In practice, this often starts as:
- Uniform temperature throughout
- Or longitudinally varying initial temperature (warmer upstream, cooler near dam)
- Initial water surface elevation (ELWS)

**Initial condition card in w2_con.npt**:
- `T2I`: Initial temperature (deg C) — can be single value or profile
- `ELBOT`: Bottom elevation for each segment
- `ELWS`: Initial water surface elevation (m ASL)

**Spinup**: 1-2 year spinup recommended, same as GLM. CE-QUAL-W2's adaptive timestep helps stabilize faster.

### s7_hydraulic_params: Hydraulic Parameters

**Purpose**: Set eddy viscosity, dispersion, bottom friction, and other hydraulic coefficients.

**Key parameters**:

| Parameter | Symbol | Typical Range | Controls |
|-----------|--------|--------------|----------|
| Longitudinal eddy viscosity | AX | 0.1 - 10 m^2/s | Longitudinal momentum diffusion |
| Longitudinal dispersion | DX | 0.1 - 100 m^2/s | Longitudinal mass/heat dispersion |
| Chezy coefficient | CHEZY | 30 - 100 | Bottom friction (alternative: Manning's n) |
| Wind sheltering coefficient | WSC | 0.5 - 1.0 | Wind reduction by topography |
| Bottom heat exchange coefficient | CBHE | 0.3 - 1.5 W/m^2/deg C | Sediment heat flux |
| Sediment temperature | TSED | 5 - 15 deg C | Sediment boundary temperature |
| Fraction of SW absorbed at surface | BETA | 0.3 - 0.6 | Light penetration partitioning |
| Light extinction coefficient | EXH2O | 0.1 - 1.0 m^-1 | Background water clarity |

**Calibration sensitivity**: AX and DX control longitudinal mixing and are among the most sensitive parameters. WSC controls wind-driven circulation and surface mixing.

### s8_wq_config: Water Quality Configuration

**Purpose**: Configure which WQ constituents are active and set their kinetic rate coefficients.

**CE-QUAL-W2 WQ constituents** (21+ variables):

| Group | Variables | Key Rates |
|-------|----------|-----------|
| Temperature | T2 | (always active, driven by energy balance) |
| Dissolved oxygen | DO | SOD (sediment oxygen demand), Reaeration |
| CBOD (Carbonaceous BOD) | CBOD1-5 | Decay rate, settling velocity |
| Algae | ALG1-10 | Growth rate, mortality, settling, nutrient uptake |
| Organic matter | LDOM, RDOM, LPOM, RPOM | Decay rates |
| Phosphorus | PO4 | Sediment release, algal uptake |
| Ammonium | NH4 | Nitrification rate |
| Nitrate | NO3 | Denitrification rate |
| Dissolved silica | DSI | Diatom uptake |
| Particulate silica | PSI | Settling |
| Labile DOM | LDOM | Decay rate |
| Refractory DOM | RDOM | Decay rate |
| Total dissolved solids | TDS | Conservative |
| Inorganic suspended solids | ISS | Settling velocity |
| Iron | Fe | Redox cycling |
| Generic constituents | GEN1-n | User-defined kinetics |
| Zooplankton | ZOO1-n | Grazing rate |
| Macrophytes | MAC1-n | Growth rate |

**Recommended WQ configurations**:
1. **Temperature only**: For initial hydrodynamic validation (fastest)
2. **T + DO + Nutrients**: Standard water quality study
3. **T + DO + Nutrients + Algae**: Eutrophication assessment
4. **Full suite**: Research/regulatory applications

### s9_control_file: Control File Assembly

**Purpose**: Assemble `w2_con.npt` and all auxiliary input files into a consistent, valid model input package.

This is the **most error-prone stage** because:
- `w2_con.npt` is a single large fixed-width text file with ~50 card groups
- Card field widths are typically 8 characters — off-by-one errors are catastrophic
- Many parameters cross-reference segment/layer indices from the bathymetry
- Constituent on/off flags must be consistent with inflow concentration files

**Validation checks** the assembly tool must perform:
1. Segment count in `w2_con.npt` matches bathymetry file columns
2. Layer count matches bathymetry file rows
3. Branch upstream/downstream segment references are valid
4. All referenced input files exist and have correct format
5. Simulation period is consistent across all time-series files
6. Active constituent flags match available inflow concentration data
7. Outlet structure elevations are within the bathymetry elevation range
8. Initial water surface elevation is above bottom elevation everywhere

### s10_execution: Model Execution

**Command**:
```bash
cd <run_dir>
./w2.exe
# or
/path/to/w2.exe   (some versions read w2_con.npt from current directory)
```

CE-QUAL-W2 reads `w2_con.npt` from the current working directory (typically). It is single-threaded. Runtime depends heavily on grid size and timestep:

| Grid Size (seg x layers) | Simulation Period | Expected Runtime |
|--------------------------|------------------|-----------------|
| 20x20 (small reservoir) | 1 year | 1-5 minutes |
| 50x50 (medium reservoir) | 1 year | 5-30 minutes |
| 100x100 (large reservoir) | 1 year | 30-120 minutes |
| 500x100 (Three Gorges scale) | 1 year | 2-12 hours |

**Adaptive timestep**: CE-QUAL-W2 uses CFL-based adaptive timestepping. The minimum timestep can drop to ~1 second during high-flow events, dramatically increasing runtime. Monitor via `w2l.opt` log file.

**Common runtime errors**:
- STOP with error code in `w2l.opt` — check log for cause
- NaN in output — usually from unstable timestep (increase grid resolution or reduce max dt)
- Zero output — model ran but wrote no data (check output card group in `w2_con.npt`)

### s11_output_analysis: Output Analysis

**Key visualizations for 2D results**:

1. **Longitudinal-vertical temperature curtain plot**: Distance (x-axis) vs depth (y-axis), temperature (color). The signature CE-QUAL-W2 output. Show at multiple time snapshots (e.g., monthly).

2. **Vertical temperature profiles**: At dam location and upstream locations. Compare with observed profiles.

3. **Longitudinal temperature/DO/nutrient profiles**: At surface and at specific depths.

4. **Time series at dam outlet**: Temperature, DO, nutrients at the withdrawal elevation. Compare with downstream observations.

5. **Water surface elevation**: Reservoir level over time.

6. **Inflow/outflow water balance**: Verify mass conservation.

7. **2D velocity field** (if available): Show circulation patterns during stratification.

### s12_calibration: Calibration

**Calibration parameters** (priority order):

| Priority | Parameter | Controls | Range |
|----------|-----------|----------|-------|
| 1 | WSC | Wind sheltering, surface mixing | 0.5 - 1.0 |
| 2 | EXH2O | Light extinction, thermocline depth | 0.1 - 1.0 m^-1 |
| 3 | AX | Longitudinal mixing | 0.1 - 10 m^2/s |
| 4 | CBHE | Bottom heat exchange | 0.3 - 1.5 W/m^2/C |
| 5 | TSED | Sediment temperature | 5 - 15 deg C |
| 6 | SOD | Sediment oxygen demand (if WQ) | 0.1 - 5.0 g/m^2/day |
| 7 | Algal growth rates | Primary production (if algae) | 1.0 - 3.0 day^-1 |

**Calibration data sources**:
- Reservoir temperature profiles (Chinse water resources bulletins, published papers)
- Dam release temperature (hydropower monitoring)
- Water quality monitoring stations (Ministry of Ecology and Environment)
- Remote sensing surface temperature (Landsat thermal band, MODIS)

**Calibration approach**: GLUE-style Latin Hypercube Sampling, similar to GLM calibration tool. Objective function: multi-point RMSE of temperature profiles.

### s13_coupling: Upstream/Downstream Coupling

**Coupling points with HydroCraft**:

| # | Source | Target | Variable | Tool/Transformation |
|---|--------|--------|----------|-------------------|
| 1 | CaMa-Flood | CE-QUAL-W2 | Upstream discharge | CaMa `outflw` at reservoir inlet segment |
| 2 | VIC | CE-QUAL-W2 | Met forcing | CMFD/MSWX with unit conversion |
| 3 | VIC | CE-QUAL-W2 | Distributed tributary inflow | Local runoff from ungauged sub-basins |
| 4 | CE-QUAL-W2 | CaMa-Flood | Dam release discharge | Outflow time series at dam |
| 5 | CE-QUAL-W2 | CaMa-Flood | Dam release temperature | For downstream thermal impact |
| 6 | CE-QUAL-W2 | GLM | Comparison/validation | Same reservoir, 1D vs 2D comparison |
| 7 | SWAT+ | CE-QUAL-W2 | Nutrient loading | Upstream N/P from watershed WQ model |
| 8 | CE-QUAL-W2 | SWAT+ | Downstream WQ | Outflow WQ concentrations |
| 9 | DLBreach | CE-QUAL-W2 | Dam breach scenario | Breach hydrograph as outflow boundary |
| 10 | CMIP6 | CE-QUAL-W2 | Future climate forcing | Delta-change on met files |

---

## 7. Tools to Build

### Tool Inventory (18 tools, estimated ~8,500 lines)

| # | Tool ID | Stage | Script Path | Est. Lines | Purpose |
|---|---------|-------|-------------|-----------|---------|
| 1 | `build_reservoir_grid` | s1 | `tools/s1_bathymetry/build_reservoir_grid.py` | 700 | Generate segment-layer grid from DEM + reservoir extent. Identifies thalweg, extracts cross-sections, builds width matrix. |
| 2 | `generate_bathymetry` | s1 | `tools/s1_bathymetry/generate_bathymetry.py` | 500 | Write `bth_wb*.npt` files from the width matrix. Handles boundary segments, variable layer thickness. |
| 3 | `idealized_bathymetry` | s1 | `tools/s1_bathymetry/idealized_bathymetry.py` | 300 | Generate idealized bathymetry from HydroLAKES parameters (area, depth, length). Quick-start when no DEM bathymetry available. |
| 4 | `build_branch_topology` | s2 | `tools/s2_branch_topology/build_branch_topology.py` | 400 | Define branch connectivity from shapefile/DEM. Compute slopes, assign segment ranges, handle confluences. |
| 5 | `convert_met_to_w2` | s3 | `tools/s3_met_forcing/convert_met_to_w2.py` | 450 | Convert CMFD/MSWX to CE-QUAL-W2 met format. VP to dewpoint, cloud cover derivation, Julian day conversion. |
| 6 | `convert_inflow_to_w2` | s4 | `tools/s4_inflow/convert_inflow_to_w2.py` | 400 | Convert CaMa-Flood/VIC discharge to `qin_br*.npt` + `tin_br*.npt`. Temperature estimation. |
| 7 | `generate_distributed_inflow` | s4 | `tools/s4_inflow/generate_distributed_inflow.py` | 350 | Generate distributed tributary files (`qdt_*.npt`, `tdt_*.npt`) from VIC runoff for ungauged segments. |
| 8 | `configure_w2_outflow` | s5 | `tools/s5_outflow/configure_w2_outflow.py` | 350 | Configure dam outlets, selective withdrawal elevations, outflow time series. Multi-level outlet support. |
| 9 | `build_init_conditions` | s6 | `tools/s6_init_conditions/build_init_conditions.py` | 300 | Generate 2D initial temperature/WQ fields. Uniform, gradient, or profile-based initialization. |
| 10 | `set_hydraulic_params` | s7 | `tools/s7_hydraulic_params/set_hydraulic_params.py` | 250 | Set AX, DX, CHEZY, WSC, CBHE, TSED with validation. Auto-estimate from reservoir characteristics. |
| 11 | `configure_wq` | s8 | `tools/s8_wq_config/configure_wq.py` | 400 | Activate WQ constituents, set kinetic rates, generate constituent cards. |
| 12 | `generate_w2_control` | s9 | `tools/s9_control_file/generate_w2_control.py` | 800 | Assemble `w2_con.npt` from all upstream outputs. Comprehensive validation of cross-references. |
| 13 | `run_w2` | s10 | `tools/s10_execution/run_w2.py` | 250 | Execute CE-QUAL-W2 with preflight checks, log monitoring, success verification. |
| 14 | `parse_w2_output` | s11 | `tools/s11_output_analysis/parse_w2_output.py` | 500 | Parse snapshot, profile, and time series output files. Extract to pandas/xarray. |
| 15 | `plot_w2_curtain` | s11 | `tools/s11_output_analysis/plot_w2_curtain.py` | 400 | Generate 2D longitudinal-vertical curtain plots (temperature, DO, etc.). The signature CE-QUAL-W2 visualization. |
| 16 | `plot_w2_timeseries` | s11 | `tools/s11_output_analysis/plot_w2_timeseries.py` | 300 | Generate time series plots at specific locations (dam outlet, upstream, etc.). |
| 17 | `calibrate_w2` | s12 | `tools/s12_calibration/calibrate_w2.py` | 500 | GLUE-style calibration against observed temperature profiles. Multi-point, multi-depth objective function. |
| 18 | `w2_to_cama_coupling` | s13 | `tools/s13_coupling/w2_to_cama_coupling.py` | 300 | Convert CE-QUAL-W2 outflow to CaMa-Flood compatible format. Extract release temperature. |

**Total**: 18 tools, ~7,250 lines estimated (may increase to ~8,500 with edge case handling).

### Tool Details for Critical Tools

#### `build_reservoir_grid` (Tool #1 — Most Complex)

```
Input: DEM raster, reservoir extent shapefile, dam location (lat/lon),
       segment_length (m), layer_thickness (m)
Process:
  1. Clip DEM to reservoir extent + buffer
  2. Identify reservoir water surface from DEM (flat area at known WSE)
  3. Trace thalweg (deepest path) from upstream to dam
  4. Place cross-section lines perpendicular to thalweg at segment_length intervals
  5. For each cross-section, extract elevation profile
  6. For each layer elevation, compute width as distance between left/right bank
  7. Build width matrix: [KMX layers] x [IMX segments]
  8. Add boundary segments (segment 1 and IMX) with zero width
  9. Compute segment-averaged bottom elevation, slope
Output: bathymetry_grid.json (width matrix + metadata), segment coordinates
Edge cases:
  - DEM has no underwater bathymetry (common) — interpolate from dam depth + known profiles
  - Branches (arms) require separate thalweg traces
  - Very narrow sections where width < layer_thickness — merge cells
  - Exposed areas (islands) at low water — zero width cells
```

#### `generate_w2_control` (Tool #12 — Most Error-Prone)

```
Input: All upstream tool outputs (bathymetry, branch topology, met files,
       inflow files, outflow config, init conditions, hydraulic params, WQ config)
Process:
  1. Read all input JSONs/configs
  2. Build each of ~50 card groups in w2_con.npt
  3. CRITICAL: Format each field as exactly 8 characters (right-justified for numbers)
  4. Validate all cross-references:
     - Segment indices within [1, IMX]
     - Layer indices within [1, KMX]
     - File paths exist and have correct format
     - Constituent flags consistent with inflow data
     - Branch connectivity forms a valid tree
  5. Write w2_con.npt with correct fixed-width formatting
Output: w2_con.npt
Silent error traps:
  - Column misalignment in 8-char fields (Fortran reads by position)
  - Off-by-one in segment numbering (boundary segments vs active segments)
  - Inconsistent constituent numbering between w2_con.npt and inflow files
  - Path length > 72 chars (Fortran CHARACTER limit)
```

#### `plot_w2_curtain` (Tool #15 — Signature Visualization)

```
Input: Parsed output (from parse_w2_output), variable name, time step(s),
       segment coordinates (for x-axis distance)
Process:
  1. Extract 2D field (segment x layer) at specified time
  2. Map segment index to distance from upstream (km)
  3. Map layer index to elevation (m ASL) or depth (m)
  4. Generate filled contour plot: distance (x) vs depth (y) vs variable (color)
  5. Add bottom topography as solid fill
  6. Annotate dam location, inflow locations, withdrawal elevations
  7. Optionally: multi-panel for multiple timesteps (e.g., quarterly)
Output: PNG curtain plot
```

---

## 8. Skill Documents to Write

| # | Document ID | Stage | Path | Key Content |
|---|------------|-------|------|-------------|
| 1 | sd_s0 | s0_config | `docs/s0_configuration_skill.md` | Reservoir selection, GLM vs W2 decision guide, period constraints |
| 2 | sd_s1 | s1_bathymetry | `docs/s1_bathymetry_skill.md` | DEM-based grid generation, idealized shapes, segment/layer sizing rules, width matrix validation |
| 3 | sd_s2 | s2_branch | `docs/s2_branch_topology_skill.md` | Multi-branch setup, connectivity rules, slope computation, boundary conditions |
| 4 | sd_s3 | s3_met | `docs/s3_met_forcing_skill.md` | Unit conversion table (VP->TDEW, cloud 0-10), Julian day format, fixed-width formatting |
| 5 | sd_s4 | s4_inflow | `docs/s4_inflow_skill.md` | Inflow types (branch/tributary/distributed), temperature estimation, constituent files |
| 6 | sd_s5 | s5_outflow | `docs/s5_outflow_skill.md` | Selective withdrawal physics, multi-level outlets, dam operation modes |
| 7 | sd_s6 | s6_init | `docs/s6_init_conditions_skill.md` | 2D initialization strategies, spinup guidance, elevation consistency |
| 8 | sd_s7 | s7_hydraulic | `docs/s7_hydraulic_params_skill.md` | AX/DX estimation from reservoir geometry, WSC from topography, calibration |
| 9 | sd_s8 | s8_wq | `docs/s8_wq_config_skill.md` | Constituent selection guide, rate coefficient defaults, algae group setup |
| 10 | sd_s9 | s9_control | `docs/s9_control_file_skill.md` | w2_con.npt structure, all ~50 card groups, fixed-width formatting rules |
| 11 | sd_s10 | s10_execution | `docs/s10_execution_skill.md` | Runtime expectations, log interpretation, convergence issues |
| 12 | sd_s11 | s11_output | `docs/s11_output_analysis_skill.md` | Output file formats, curtain plot interpretation, validation metrics |
| 13 | sd_s12 | s12_calibration | `docs/s12_calibration_skill.md` | Parameter sensitivity, calibration strategy, observed data sources |
| 14 | sd_s13 | s13_coupling | `docs/s13_coupling_skill.md` | CaMa-Flood inflow/outflow coupling, GLM comparison, DLBreach scenarios |

**Total**: 14 skill documents, estimated ~12,000 words.

---

## 9. Diagnostic Triplets (Anticipated)

### By Failure Domain

#### Unit Conversion (HIGHEST PRIORITY — Silent Errors)

| ID | Stage | Symptom | Root Cause | Remedy | Severity |
|----|-------|---------|------------|--------|----------|
| dt_001 | s3_met | Water temperature systematically 3-5 C too warm | Cloud cover as fraction (0-1) instead of tenths (0-10); model sees clear sky | Multiply cloud cover by 10 | **silent** |
| dt_002 | s3_met | Dewpoint temperature unreasonable (e.g., always -40 C) | Vapor pressure units wrong or conversion formula error (kPa vs Pa vs hPa) | Use correct VP-to-TDEW: `TDEW = (237.3 * ln(VP/0.6108)) / (17.27 - ln(VP/0.6108))` with VP in kPa | **silent** |
| dt_003 | s4_inflow | Inflow discharge 1000x too large or small | CaMa-Flood mm/day grid-cell runoff not converted to m^3/s point discharge | Multiply by cell area (m^2) and divide by 86400 | **silent** |
| dt_004 | s3_met | Wind direction causes wrong circulation pattern | Wind direction in degrees but model expects radians (or vice versa, version-dependent) | Check w2_con.npt WDIC card; v4.x typically uses degrees | **silent** |
| dt_005 | s3_met | Julian day offset — forcing misaligned by hours or days | JDAY computed as integer day instead of decimal day (1.0 vs 1.5 for noon) | Use `JDAY = DOY + hour/24.0 + minute/1440.0` | **silent** |

#### Fixed-Width Format / Column Alignment (Fortran-Specific)

| ID | Stage | Symptom | Root Cause | Remedy | Severity |
|----|-------|---------|------------|--------|----------|
| dt_006 | s9_control | Model reads wrong parameter values, bizarre behavior | Column misalignment in w2_con.npt (8-char fields shifted by 1+ characters) | Verify every field is right-justified in exactly 8 characters; use formatted string output | **silent** |
| dt_007 | s1_bathy | Bathymetry file rejected or widths read incorrectly | bth_wb*.npt column widths not matching Fortran FORMAT statement | Match exact column widths from source code FORMAT; typically 8 chars per segment | fatal |
| dt_008 | s9_control | "File not found" for input files | File path exceeds Fortran CHARACTER*72 limit | Use relative paths or symlinks to shorten paths below 72 chars | fatal |
| dt_009 | s9_control | Model reads past end of met/inflow file | Met/inflow file has fewer timesteps than simulation period | Ensure all input time series cover TMSTRT to TMEND Julian days | fatal |

#### Grid/Geometry Errors

| ID | Stage | Symptom | Root Cause | Remedy | Severity |
|----|-------|---------|------------|--------|----------|
| dt_010 | s1_bathy | Model crashes with "layer error" at startup | Segment has zero width at all layers (no water column) | Remove empty segments or ensure at least one non-zero width per active segment | fatal |
| dt_011 | s1_bathy | Unrealistic velocities, numerical instability | Segment length too short relative to layer thickness (CFL violation) | Increase segment length or decrease layer thickness; check Courant number < 1 | fatal |
| dt_012 | s2_branch | Model crashes at branch junction | Branch downstream segment does not exist or points to wrong segment | Validate DHS references: DHS > 0 must point to a valid segment in receiving branch | fatal |
| dt_013 | s1_bathy | Bottom elevation inconsistency between segments | Bottom elevation jumps up in downstream direction (water cannot flow uphill) | Ensure bottom elevations are monotonically non-increasing in downstream direction | **silent** |
| dt_014 | s6_init | Initial water surface below bottom elevation at some segments | ELWS < ELBOT for upstream segments (reservoir not full) | Set ELWS >= max(ELBOT) or handle dry segments with initial zero-width layers | fatal |

#### Water Quality Configuration

| ID | Stage | Symptom | Root Cause | Remedy | Severity |
|----|-------|---------|------------|--------|----------|
| dt_015 | s8_wq | Constituent concentration always zero despite non-zero inflow | Constituent flag OFF in w2_con.npt but ON in inflow file (or vice versa) | Ensure CONSTITU card flags match cin_br*.npt column count exactly | **silent** |
| dt_016 | s8_wq | DO drops to zero immediately (anoxic everywhere) | SOD (sediment oxygen demand) set too high for reservoir | Start with SOD = 0.5 g/m^2/day; calibrate against observed DO profiles | **silent** |
| dt_017 | s8_wq | Algae bloom unrealistically (chlorophyll > 1000 ug/L) | Algal growth rate set too high, or nutrient loading unconstrained | Cap algal growth rate at 2.0/day; verify nutrient inflow concentrations | **silent** |

#### Selective Withdrawal / Outflow

| ID | Stage | Symptom | Root Cause | Remedy | Severity |
|----|-------|---------|------------|--------|----------|
| dt_018 | s5_outflow | Dam release temperature wrong (too warm or too cold) | Outlet elevation in wrong units or reference frame (depth from surface vs elevation ASL) | Outlet elevation must be in m ASL, matching bathymetry elevation datum | **silent** |
| dt_019 | s5_outflow | Outflow exceeds inflow, reservoir drains unrealistically | Outflow file units wrong (L/s instead of m^3/s) or negative flow values | Validate outflow units and ensure non-negative | **silent** |

#### Coupling / Dependency

| ID | Stage | Symptom | Root Cause | Remedy | Severity |
|----|-------|---------|------------|--------|----------|
| dt_020 | s13_coupling | CaMa-Flood inflow arrives at wrong segment | Spatial mismatch between CaMa grid cell and W2 inflow segment | Map CaMa outlet cell to nearest W2 branch inflow point; verify with coordinates | **silent** |
| dt_021 | s13_coupling | Double-counting runoff: VIC local + CaMa routed | VIC distributed tributary inflow overlaps with CaMa-routed main channel inflow | Subtract contributing area of CaMa-routed inflow from distributed tributary calculation | **silent** |

#### Runtime / Numerical

| ID | Stage | Symptom | Root Cause | Remedy | Severity |
|----|-------|---------|------------|--------|----------|
| dt_022 | s10_exec | Model runs extremely slowly (hours for small reservoir) | Timestep drops to < 1 second due to CFL violation in narrow segments | Increase minimum segment width or merge narrow segments; check for zero-width cells | degraded |
| dt_023 | s10_exec | NaN in output, model crashes mid-simulation | Numerical instability from sharp bathymetry gradients | Smooth bathymetry transitions; ensure segment lengths are >= 2x layer thickness | fatal |
| dt_024 | s10_exec | Model stops with "NEGATIVE THICKNESS" error | Water surface drops below a layer boundary during drawdown | Increase minimum layer thickness; add wetting/drying capability if available | fatal |
| dt_025 | s10_exec | Zero output files despite model "completing" | Output card group missing or output interval set to 0 | Verify OUT FILE cards in w2_con.npt have non-zero intervals | **silent** |

**Total**: 25 anticipated diagnostic triplets across 6 failure domains.
- Silent errors: 14/25 (56%) — consistent with the high silent error rate observed in lake models (GLM: 56%)

---

## 10. Coupling Points with HydroCraft

### Coupling Matrix

| # | Coupling ID | Source Model | Target Model | Variable | Direction | Priority |
|---|------------|-------------|-------------|----------|-----------|----------|
| 1 | c_w2_01 | CaMa-Flood | CE-QUAL-W2 | Discharge at reservoir inlet(s) | CaMa -> W2 | Phase 1 |
| 2 | c_w2_02 | VIC | CE-QUAL-W2 | Meteorological forcing | VIC -> W2 | Phase 1 |
| 3 | c_w2_03 | VIC | CE-QUAL-W2 | Distributed tributary runoff | VIC -> W2 | Phase 1 |
| 4 | c_w2_04 | CE-QUAL-W2 | CaMa-Flood | Dam release discharge | W2 -> CaMa | Phase 1 |
| 5 | c_w2_05 | CE-QUAL-W2 | CaMa-Flood | Dam release temperature | W2 -> CaMa | Phase 2 |
| 6 | c_w2_06 | SWAT+ | CE-QUAL-W2 | Upstream nutrient loading (N, P, sediment) | SWAT+ -> W2 | Phase 2 |
| 7 | c_w2_07 | CE-QUAL-W2 | SWAT+ | Downstream WQ concentrations | W2 -> SWAT+ | Phase 2 |
| 8 | c_w2_08 | GLM | CE-QUAL-W2 | 1D vs 2D comparison/validation | GLM <-> W2 | Phase 2 |
| 9 | c_w2_09 | DLBreach | CE-QUAL-W2 | Dam breach scenario (outflow boundary) | DLBreach -> W2 | Phase 3 |
| 10 | c_w2_10 | CMIP6 | CE-QUAL-W2 | Future climate forcing (delta-change) | CMIP6 -> W2 | Phase 3 |
| 11 | c_w2_11 | Pywr | CE-QUAL-W2 | Optimized reservoir release schedule | Pywr -> W2 | Phase 3 |
| 12 | c_w2_12 | CE-QUAL-W2 | Pywr | Current storage/temperature state | W2 -> Pywr | Phase 3 |

### CE-QUAL-W2 vs GLM Auto-Selection Logic

When the user requests a reservoir simulation, the agent should recommend:

```python
if reservoir_length_km / reservoir_width_km > 5:
    recommend = "CE-QUAL-W2"
    reason = "Elongated reservoir — longitudinal gradients are significant"
elif reservoir has multiple inflow tributaries at different locations:
    recommend = "CE-QUAL-W2"
    reason = "Multiple spatially distributed inflows require 2D routing"
elif selective_withdrawal_required and num_outlets > 1:
    recommend = "CE-QUAL-W2"
    reason = "Multi-level selective withdrawal needs 2D approach"
elif quick_assessment or reservoir_area_km2 < 1:
    recommend = "GLM"
    reason = "Compact lake or rapid assessment — 1D is sufficient"
else:
    recommend = "GLM"
    reason = "Default to faster 1D model; upgrade to CE-QUAL-W2 if needed"
```

---

## 11. Validation Plan

### Tier 1: Developer Example Data (Day 1)

**Dataset**: DeGray Lake, Arkansas (included in USACE CE-QUAL-W2 examples)
- Classic USACE test case, well-documented in the user manual
- Purpose: Verify compiled binary works, output matches reference
- Test: Compare temperature profiles at dam location to published results

**Alternative**: Any example included in the PSU v4.5 GitHub repository.

### Tier 2: Progressive Data Replacement (Week 1)

Following VALIDATION_PROTOCOL.md, replace inputs one-at-a-time:
1. **Forcing replacement**: Keep example bathymetry, replace met data with CMFD/MSWX
2. **Inflow replacement**: Keep example met, replace inflow with CaMa-Flood output
3. **Grid replacement**: Keep other inputs, replace bathymetry with DEM-derived grid
4. After each replacement, verify results remain physically reasonable

### Tier 3: Chinese Reservoir Validation (Week 2-3)

**Primary candidate**: Danjiangkou Reservoir (丹江口水库)

| Attribute | Value |
|-----------|-------|
| Location | 32.54N, 111.51E |
| Max depth | ~80 m |
| Surface area | ~745 km^2 |
| Length | ~80 km (main stem) |
| Branches | 2 (Han River + Dan River) |
| Significance | South-to-North Water Transfer source |
| Data availability | Published temperature profiles, water quality monitoring data (Ministry of Ecology) |
| Forcing | CMFD (China, 0.1 deg) |

**Why Danjiangkou**:
- Strategically important (water quality for South-to-North Transfer)
- Two branches (tests multi-branch capability)
- Moderate size (feasible grid: ~80 segments x ~80 layers)
- Published temperature and WQ data available in Chinese literature
- Can be compared with GLM 1D simulation to demonstrate 2D advantages

**Alternative candidates**:

| Reservoir | Pros | Cons |
|-----------|------|------|
| **Three Gorges** (三峡) | Most important Chinese reservoir, extensive data | Very large (660 km), expensive computation, complex cascade |
| **Miyun** (密云) | Already validated with GLM, good for comparison | Small enough that GLM may be adequate |
| **Ertan** (二滩) | Deep, well-studied, thermal pollution concern | Less accessible data |
| **Xinanjiang** (新安江) | Source of Qiandao Lake, WQ focus | Complex geometry (1000+ islands) |

### Tier 4: Global Validation (If time allows)

**Lake Powell, USA** — One of the most heavily modeled reservoirs with CE-QUAL-W2:
- US Bureau of Reclamation has published CE-QUAL-W2 models
- 300 km long, very elongated (L:W > 100:1)
- Extensive USGS monitoring data
- Published CE-QUAL-W2 calibration parameters available as reference

### Validation Protocol

For each validation reservoir:
1. Build grid from DEM (or idealized from HydroLAKES)
2. Run with default parameters (temperature only)
3. Compare simulated vs observed: surface temperature, dam release temperature, thermocline depth
4. Calibrate (WSC, EXH2O, AX, CBHE, TSED) using GLUE
5. Report calibrated RMSE, bias, NSE for temperature
6. If WQ enabled: validate DO, nutrients against monitoring data
7. Generate curtain plots at key time steps
8. Compare with GLM 1D results for the same reservoir
9. Write findings to basin_context.yaml

---

## 12. Estimated Effort

### Phase 1: Installation & Binary Verification (1 day)

| Task | Time |
|------|------|
| Clone PSU v4.5 from GitHub | 15 min |
| Install Fortran compiler + NetCDF if needed | 30 min |
| Compile CE-QUAL-W2 from source | 1-3 hours (Fortran compilation troubleshooting) |
| Run reference example (DeGray Lake or equivalent) | 1 hour |
| Verify output matches reference | 1 hour |
| **Subtotal** | **~4-6 hours** |

### Phase 2: Core Pipeline Tools (4-5 days)

| Task | Time |
|------|------|
| Tool #1: build_reservoir_grid (DEM-based) | 8 hours (most complex tool) |
| Tool #2: generate_bathymetry | 4 hours |
| Tool #3: idealized_bathymetry | 3 hours |
| Tool #4: build_branch_topology | 5 hours |
| Tool #5: convert_met_to_w2 | 4 hours |
| Tool #6: convert_inflow_to_w2 | 4 hours |
| Tool #7: generate_distributed_inflow | 3 hours |
| Tool #8: configure_w2_outflow | 3 hours |
| Tool #9: build_init_conditions | 2 hours |
| Tool #10: set_hydraulic_params | 2 hours |
| Tool #12: generate_w2_control (critical!) | 8 hours (many card groups, format validation) |
| Tool #13: run_w2 | 2 hours |
| **Subtotal** | **~48 hours** |

### Phase 3: Validation & Calibration (3-4 days)

| Task | Time |
|------|------|
| Developer example end-to-end test | 4 hours |
| Progressive data replacement (3 steps) | 8 hours |
| Danjiangkou Reservoir full setup | 8 hours |
| Danjiangkou validation + calibration | 8 hours |
| Fix bugs discovered during validation | 8 hours |
| **Subtotal** | **~36 hours** |

### Phase 4: Output Analysis & WQ (2-3 days)

| Task | Time |
|------|------|
| Tool #11: configure_wq | 4 hours |
| Tool #14: parse_w2_output | 6 hours (complex fixed-width parsing) |
| Tool #15: plot_w2_curtain | 5 hours (signature 2D visualization) |
| Tool #16: plot_w2_timeseries | 3 hours |
| Tool #17: calibrate_w2 | 5 hours |
| Tool #18: w2_to_cama_coupling | 3 hours |
| **Subtotal** | **~26 hours** |

### Phase 5: Documentation & Diagnostics (2 days)

| Task | Time |
|------|------|
| 14 skill documents | 8 hours |
| 25 diagnostic triplets (detailed) | 4 hours |
| SKILL.md + knowledge_infrastructure.yaml | 3 hours |
| Workflow diagram (pipeline.drawio) | 1 hour |
| **Subtotal** | **~16 hours** |

### Total: 12-16 working days

This is approximately 2-3x the GLM effort, which reflects:
- More complex grid generation (2D bathymetry vs 1D depth-area curve)
- More input files (10+ vs 3-4 for GLM)
- Fixed-width format handling (more error-prone than CSV/namelist)
- Multi-branch topology (not present in GLM)
- More WQ constituents (21+ vs AED2's modular approach)
- More complex output parsing (2D fields vs 1D profiles)

---

## 13. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Fortran compilation fails on server | Medium | High | Try PSU v4.5 (newer Fortran standard); fall back to USACE v3.72 pre-built if available; inspect compiler flags |
| DEM lacks underwater bathymetry | High | High | Use idealized shapes from HydroLAKES for quick start; require published bathymetry for detailed studies; interpolate from dam max depth + thalweg |
| Fixed-width format alignment errors | High | High | Build comprehensive formatter with exact column-width enforcement; unit tests for every card group; byte-by-byte comparison with reference files |
| Large reservoir (Three Gorges) exceeds runtime budget | Medium | Medium | Start with smaller reservoirs (Danjiangkou, Miyun); optimize grid resolution; consider segment merging for very long reservoirs |
| Observed validation data scarce for Chinese reservoirs | Medium | Medium | Use remote sensing surface temperature (Landsat/MODIS) as proxy; published literature values; Ministry of Ecology monitoring reports |
| Version incompatibility between v3.x and v4.x input files | Low | Medium | Target PSU v4.5 only; document version-specific format differences |
| Adaptive timestep makes runtime unpredictable | Medium | Low | Set minimum timestep floor; monitor w2l.opt for timestep warnings; smooth bathymetry to avoid sharp gradients |
| Multi-branch setup too complex for automation | Medium | Medium | Start with single-branch reservoirs; add multi-branch gradually; provide manual override for branch connectivity |

---

## 14. File Structure (Target)

```
models/CE_QUAL_W2/
  knowledge_infrastructure/
    DISSECTION_PLAN.md              # This file
    SKILL.md                        # Agent entry point (after dissection)
    knowledge_infrastructure.yaml   # Schema-compliant package definition
    workflow/
      pipeline.drawio              # Visual pipeline diagram
      workflow.md                  # Agent-readable workflow
    tools/
      s1_bathymetry/
        build_reservoir_grid.py     # DEM-based segment-layer grid
        generate_bathymetry.py      # Write bth_wb*.npt files
        idealized_bathymetry.py     # Quick-start from HydroLAKES
      s2_branch_topology/
        build_branch_topology.py    # Branch connectivity
      s3_met_forcing/
        convert_met_to_w2.py        # CMFD/MSWX to W2 met format
      s4_inflow/
        convert_inflow_to_w2.py     # CaMa/VIC to W2 inflow
        generate_distributed_inflow.py  # Distributed tributary flow
      s5_outflow/
        configure_w2_outflow.py     # Selective withdrawal config
      s6_init_conditions/
        build_init_conditions.py    # 2D initial T/WQ fields
      s7_hydraulic_params/
        set_hydraulic_params.py     # AX, DX, WSC, CBHE
      s8_wq_config/
        configure_wq.py             # Constituent activation + rates
      s9_control_file/
        generate_w2_control.py      # Assemble w2_con.npt
      s10_execution/
        run_w2.py                   # Execute CE-QUAL-W2
      s11_output_analysis/
        parse_w2_output.py          # Parse fixed-width output
        plot_w2_curtain.py          # 2D curtain plots
        plot_w2_timeseries.py       # Time series at locations
      s12_calibration/
        calibrate_w2.py             # GLUE-style calibration
      s13_coupling/
        w2_to_cama_coupling.py      # W2 outflow to CaMa-Flood
    docs/
      s0_configuration_skill.md
      s1_bathymetry_skill.md
      s2_branch_topology_skill.md
      s3_met_forcing_skill.md
      s4_inflow_skill.md
      s5_outflow_skill.md
      s6_init_conditions_skill.md
      s7_hydraulic_params_skill.md
      s8_wq_config_skill.md
      s9_control_file_skill.md
      s10_execution_skill.md
      s11_output_analysis_skill.md
      s12_calibration_skill.md
      s13_coupling_skill.md
    diagnostics/
      triplets.yaml                # 25+ diagnostic triplets
      error_log.yaml               # Errors from real runs
      episodes.yaml                # Debugging stories

model/ce_qual_w2/
  bin/w2.exe                       # CE-QUAL-W2 executable
  src/                             # Fortran source code
  examples/                        # Reference examples
  docs/                            # User manual PDF
```

---

## 15. Integration with HydroCraft Platform

### CLAUDE.md Updates Required

After CE-QUAL-W2 is validated, add to the Supported Models table:

```markdown
| **Reservoir WQ (2D)** | CE-QUAL-W2 v4.5 | 2D laterally-averaged hydrodynamics + 21 WQ constituents |
```

### Platform Numbers Update

```
Model packages: 18 (16 validated + 2 testing)
Autonomous tools: ~260 (+18 from CE-QUAL-W2)
Diagnostic triplets: ~318 (+25 from CE-QUAL-W2)
```

### New Skill Entry

```markdown
| cequalw2-reservoir-run | CE-QUAL-W2 2D reservoir simulation (hydrodynamics + WQ) |
```

### New Coupling Entries

```markdown
| c_w2_01 | CaMa-Flood discharge -> CE-QUAL-W2 reservoir inflow |
| c_w2_04 | CE-QUAL-W2 dam release -> CaMa-Flood downstream routing |
| c_w2_06 | SWAT+ nutrient loading -> CE-QUAL-W2 inflow WQ |
```

### Web UI Integration

When the user selects a basin containing a major elongated reservoir:
1. Check if reservoir L:W ratio > 5 (from HydroLAKES geometry)
2. Offer: "This basin contains [Reservoir Name] (length: X km, max depth: Y m). This reservoir is elongated — I recommend CE-QUAL-W2 for 2D simulation. Alternatively, GLM can provide a faster 1D assessment. Which would you prefer?"
3. If CE-QUAL-W2 selected, warn about longer setup time (~1-2 hours for bathymetry) and runtime (~30-120 min)

---

## 16. Key Publications and Resources

### Primary References

1. **Cole, T.M. and Wells, S.A.** (2006). CE-QUAL-W2: A Two-Dimensional, Laterally Averaged, Hydrodynamic and Water Quality Model, Version 3.5. US Army Corps of Engineers. (The authoritative user manual, ~700 pages)

2. **Wells, S.A.** (2019). CE-QUAL-W2: A Two-Dimensional, Laterally Averaged, Hydrodynamic and Water Quality Model, Version 4.1. Portland State University. (Updated for v4.x)

3. **Wells, S.A.** (2021). CE-QUAL-W2: A Two-Dimensional, Laterally Averaged, Hydrodynamic and Water Quality Model, Version 4.5. Portland State University.

### Key Application Papers (Chinese Reservoirs)

4. **Ma, S., Kassinos, S.C., Kassinos, D.F., Akylas, E.** (2008). "Modeling the impact of water withdrawal schemes on the thermal stratification in a reservoir." Journal of Hydraulic Engineering.

5. **Yang, Z., Cheng, B., Xu, Y., et al.** (2018). "Application of CE-QUAL-W2 model for Three Gorges Reservoir water temperature simulation." (Multiple Chinese-language papers on this topic)

6. **Long, L., Ji, D., Liu, D., et al.** (2019). "Thermal stratification and its effect on algal blooms in Three Gorges Reservoir." Environmental Science and Pollution Research.

7. **Zhang, Y., Wu, Z., Liu, M., et al.** (2015). "Thermal structure and response to long-term climatic changes in Lake Qiandaohu." Environmental Science & Technology.

### Source Code and Downloads

8. **GitHub (PSU v4.5)**: https://github.com/EnvironmentalSystems/CE-QUAL-W2
9. **USACE ERDC**: https://www.erdc.usace.army.mil/Software/ (registration required)
10. **PSU CE-QUAL-W2 website**: https://www.ce.pdx.edu/w2/ (documentation, workshops, examples)

### Comparison with GLM

11. **Hipsey, M.R., Bruce, L.C., Boon, C., et al.** (2019). "A General Lake Model (GLM 3.0) for linking with high-frequency sensor data from the Global Lake Ecological Observatory Network (GLEON)." Geoscientific Model Development.

12. **Weber, M., Rinke, K., Hipsey, M.R., Boehrer, B.** (2017). "Optimizing withdrawal from drinking water reservoirs to reduce manganese enrichment of drinking water — A set of tools developed for the Rappbode Reservoir." (Compares 1D and 2D approaches)

---

## Appendix A: CE-QUAL-W2 w2_con.npt Card Group Reference

The control file has approximately 50 card groups. The most critical ones:

```
TITLE     (3 lines of title text)
GRID      (NWB, NBR, IMX, KMX — overall grid dimensions)
TIME      (TMSTRT, TMEND, YEAR — simulation period)
CALCU     (VEL, TEMP, CONSTITUENTS — what to compute)
DLT CON   (DLTMIN — minimum timestep)
DLT DATE  (date-specific timestep limits)
DLT MAX   (max timestep by water body)
BRANCH    (US, DS, UHS, DHS, slope per branch)
INIT CND  (T2I, ICE — initial conditions)
MET DATA  (METFN — met file path per water body)
WIND SHE  (WSC — wind sheltering per water body)
EX COEF   (EXH2O, EXSS, EXOM, BETA — light extinction)
HYD COEF  (AX, DX, CBHE, TSED, FI, TSEDF — hydraulic/thermal coefficients)
INFLOW    (NSTR, KTSTR, KBSTR — inflow configuration)
IN FILE   (QINFN, TINFN, CINFN — inflow file paths per branch)
OUTFLOW   (NSTR — number of outlet structures)
OUT FILE  (output file paths and controls)
CONSTITU  (CCC — constituent on/off flags)
... (many more)
```

Each card uses 8-character fixed-width fields. The exact format is defined in the Fortran source code READ statements.

---

## Appendix B: Comparison of CE-QUAL-W2 Versions

| Feature | USACE v3.72 | PSU v4.1 | PSU v4.5 |
|---------|-------------|----------|----------|
| Open source | No (registration) | Yes (GitHub) | Yes (GitHub) |
| Fortran standard | F77/F90 | F90 | F90/F95 |
| NetCDF output | No | Optional | Yes |
| Max branches | 100 | 200+ | 200+ |
| Zooplankton | No | Yes | Yes |
| Macrophytes | Basic | Improved | Full |
| Ice model | Basic | Improved | Full |
| Sediment diagenesis | SOD only | Full | Full |
| Parallel processing | No | No | Experimental (OpenMP) |
| Input file format | Fixed-width | Fixed-width | Fixed-width + optional NetCDF |
| User manual | 700 pages | Updated | Updated |
| Active maintenance | Slow | Active | Active |

**Recommendation**: PSU v4.5 for HydroCraft (open source, modern features, active maintenance).

---

## Appendix C: Pre-Flight Checklist for CE-QUAL-W2

Based on `PREFLIGHT.md`, the applicable trap categories for CE-QUAL-W2:

- [x] **Has Fortran code** — Fortran traps apply (path truncation, fixed-form, STOP exits)
- [x] **Reads fixed-width text files** — Column alignment traps apply (8-char fields)
- [x] **Will be coupled with other models** — Coupling traps apply (CaMa-Flood, GLM, SWAT+)
- [x] **Has physical units** — Unit traps apply (cloud cover 0-10, dewpoint vs RH, Julian day)
- [x] **Uses spatial data** — Spatial traps apply (segment coordinates, branch connectivity)
- [ ] **Is a crop/ecosystem model** — Not applicable
- [x] **Runs on Linux but may have Windows assumptions** — Platform traps may apply
- [x] **Is a lake/reservoir model** — Lake model traps apply (inflow units, bathymetry direction)
- [ ] **Is a 2D flood/inundation model** — Partially applicable (2D but laterally averaged, not floodplain)
- [x] **Has config file separate from model input** — Config file traps apply (w2_con.npt is massive)
- [ ] **Can emulate multiple model structures** — Not applicable

**Top 3 anticipated failure modes**:
1. Fixed-width column misalignment in w2_con.npt (8-char fields) — **silent**
2. Cloud cover units (tenths 0-10 vs fraction 0-1 vs percent 0-100) — **silent**
3. Bathymetry width matrix dimensions not matching grid declaration — **fatal**
