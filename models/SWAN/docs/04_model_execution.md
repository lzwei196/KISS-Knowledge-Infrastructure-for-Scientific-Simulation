# Stage 5: Model Execution

## Purpose

Execute the SWAN wave model or the PySWaN spectral generation pipeline. This stage handles preflight validation, execution, and postflight checking. SWAN can run as the Fortran binary (full physics) or through PySWaN (spectral I/O and JONSWAP generation only).

## Inputs

### SWAN Binary Execution

| Input | Description |
|-------|-------------|
| `.swn` file | SWAN command input file |
| `.bot` file | Bathymetry grid |
| `.spc` / `.tpar` | Boundary spectral files |
| Wind files | Wind forcing (if GEN3 + wind enabled) |
| `swan.exe` / `swanrun` | SWAN executable |

### PySWaN Pipeline Execution

| Input | Description |
|-------|-------------|
| Wave parameters | Hs, Tp, pdir, ms, gamma |
| Frequency grid | np.linspace(fmin, fmax, nf) |
| Direction grid | np.arange(dir1, dir2, ddir) |
| Coordinate info | lon/lat or x/y arrays |

## Outputs

### SWAN Binary Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `.crv` | TABLE | Tabulated wave parameters along curves |
| `.s1d` / `.s2d` | SPEC | Spectral output at specified points |
| `PRINT` | Text | SWAN log file with warnings/errors |
| `norm_end` | Flag | Created on successful completion |

### PySWaN Pipeline Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `boundary_1d.spc` | SWAN spectral | 1D JONSWAP spectrum |
| `boundary_2d.spc` | SWAN spectral | 2D JONSWAP spectrum |
| `boundary.tpar` | TPAR | Parametric boundary file |

## Procedure

### Option A: SWAN Binary

1. **Preflight checks**
   ```python
   from ki.tools.run_swan import validate_swn_inputs
   check = validate_swn_inputs('run.swn', swan_binary='/path/to/swan.exe')
   print(check['status'])  # 'OK' or error details
   ```

2. **Execute**
   ```python
   from ki.tools.run_swan import run_swan_binary
   result = run_swan_binary('run.swn', swan_binary='/path/to/swan.exe',
                             timeout=3600)
   ```

3. **Postflight**
   - Check return code = 0
   - Check PRINT file for ERROR lines
   - Verify output files exist and are non-empty

### Option B: PySWaN Pipeline

1. **Execute round-trip test**
   ```python
   from ki.tools.run_swan import run_pyswan_pipeline

   params = {
       'Hs': 1.0, 'Tp': 10.0, 'pdir': 270.0, 'ms': 4,
       'gamma': 3.3, 'fmin': 0.025, 'fmax': 1.0, 'nf': 40,
       'lon': [4.0], 'lat': [52.0],
       't': [datetime.datetime(2016, 1, 1)],
   }
   result = run_pyswan_pipeline(params, './output', mode='roundtrip_test')
   print(result['status'])   # 'OK'
   print(result['metrics'])  # Hm0 verification
   ```

2. **Check metrics**
   - `error_1D` and `error_2D` should be < 0.01 (1% of Hs)

## Verification

### SWAN Binary
- [ ] Return code = 0
- [ ] `norm_end` file exists (clean termination)
- [ ] No ERROR in PRINT file
- [ ] Output files exist with reasonable sizes
- [ ] Hs in output matches boundary condition at boundary points

### PySWaN Pipeline
- [ ] All output files created
- [ ] Round-trip Hm0 matches input Hs within 1%
- [ ] Spectral shape is reasonable (peak at fp = 1/Tp)
- [ ] No NaN in energy arrays

```python
# Quick verification
result = run_pyswan_pipeline(params, './output', mode='roundtrip_test')
assert result['status'] == 'OK'
assert result['metrics']['error_1D'] < 0.01
assert result['metrics']['error_2D'] < 0.01
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| **Binary not found** | FileNotFoundError | Check swan.exe path; may need `swanrun` wrapper |
| **Missing input file** | SWAN error in PRINT | Run preflight check; ensure all .bot and .spc files exist |
| **Grid mismatch** | "grid does not cover" error | INPGRID extent must cover CGRID |
| **Timestep too large** | Numerical instability, crash | Reduce NUM ACCUR timestep; typical: 1-5 min for nearshore |
| **Stationary mode on non-stationary input** | Uses only first timestep | Match MODE NONSTAT with TIME header in spectral files |
| **Output location outside grid** | Zero or missing values | CURVE/TABLE locations must be within CGRID extent |
| **Memory overflow** | SWAN crash on large grids | Reduce grid resolution or use parallel (MPI) SWAN |

## Example

Running the PySWaN test suite:
```python
import unittest
from pyswan.swantest import TestSuite

# This generates JONSWAP spectra, writes to SWAN format,
# reads back, and verifies Hm0 = 1.0 m within tolerance
suite = unittest.TestLoader().loadTestsFromTestCase(TestSuite)
unittest.TextTestRunner(verbosity=2).run(suite)
```

Running SWAN binary (from the test data):
```bash
# Windows (from data/ directory)
call swanrun 1D_llstat

# Linux
swan.exe 1D_llstat
# or
swanrun -input 1D_llstat.swn
```
