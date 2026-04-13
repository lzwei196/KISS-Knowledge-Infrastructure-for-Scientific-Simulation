# S7: Model Execution

## Purpose

Run the DHSVM binary, monitor progress, capture output, and detect common
failure modes. DHSVM is invoked with a single argument (the configuration file)
and produces output to stdout, stderr, and the configured output directory.

## Inputs

| Input | Description |
|-------|-------------|
| DHSVM binary | Compiled executable (from CMake build) |
| Configuration file | Complete DHSVM input file with all sections |
| Input data files | DEM, mask, soil, vegetation, met forcing, stream network |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Aggregated.Values | output_dir/ | Basin-averaged time series |
| Stream.Flow | output_dir/ | Stream discharge per segment |
| Mass.Balance | output_dir/ | Running water balance |
| Mass.Final.Balance | stderr | End-of-simulation mass balance summary |
| Pixel.* | output_dir/ | Point time series (if configured) |
| State files | state_dir/ | Model state for restart (if configured) |

## Procedure

1. **Verify all input files exist** before running. The most common runtime
   errors are missing files. Check:
   - DEM, mask, soil map, vegetation map (binary files)
   - Met forcing files (all grid cells present)
   - Stream network files (if NETWORK routing)
   - Output directory exists and is writable

2. **Run the model:**
   ```bash
   ./DHSVM INPUT.MyBasin > stdout.log 2> stderr.log
   ```

   Or use the wrapper:
   ```bash
   python tools/run_dhsvm.py \
     --binary build/DHSVM/sourcecode/DHSVM \
     --config INPUT.MyBasin \
     --timeout 7200 \
     --output run_report.json
   ```

3. **Monitor progress**: DHSVM prints the current timestep to stdout.
   Check stderr for warnings and the final mass balance.

4. **Check return code**: 0 = success, non-zero = error.

5. **Inspect mass balance**: The final mass balance printed to stderr should
   show closure < 1%. Large closure errors indicate a bug or incorrect inputs.

## Verification

- **Return code 0**: Model completed without fatal errors
- **Mass balance closure**: `|Inflow - Outflow - Storage Change| / Inflow < 1%`
- **Output files present**: Aggregated.Values, Stream.Flow exist and are non-empty
- **No NaN in output**: Check Aggregated.Values for NaN values
- **Reasonable streamflow**: Peak flow should be realistic for the basin size

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Missing met file | "Unable to open" error, crash | Verify GRID_DECIMAL and file names |
| DEM/mask size mismatch | Segfault or garbage output | Verify binary = nrows × ncols × 4 bytes |
| Veg height < ref height | NaN in wind calculations | Increase ref height or veg height |
| Output dir doesn't exist | Write error | Create directory before running |
| Disk full | Truncated output files | Check available space (DHSVM can produce GB of output) |
| Wrong working directory | Relative paths fail | Run from config file's directory |

## Example

```bash
# Full execution with logging
cd /path/to/basin/setup
../../build/DHSVM/sourcecode/DHSVM INPUT.Chiwawa.Baseline \
  > stdout.log 2> stderr.log
echo "Exit code: $?"

# Check mass balance
tail -20 stderr.log

# Quick output check
head -5 output/Aggregated.Values
wc -l output/Stream.Flow
```

## Typical Runtime

| Grid size | Timestep | Period | Approximate time |
|-----------|----------|--------|-----------------|
| 100×100 (90m) | 3 hr | 1 year | 1-5 minutes |
| 500×500 (90m) | 3 hr | 1 year | 15-60 minutes |
| 1000×1000 (30m) | 3 hr | 1 year | 1-4 hours |
| 500×500 (90m) | 3 hr | 30 years | 8-24 hours |
