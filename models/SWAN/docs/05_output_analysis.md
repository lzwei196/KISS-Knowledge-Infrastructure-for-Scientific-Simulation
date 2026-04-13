# Stage 6: Output Parsing and Analysis

## Purpose

Parse SWAN output files (TABLE curves, spectral files) into structured data for analysis, visualization, and comparison with observations. Extract bulk wave parameters (Hs, Tp, Tm01, Tm02, direction) from spectral output and export to CSV for further processing.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| `.crv` / `.tab` | TABLE output | SWAN run | Tabulated wave parameters along curves |
| `.s1d` | SPEC1D output | SWAN run | 1D spectral output at specified points |
| `.s2d` / `.spc` | SPEC2D output | SWAN run | 2D spectral output at specified points |
| `.tpar` | TPAR | SWAN boundary | Parametric time series |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| CSV file | CSV | Tabulated wave parameters with headers |
| pandas DataFrame | In-memory | For further analysis |
| Spectral plots | PNG | 1D line plots, 2D polar plots |

### Key Output Variables

| Variable | Symbol | Unit | Description |
|----------|--------|------|-------------|
| Significant wave height | Hsig / Hm0 | m | 4√m0, primary wave parameter |
| Peak period | RTpeak / Tp | s | Period of spectral peak |
| Mean period (m01) | Tm01 | s | m0/m1 spectral moment ratio |
| Mean period (m02) | Tm02 | s | √(m0/m2) spectral moment ratio |
| Peak direction | PkDir / pdir | deg | Direction of spectral peak |
| Water depth | Depth | m | Bottom depth at output location |
| X-coordinate | Xp | m or deg | Easting or longitude |
| Y-coordinate | Yp | m or deg | Northing or latitude |

## Procedure

### 1. Parse TABLE Output (.crv)

```python
from ki.tools.parse_swan_output import parse_table, table_to_csv

# Parse to dict
data = parse_table('gauge_output.crv')
print(f"Columns: {data['columns']}")
print(f"Hs range: {data['Hsig'].min():.3f} - {data['Hsig'].max():.3f} m")

# Export to CSV
table_to_csv('gauge_output.crv', 'gauge_output.csv')
```

### 2. Parse 1D Spectral Output

```python
from ki.tools.parse_swan_output import parse_spec1d, extract_spectral_params

spec = parse_spec1d('output_points.s1d')
params = extract_spectral_params(spec, output_csv='spectral_params.csv')
print(f"Hm0: {params['Hm0'][0,0]:.3f} m")
print(f"Tm01: {params['Tm01'][0,0]:.3f} s")
```

### 3. Parse 2D Spectral Output

```python
from ki.tools.parse_swan_output import parse_spec2d

spec = parse_spec2d('output_points.spc')
print(f"Hm0: {spec.Hm0()[0,0]:.3f} m")
print(f"Tp: {spec.Tp():.3f} s")
print(f"Peak dir: {spec.pdir():.1f} deg")
```

### 4. Visualize Spectra

```python
# 1D spectrum plot
spec1d = parse_spec1d('output.s1d')
spec1d.plot('spectrum_1d.png')

# 2D spectrum polar plot
spec2d = parse_spec2d('output.spc')
spec2d.plot('spectrum_2d.png')
```

### 5. Compare with Observations

```python
import numpy as np

# Load observed data
obs_hs = np.loadtxt('observed_hs.csv')

# Parse simulated
data = parse_table('output.crv')
sim_hs = data['Hsig']

# Compute metrics
bias = np.mean(sim_hs - obs_hs)
rmse = np.sqrt(np.mean((sim_hs - obs_hs)**2))
r = np.corrcoef(obs_hs, sim_hs)[0, 1]
scatter_index = rmse / np.mean(obs_hs)

print(f"Bias: {bias:.3f} m")
print(f"RMSE: {rmse:.3f} m")
print(f"R: {r:.3f}")
print(f"Scatter Index: {scatter_index:.3f}")
```

## Verification

- [ ] Parsed column count matches header
- [ ] No all-zero or all-NaN columns
- [ ] Hs values are positive and within physical bounds (0-25 m)
- [ ] Periods are positive (1-25 s typically)
- [ ] Directions are within 0-360 range
- [ ] Spatial extent of output matches expected domain

```python
data = parse_table('output.crv')
assert data['n_rows'] > 0, "No data rows parsed"
assert np.all(data['Hsig'] >= 0), "Negative Hs values"
assert np.all(data['RTpeak'] > 0), "Non-positive periods"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| **Exception values** | -999 or -99 in output | These are SWAN's NaN markers; mask before analysis |
| **Nautical vs Cartesian dir** | Direction off by 180° or mirrored | Check SET command in .swn and direction_units in Spec objects |
| **Tp vs Tm01 vs Tm02** | Periods don't match expectations | Tp (peak) > Tm01 > Tm02 always; don't confuse them |
| **Hs = 0 at boundary** | Boundary not correctly prescribed | Check BOUN command and boundary file location/format |
| **Energy units mismatch** | Hm0 off by factor | m²/Hz/deg vs m²/Hz/rad — check energy_units attribute |
| **Missing timesteps** | Fewer data rows than expected | Check COMPUTE time range matches boundary data coverage |
| **Spectrum all NaN** | NODATA or ZERO marker | Point is outside active domain or in dry cell |

## Example

Parsing the 1D flume test CRV output:
```python
data = parse_table('data/1D_llstat.crv')

# Expected columns: Xp, Yp, PkDir, Hsig, RTpeak, Tm01, Tm02, Depth
# For Hs=1m boundary input, Hsig should start at ~1.0 and decay along flume
print(f"Hs at x=0: {data['Hsig'][0]:.3f} m")    # ~1.001
print(f"Hs at x=1000: {data['Hsig'][-1]:.3f} m") # ~0.70 (shoaling losses)
print(f"Depth: {data['Depth'][0]:.1f} m")          # 2.0 (uniform)
```
