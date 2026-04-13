# Stage 6: Model Execution

## Purpose
Run the GSFLOW binary with a prepared control file and all input files,
capture output, and verify successful completion.

## Inputs
- GSFLOW executable (`gsflow` on Linux, `gsflow.exe` on Windows)
- Control file (`.control`) with all paths resolved
- All referenced input files:
  - PRMS: data file, parameter files, .day files
  - MODFLOW: name file and all package files
- Sufficient disk space for output files

## Outputs
- PRMS listing file (`model_output_file`)
- GSFLOW water budget file (`gsflow_output_file`)
- CSV basin summary (`csv_output_file`)
- MODFLOW listing file (`.list`)
- MODFLOW head and budget files (`.hds`, `.cbc`)
- SFR gage output files (if configured)

## Procedure

1. **Pre-flight checks:**
   - Verify executable exists and is executable (`chmod +x gsflow`)
   - Verify control file parses correctly
   - Verify all referenced files exist
   - Check disk space (rule of thumb: output ≈ 10× input for daily output)

2. **Run the model:**
   ```bash
   # Basic execution
   gsflow path/to/gsflow.control

   # With output capture
   gsflow path/to/gsflow.control > gsflow.log 2>&1

   # Python wrapper
   python run_gsflow.py \
       --executable ./gsflow \
       --control-file ./control/gsflow.control \
       --timeout 7200
   ```

3. **Monitor progress:**
   - GSFLOW prints progress to stdout (year-month being processed)
   - Watch for convergence warnings
   - Large models may take hours to days

4. **Post-run checks:**
   - Check return code (0 = success)
   - Examine listing file for errors
   - Verify output files exist and are non-empty
   - Check water budget closure

## Verification
- Return code = 0
- Listing file does not contain "ERROR" or "FAILED"
- Output CSV file has correct number of days
- MODFLOW listing shows water budget closure (IN ≈ OUT within 1%)
- No "SOLVER CONVERGENCE FAILURE" in listing file
- Output file sizes are reasonable (not 0 bytes, not unexpectedly small)

## Traps
- **Timeout:** Large basins with fine grids can take very long.
  Set appropriate timeout (12–24 hours for large models).
- **Memory:** GSFLOW uses dynamic allocation. Very large models may
  exhaust available RAM → use swap or reduce grid resolution.
- **Convergence failure:** MODFLOW solver may not converge for some
  stress periods. Check:
  - Initial heads are reasonable (not too far from steady state)
  - Hydraulic conductivity values are physically reasonable
  - Grid spacing is not too fine relative to aquifer properties
  - Try NWT solver instead of PCG
- **Silent output errors:** If output files are empty:
  - Check `basinOutON_OFF = 1` in control file
  - Check output directory exists (GSFLOW won't create directories)
  - Check disk space
- **Path encoding:** Control file paths with special characters or
  spaces will fail. Use simple paths without spaces.
- **Working directory:** GSFLOW resolves relative paths from the
  working directory, NOT the control file location (in some versions).
  Run from the directory containing the control file to be safe.

## Example
```bash
# Compile and run sagehen example
cd gsflow_v2/GSFLOW/data/sagehen

# Fix paths for Linux
find . -name "*.control" -exec sed -i 's|\\|/|g' {} \;

# Run
../../bin/gsflow windows/gsflow.control

# Check output
head -5 output/prms/gsflow.out
wc -l output/prms/*.csv
```
