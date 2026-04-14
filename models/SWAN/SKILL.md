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

# PySWaN (SWAN I/O Toolbox) — Knowledge Infrastructure

**Package**: `pyswan-ocean` v1.0.0
**Model**: PySWaN — Python I/O and spectral analysis toolbox for SWAN (Simulating WAves Nearshore)
**Source**: [github.com/openearth/swan](https://github.com/openearth/swan)
**Author**: Gerben de Boer (TU Delft / Van Oord)
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 20 diagnostic triplets | ~1,200 lines of validated Python
**Validation status**: `tested` (round-trip JONSWAP spectrum generation, write, read, Hm0 verification)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/NOAA_Tides/SKILL.md` for tidal observation data.
See `data_ki/NDBC/SKILL.md` for wave buoy observations.


## Overview

This knowledge infrastructure enables autonomous generation, I/O, and analysis of spectral ocean wave data for SWAN (Simulating WAves Nearshore) using the PySWaN Python package. The toolbox provides Python classes for three spectral representations (0D parametric, 1D frequency, 2D frequency-direction) and read/write functions for all major SWAN spectral file formats.

**What SWAN does**: SWAN is a third-generation numerical wave model for computing wave propagation in coastal regions. It solves the spectral action balance equation for wind-generated surface gravity waves in nearshore waters, accounting for:
- Wave generation by wind (GEN3 formulation)
- Wave propagation (refraction, shoaling, diffraction)
- Nonlinear wave-wave interactions (triads, quadruplets)
- Dissipation (whitecapping, bottom friction, depth-induced breaking)
- Bottom-induced effects (shoaling, refraction over variable bathymetry)

**What PySWaN does**: Python I/O toolbox that wraps SWAN spectral file formats:
- Generate JONSWAP spectra (1D, 2D) from parametric wave parameters
- Read/write SWAN spectral files (.spc, .s1d, .s2d)
- Read/write SWAN parametric files (.tpar)
- Compute spectral parameters (Hm0, Tp, Tm01, Tm02, peak direction)
- Directional spreading functions (cos^ms power law)
- Plot spectra (1D line plots, 2D polar plots)

**Key difference from hydrological models**: SWAN operates on spectral wave energy density in the frequency-direction domain, not on water balance or hydrograph routing. Units are m²/Hz (1D) or m²/Hz/deg (2D), not m³/s or mm/day.

---

## Installation

### Source

```
PySWaN v0.0 (WIP)
Source:   github.com/openearth/swan
License:  GPL v3
Platform: Cross-platform (pure Python)
```

### Python Dependencies

```
numpy        — array operations, spectral math
scipy        — integration (cumtrapz for spectral moments)
matplotlib   — plotting (optional, for visualization)
```

### Installation Steps

```bash
# Create virtual environment
python3 -m venv /path/to/venv
source /path/to/venv/bin/activate

# Install from source
cd /path/to/swan/source/repo
pip install -e .

# Verify
python -c "import pyswan; import pyswan.swan as swan; import pyswan.oceanwaves as ow; print('OK')"
```

### Test Data

```
data/
  1D_lltime.spc       # 1D spectrum, lon/lat coords, time-varying
  1D_llstat.spc       # 1D spectrum, lon/lat coords, stationary
  1D_xytime.spc       # 1D spectrum, x/y coords, time-varying
  1D_xystat.spc       # 1D spectrum, x/y coords, stationary
  2D_lltime.spc       # 2D spectrum, lon/lat coords, time-varying
  2D_llstat.spc       # 2D spectrum, lon/lat coords, stationary
  2D_xytime.spc       # 2D spectrum, x/y coords, time-varying
  2D_xystat.spc       # 2D spectrum, x/y coords, stationary
  *.swn               # SWAN input command files
  *.crv               # SWAN curve output files (TABLE output)
  *.bot               # Bathymetry files
  Spec0D_scalar.tpar  # Parametric (0D) TPAR file
  Spec0_series.tpar   # Parametric time series TPAR file
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Define domain, grid, physics, boundary conditions |
| 1 | Bathymetry prep | `convert_bathymetry` | Prepare bottom grid from GEBCO/survey data |
| 2 | Boundary spectra | `convert_boundary_spectra` | Generate/convert boundary wave spectra (TPAR, 1D, 2D) |
| 3 | Wind forcing | `convert_wind_forcing` | Prepare wind fields (ERA5/CFSR to SWAN format) |
| 4 | SWN command file | (manual/template) | Assemble SWAN input file (.swn) |
| 5 | Execution | `run_swan` | Execute SWAN binary with preflight checks |
| 6 | Output parsing | `parse_swan_output` | Read TABLE/SPEC output to CSV/arrays |

---

## Spectral Data Classes

### Spec0 — Parametric (0D)

Scalar wave parameters without spectral resolution.

| Attribute | Type | Units | Description |
|-----------|------|-------|-------------|
| `t` | datetime array | UTC | Time stamps |
| `Hs` | float/array | m | Significant wave height |
| `Tp` | float/array | s | Peak period |
| `pdir` | float/array | degrees | Peak wave direction (nautical) |
| `ms` | float/array | - | Directional spreading power |
| `lon` | float array | degrees E | Longitude |
| `lat` | float array | degrees N | Latitude |

### Spec1 — 1D Frequency Spectrum

Energy density as function of frequency only. Dimensions: `[time, location, frequency]`.

| Attribute | Type | Units | Description |
|-----------|------|-------|-------------|
| `f` | float array | Hz | Frequency bins |
| `energy` | masked array | m²/Hz | Variance density spectrum |
| `direction` | masked array | degrees | Mean wave direction per frequency |
| `spreading` | masked array | degrees or power | Directional spread per frequency |
| `t` | datetime array | UTC | Time stamps |
| `x`, `y` | float arrays | m | Cartesian coordinates |
| `lon`, `lat` | float arrays | degrees | Geographic coordinates |

### Spec2 — 2D Frequency-Direction Spectrum

Energy density as function of frequency and direction. Dimensions: `[time, location, frequency, direction]`.

| Attribute | Type | Units | Description |
|-----------|------|-------|-------------|
| `f` | float array | Hz | Frequency bins |
| `direction` | float array | degrees | Direction bins |
| `energy` | masked array | m²/Hz/deg | Variance density spectrum |
| `direction_units` | string | - | 'degrees_north' (nautical) or 'degrees_true' (Cartesian) |
| `energy_units` | string | - | 'm2/Hz/deg' |
| `t` | datetime array | UTC | Time stamps |

---

## SWAN File Formats

### Spectral Files (.spc, .s1d, .s2d)

Header structure (common to 1D and 2D):
```
SWAN 1                           ← version
$ comment line                    ← $ prefix comments
TIME                             ← optional: time-varying file
1                                ← timecoding (1 = YYYYMMDD.HHMMSS)
LONLAT                           ← or LOCATIONS for x/y
2                                ← number of points
0.000000 0.000000                ← coordinates
100.000000 0.000000
AFREQ                            ← AFREQ (absolute) or RFREQ (relative)
40                               ← number of frequencies
0.025                            ← frequency values (Hz)
...
```

2D spectra add direction block after frequencies:
```
NDIR                             ← NDIR (nautical) or CDIR (Cartesian)
25                               ← number of directions
-180                             ← direction values (degrees)
...
```

Data block per timestep per location:
```
20160101.000000                  ← timestamp (if TIME)
FACTOR                           ← FACTOR, ZERO, or NODATA
1.0                              ← scale factor
<energy matrix>                  ← [nfreq x ndir] for 2D, [nfreq x 3] for 1D
```

### TPAR Files (.tpar)

Parametric boundary condition time series:
```
TPAR $yyyymmdd.HHMMSS Hs Tp pdir ms
19920516.130000 1.0 5 -90 10
```

Columns: time (YYYYMMDD.HHMMSS), Hs (m), Tp (s), pdir (degrees, nautical), ms (spreading power)

### TABLE Output Files (.crv)

SWAN output along curves (CURVE command):
```
%
% Run:000   Table:GAUGE   SWAN version:41.01AB
%
%   Xp    Yp    PkDir    Hsig    RTpeak    Tm01    Tm02    Depth
%   [m]   [m]   [degr]   [m]     [sec]     [sec]   [sec]   [m]
    0.    0.    273.91   1.001    4.993    4.168    3.810   2.000
```

### SWN Command Files (.swn)

SWAN input commands (Fortran-style):
```
PROJ 'name' 'run_id'
SET NAUTICAL
MODE NONSTat ONED
CGRID 0. 0. 0. 1000. 0. 100 0 SECTOR -180 180 23 0.025 1 39
INPGRID BOTTOM -1. 0. 0. 1 0 1002. 0.
READINP BOTTOM 1. 'bathymetry.bot' 4 0 FREE
BOUN SHAPE BIN PEAK DSPR POWER
BOUN SIDE W CCW VAR FILE 0 'boundary.spc'
GEN3
COMPUTE NONSTat 20160101.000000 1 MIN 20160101.001000
STOP
```

---

## Unit Trap Table

| Variable | PySWaN Internal | SWAN Binary | Common Source | Trap |
|----------|----------------|-------------|---------------|------|
| Energy density (2D) | m²/Hz/deg | m²/Hz/degr | buoy data | Some buoys report m²/Hz/rad — multiply by π/180 |
| Energy density (1D) | m²/Hz | m²/Hz | - | 1D has no directional dimension — do NOT divide by deg |
| Direction (nautical) | degrees_north | NDIR | met convention | Nautical = direction FROM which waves come |
| Direction (Cartesian) | degrees_true | CDIR | math convention | Cartesian = direction TO which waves propagate |
| Frequency | Hz | Hz | - | Some models use rad/s — divide by 2π |
| Period (peak) | seconds | seconds | - | Tp = 1/fp, NOT 1/fm; confusion with Tm01/Tm02 |
| Wave height Hs | m | m | cm in some datasets | Hm0 = 4√m0, where m0 = ∫E(f)df |
| Spreading power | dimensionless | dimensionless | degrees | ms is cos^ms power, NOT angular spread in degrees |
| Time | datetime | YYYYMMDD.HHMMSS | ISO 8601 | timecoding=1 is fixed format, not unix timestamp |
| Coordinates | degrees or m | LONLAT or LOCATIONS | WGS84 | LONLAT for geographic, LOCATIONS for Cartesian x/y |
| Bathymetry | m (depth positive down) | m positive down | m positive up? | Some sources give elevation (negative = water); SWAN wants positive depth |
| Wind speed | m/s | m/s | knots, km/h | 1 knot = 0.5144 m/s; SWAN needs m/s |
| Wind direction | degrees (met convention) | degrees | various | Met convention = direction FROM which wind blows |

---

## Spectral Moments and Parameters

Key formulas used in the codebase:

```
m0 = ∫ E(f) df                     → Hm0 = 4 * sqrt(m0)
m1 = ∫ f * E(f) df                  → Tm01 = m0 / m1
m2 = ∫ f² * E(f) df                 → Tm02 = sqrt(m0 / m2)
fp = argmax(E(f))                   → Tp = 1 / fp
```

For 2D spectra, first integrate over direction:
```
E_1D(f) = ∫ E(f,θ) dθ              → then apply 1D formulas above
```

JONSWAP spectrum:
```
E(f) = α * Hm0² * Tp⁻⁴ * f⁻⁵ * exp(-1.25 * (Tp*f)⁻⁴) * γ^exp(-0.5 * (Tp*f - 1)² / σ²)

where:
  α = 1 / (0.06533 * γ^0.8015 + 0.13467) / 16    (Yamaguchi 1984)
  σ = 0.07 for f < fp, 0.09 for f ≥ fp
  γ = 3.3 (default peak enhancement factor)
```

Directional spreading (cos^ms power law):
```
D(θ) = A1 * max(cos(θ - θ_peak), 0)^ms

where:
  A1 = 2^ms * Γ(ms/2 + 1)² / (π * Γ(ms + 1))
  ms = spreading power (higher = narrower; typical: 2-20)
```

---

## Tool Reference

| Tool | Stage | Input | Output | Key Function |
|------|-------|-------|--------|--------------|
| `convert_boundary_spectra.py` | 2 | CSV/NetCDF wave data | .tpar/.spc files | Convert global wave data to SWAN boundary format |
| `convert_bathymetry.py` | 1 | GEBCO NetCDF, survey ASCII | .bot files | Regrid bathymetry to SWAN computational grid |
| `run_swan.py` | 5 | .swn + all inputs | .crv, .spc output | Execute SWAN binary with validation |
| `parse_swan_output.py` | 6 | .crv, .spc files | CSV, pandas DataFrame | Extract results from SWAN output |

---

## Key Conventions

1. **Direction convention**: SWAN uses nautical by default (SET NAUTICAL) — direction FROM which waves come, measured clockwise from North. Cartesian (CDIR) measures direction TO which waves propagate.

2. **Time format**: YYYYMMDD.HHMMSS (e.g., 20160101.000000). timecoding=1 is the standard.

3. **Coordinates**: LONLAT for geographic (degrees), LOCATIONS for Cartesian (meters). PySWaN stores both but uses whichever is non-None.

4. **Exception values**: NaN in PySWaN maps to SWAN exception values (typically -999 or NaN). Masked arrays handle this.

5. **FACTOR keyword**: In spectral data blocks, each location has FACTOR (with scale), ZERO (all zeros), or NODATA. PySWaN currently only handles FACTOR.

6. **Frequency types**: AFREQ = absolute frequency (Hz), RFREQ = relative frequency (relative to current). Almost always use AFREQ.

---

## Common Workflow

```python
import pyswan.oceanwaves as ow
import pyswan.swan as swan
import numpy as np
import datetime

# 1. Create parametric spectrum
Sp0 = ow.Spec0()
Sp0.t = datetime.datetime(2016, 1, 1)
Sp0.Hs = 2.5    # m
Sp0.Tp = 10.0   # s
Sp0.pdir = 270   # from west (nautical)
Sp0.ms = 4       # spreading power

# 2. Generate 1D JONSWAP
f = np.linspace(0.025, 1.0, 40)
Sp1 = ow.Spec1(f=f, t=[Sp0.t], lon=[4.0], lat=[52.0])
Sp1.from_jonswap(Sp0.Hs, Sp0.Tp, Sp0.pdir, Sp0.ms)

# 3. Generate 2D JONSWAP
dirs = list(np.arange(-12, 13) * 15)
Sp2 = ow.Spec2(f=f, direction=dirs, t=[Sp0.t], lon=[4.0], lat=[52.0])
Sp2.from_jonswap(Sp0.Hs, Sp0.Tp, Sp0.pdir, Sp0.ms)

# 4. Write to SWAN format
with open('boundary.spc', 'w') as fid:
    swan.to_file2D(Sp2, fid)

# 5. Read back and verify
with open('boundary.spc', 'r') as fid:
    Sp2_read = swan.from_file2D(fid)
print(f"Hm0: {Sp2_read.Hm0()[0,0]:.3f} m")  # should match input Hs

# 6. Write TPAR boundary
with open('boundary.tpar', 'w') as fid:
    swan.to_file0D(Sp0, fid)

# 7. Parse SWAN TABLE output
# (after running SWAN binary)
# parse_swan_output.py reads .crv files → DataFrame
```

---

## References

- SWAN Technical Documentation: swanmodel.sourceforge.io
- Booij, N., Ris, R.C. and Holthuijsen, L.H. (1999) "A third-generation wave model for coastal regions", J. Geophys. Res., 104(C4), 7649-7666
- Hasselmann, K. et al. (1973) "Measurements of wind-wave growth and swell decay during JONSWAP"
- NOAA Wave Examples: polar.ncep.noaa.gov/waves/examples/usingpython.shtml
- OpenEarth: github.com/openearth
