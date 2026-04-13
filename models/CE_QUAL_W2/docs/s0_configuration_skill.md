# s0: Configuration — Skill Document

## Purpose

Collect user inputs and make key decisions about the CE-QUAL-W2 simulation setup. This includes reservoir selection, simulation period, forcing source, grid resolution, and whether to enable water quality constituents.

## Prerequisites

- [ ] User has identified the target reservoir (name or coordinates)
- [ ] Simulation time period defined

## Inputs

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| Reservoir name or dam coordinates | String/Float | Yes | Location of the dam |
| Start year | Integer | Yes | First year of simulation |
| End year | Integer | Yes | Last year of simulation |
| Forcing dataset | Choice | Yes | CMFD (China), MSWX (global), NASA POWER (online) |
| Enable WQ | Boolean | No | Temperature only (default) vs full water quality |
| Segment length | Float | No | Target segment length in meters (default: 1000) |
| Layer thickness | Float | No | Layer thickness in meters (default: 1.0) |

## Procedure

### Step 1: Determine CE-QUAL-W2 vs GLM

Ask: Is the reservoir elongated (length/width > 5)?
- YES: Use CE-QUAL-W2 (this workflow)
- NO: Consider GLM (1D) instead — faster setup, adequate for compact lakes

### Step 2: Collect reservoir parameters

Minimum required:
- Dam location (lat/lon)
- Approximate reservoir length (km), max depth (m), surface area (km^2)
- Dam crest elevation (m ASL)

If user has a bathymetry shapefile or cross-section data, note the path.
If not, idealized geometry will be used (requires length, depth, area only).

### Step 3: Select grid resolution

| Reservoir Length | Recommended Segment Length | Typical IMX |
|-----------------|---------------------------|-------------|
| < 10 km | 250-500 m | 20-40 |
| 10-50 km | 500-1000 m | 20-100 |
| 50-200 km | 1000-2000 m | 50-200 |
| > 200 km | 1000-2000 m | 200-660 |

| Max Depth | Recommended Layer Thickness | Typical KMX |
|-----------|---------------------------|-------------|
| < 20 m | 0.5-1.0 m | 20-40 |
| 20-100 m | 1.0-2.0 m | 20-100 |
| > 100 m | 1.0-2.0 m | 50-200 |

### Step 4: Select WQ configuration

- **Temperature only**: Fastest setup, recommended for initial hydrodynamic validation
- **T + DO + nutrients**: Standard water quality study
- **Full suite**: Research/regulatory applications (longest setup)

### Step 5: Identify available data

- Observed temperature profiles (for calibration)
- Observed discharge at dam outlet
- Inflow discharge (from CaMa-Flood or gauging stations)
- Water quality monitoring data (for WQ validation)

## Expected Outputs

Configuration parameters confirmed by user, ready for s1-s8 execution.

## Validation Checks

1. Simulation period within forcing data coverage (CMFD: 1979-2018, MSWX: 1979-2026)
2. Reservoir is within China if using CMFD
3. Grid resolution is appropriate for reservoir size

## Common Pitfalls

- Using CMFD outside China: produces completely wrong forcing (silent error)
- Grid too fine for large reservoir: very long runtime with no accuracy benefit
- Enabling full WQ without constituent inflow data: all concentrations will be default/zero
