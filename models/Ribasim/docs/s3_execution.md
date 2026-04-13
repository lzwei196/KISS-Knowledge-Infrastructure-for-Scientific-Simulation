# Stage 3: Model Execution

## Purpose

Run the Ribasim simulation using either the compiled CLI binary or the Python
API (via JuliaCall). This stage performs preflight validation, executes the
solver, and verifies output integrity.

## Inputs

| Input | Format | Source | Required |
|-------|--------|--------|----------|
| Configuration file | TOML | Stage 0 | Yes |
| GeoPackage database | GPKG | Stages 1-2 | Yes |
| Ribasim binary or Python package | Executable / pip | Installation | Yes |

## Outputs

| Output | Format | Path |
|--------|--------|------|
| Basin water balance | NetCDF | `results/basin.nc` |
| Link flow rates | NetCDF | `results/flow.nc` |
| Final basin states | NetCDF | `results/basin_state.nc` |
| Control state log | NetCDF | `results/control.nc` (if control nodes) |
| Allocation results | NetCDF | `results/allocation.nc` (if allocation) |
| Solver statistics | NetCDF | `results/solver_stats.nc` |

## Procedure

### Step 1: Preflight checks

Before running, verify:
1. `ribasim.toml` exists and parses correctly
2. `input/database.gpkg` exists and contains required tables
3. All referenced NetCDF files exist
4. `results/` directory is writable
5. Ribasim binary is accessible

```bash
# Check binary
ribasim --version

# Check TOML
python -c "import tomllib; tomllib.load(open('ribasim.toml', 'rb'))"

# Check GeoPackage
python -c "
import sqlite3
conn = sqlite3.connect('input/database.gpkg')
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
print('Tables:', tables)
assert 'Node' in tables or 'node' in tables, 'Missing Node table'
conn.close()
"
```

### Step 2: Run the model

**Method 1: CLI binary** (recommended for production):
```bash
ribasim ribasim.toml
# Multi-threaded:
JULIA_NUM_THREADS=4 ribasim ribasim.toml
```

**Method 2: Python API** (for scripting):
```python
import ribasim
ribasim.run_ribasim("ribasim.toml")
```

**Method 3: Julia directly** (for development):
```bash
julia --project=core -e 'using Ribasim; Ribasim.main(ARGS)' -- ribasim.toml
```

### Step 3: Monitor progress

Ribasim logs progress to stdout/stderr:
- `info`: Normal progress messages
- `warn`: Non-fatal issues (high water balance error)
- `error`: Fatal problems (solver divergence)

Set verbosity in TOML:
```toml
[logging]
verbosity = "debug"    # For troubleshooting
```

### Step 4: Post-run validation

Check output files exist and are valid:
```python
import xarray as xr

# Check basin output
ds = xr.open_dataset("results/basin.nc")
print(f"Time steps: {ds.dims['time']}")
print(f"Basins: {ds.dims.get('node_id', 'N/A')}")

# Check water balance error
if "relative_error" in ds:
    max_err = abs(ds["relative_error"]).max().values
    print(f"Max relative balance error: {max_err:.6f}")
    assert max_err < 0.01, f"Balance error too high: {max_err}"

ds.close()
```

### Step 5: Runtime expectations

| Model Size | Nodes | Expected Runtime | Memory |
|-----------|-------|-----------------|--------|
| Small | < 50 | 1-10 seconds | < 100 MB |
| Medium | 50-500 | 10-60 seconds | 100-500 MB |
| Large | 500-5000 | 1-10 minutes | 0.5-2 GB |
| Very large (NHI) | > 5000 | 10-60 minutes | 2-8 GB |

First run includes Julia compilation overhead (~30-60 seconds).

## Verification

1. All expected output files exist in `results/`
2. `basin.nc` has the correct number of timesteps: `(endtime - starttime) / saveat`
3. Water balance relative error < 1% for all basins
4. No NaN values in level or flow outputs
5. Final basin levels are physically reasonable

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| First-run compilation | Expected | Julia compiles on first execution (~30-60s overhead). Subsequent runs are fast. |
| Solver divergence | Fatal | Usually from extreme forcing values or ill-defined profiles. Check units first. |
| Empty results | Fatal | If solver fails immediately, output files may be created but empty. Check file sizes. |
| Memory overflow | Fatal | Very large models (>10k nodes) may exceed available RAM. Use sparse=true. |
| Water balance error | Degraded | High balance errors indicate the solver is struggling. Reduce tolerances or simplify the model. |
| Path resolution | Fatal | Ribasim resolves paths relative to TOML file location. Absolute paths in TOML are not recommended. |

## Example

```bash
# Full execution workflow
cd my_model/

# 1. Preflight
ls input/database.gpkg   # Must exist
cat ribasim.toml          # Verify configuration

# 2. Run
ribasim ribasim.toml 2>&1 | tee run.log

# 3. Check outputs
ls -la results/
python -c "
import xarray as xr
ds = xr.open_dataset('results/basin.nc')
print('Timesteps:', ds.dims.get('time', 0))
print('Variables:', list(ds.data_vars))
ds.close()
"
```
