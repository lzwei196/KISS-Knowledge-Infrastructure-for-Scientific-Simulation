# Stage 2: Boundary Spectra Preparation

## Purpose

Prepare wave boundary conditions for SWAN from global wave model output (ERA5, WaveWatch III), buoy observations, or parametric definitions. SWAN accepts boundary spectra as parametric time series (TPAR), 1D frequency spectra (.spc), or 2D frequency-direction spectra (.spc). This stage converts source data to the required SWAN format with correct units.

## Inputs

| Input | Format | Source | Units |
|-------|--------|--------|-------|
| Wave parameters | CSV, NetCDF | ERA5, buoys, manual | Hs (m), Tp (s), Dir (deg) |
| Spectral data | NetCDF, GRIB | WW3, ERA5 spectra | m²/Hz/rad or m²/Hz/deg |
| Frequency grid | Array | User-defined | Hz |
| Direction grid | Array | User-defined | degrees |

### Key Input Variables

| Variable | Unit | Range | Description |
|----------|------|-------|-------------|
| Hs | m | 0.1 - 20 | Significant wave height |
| Tp | s | 1 - 25 | Peak wave period |
| pdir | degrees (nautical) | 0 - 360 | Peak wave direction FROM which waves come |
| ms | dimensionless | 1 - 100 | Directional spreading power (cos^ms) |
| gamma | dimensionless | 1 - 10 | JONSWAP peak enhancement (default 3.3) |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `boundary.tpar` | TPAR | Parametric boundary (simplest) |
| `boundary_1d.spc` | SWAN spectral | 1D frequency spectrum |
| `boundary_2d.spc` | SWAN spectral | 2D frequency-direction spectrum |

### TPAR Format

```
TPAR $yyyymmdd.HHMMSS Hs Tp pdir ms
19920516.130000 1.0 5 -90 10
20160101.000000 2.5 10 270 4
```

### SWN Command to Use Boundary

```
BOUN SHAPE BIN PEAK DSPR POWER
BOUN SIDE W CCW VAR FILE 0 'boundary.spc'
```

or for TPAR:
```
BOUN SIDE W CCW CON FILE 'boundary.tpar'
```

## Procedure

1. **Determine boundary type**
   - TPAR: simplest, uses parametric JONSWAP reconstruction inside SWAN
   - 1D/2D: more accurate, prescribes actual spectral shape

2. **Convert units if needed**
   ```python
   from ki.tools.convert_boundary_spectra import (
       hs_cm_to_m, freq_to_period,
       cartesian_to_nautical, spreading_deg_to_power
   )

   # Common conversions
   hs_m = hs_cm_to_m(hs_cm)           # cm → m: divide by 100
   tp_s = freq_to_period(fp_hz)        # Hz → s: Tp = 1/fp
   naut_dir = cartesian_to_nautical(cart_dir)  # (270 - cart) mod 360
   ms = spreading_deg_to_power(sigma_deg)      # σ → ms ≈ 2/σ_rad² - 1
   ```

3. **Generate boundary file**
   ```python
   from ki.tools.convert_boundary_spectra import convert_to_tpar
   import datetime

   params = {
       't': [datetime.datetime(2016, 1, 1)],
       'Hs': 2.5,
       'Tp': 10.0,
       'pdir': 270.0,  # from west, nautical
       'ms': 4.0,
   }
   result = convert_to_tpar(params, 'boundary.tpar')
   ```

4. **For spectral boundaries**
   ```python
   from ki.tools.convert_boundary_spectra import convert_to_spec2d
   import numpy as np

   params['f'] = np.linspace(0.025, 1.0, 40)
   params['directions'] = list(np.arange(-12, 13) * 15)
   params['lon'] = [4.0]
   params['lat'] = [52.0]
   result = convert_to_spec2d(params, 'boundary_2d.spc', gamma=3.3)
   ```

5. **Verify round-trip**
   - Read back the written file and check Hm0 matches input Hs within 1%

## Verification

- [ ] Output file exists and is non-empty
- [ ] Read-back Hm0 matches input Hs within 1%
- [ ] Time stamps are correctly formatted (YYYYMMDD.HHMMSS)
- [ ] Direction convention matches SET command in .swn (NAUTICAL vs CARTESIAN)
- [ ] Spectral file header matches coordinate system (LONLAT vs LOCATIONS)

```python
import pyswan.swan as swan
with open('boundary.spc', 'r') as f:
    spec = swan.from_file2D(f)
print(f"Hm0 = {spec.Hm0()[0,0]:.3f} m (expected: {Hs})")
assert abs(spec.Hm0()[0,0] - Hs) < 0.01 * Hs
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| **Direction convention** | Wave energy propagates wrong way | Check if using nautical (FROM) vs Cartesian (TO); convert with `cartesian_to_nautical()` |
| **Hs in cm** | Unrealistic wave heights (>30m) | Divide by 100 |
| **Period vs frequency** | Very short periods (<0.5s) | If Tp < 0.5, it's likely frequency in Hz; use Tp = 1/fp |
| **m²/Hz/rad vs m²/Hz/deg** | Hm0 off by factor ~57 | Multiply energy by π/180 (= 0.01745) to convert rad→deg |
| **Spreading σ vs ms** | Wrong spectral shape | σ (degrees) ≠ ms (power); convert with `spreading_deg_to_power()` |
| **Missing TIME header** | SWAN expects stationary | Non-stationary runs need TIME header in spectral file |
| **timecoding** | Garbled timestamps | timecoding=1 means YYYYMMDD.HHMMSS fixed format |

## Example

From the PySWaN test suite — round-trip JONSWAP:
```python
import oceanwaves as ow, swan
import numpy as np, datetime

f = np.linspace(0.025, 1, 40)
t = [datetime.datetime(2016,1,1), datetime.datetime(2016,1,2)]
Sp = ow.Spec1(f=f, t=t, lon=[0,100], lat=[0,0])
Sp.from_jonswap(1, 5, -90, 10)  # Hs=1m, Tp=5s, pdir=-90°, ms=10

with open('test.spc', 'w') as fid:
    swan.to_file1D(Sp, fid)
with open('test.spc', 'r') as fid:
    T = swan.from_file1D(fid)

print(f"Hm0 = {T.Hm0()[0,0]:.4f}")  # Expected: ~1.0000
```
