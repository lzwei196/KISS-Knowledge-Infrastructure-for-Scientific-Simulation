# Stage 7: Troubleshooting Guide

## Purpose

Diagnose and resolve common PRMS errors, organized by failure symptom. This guide complements the diagnostic triplets in `diagnostics/triplets.yaml`.

## Common Error Messages and Solutions

### 1. "Usage: Set the full path to the control file using the '-C' option."

**Cause**: No control file specified or `-C` flag used incorrectly.

**Fix**:
```bash
# CORRECT (no space after -C)
./prms_hpc -C/path/to/control

# WRONG
./prms_hpc -C /path/to/control
./prms_hpc  # no -C at all
```

### 2. "read_control: Couldn't open <filename>"

**Cause**: Control file path doesn't exist.

**Fix**: Check the path. Use absolute paths to avoid working directory issues.

### 3. "#### delimiter not found in data file"

**Cause**: Data file is missing the `####` line that separates the header from data.

**Fix**: Ensure data file has this structure:
```
Info line
variable1 count1
variable2 count2
####
data lines...
```

### 4. "Variable X not declared at line N"

**Cause**: The data file references a variable that the selected modules don't declare.

**Fix**: Either:
- Remove the variable from the data file header, or
- Select a module that uses that variable

### 5. "Parameter File: <path> is empty."

**Cause**: Parameter file exists but has zero bytes.

**Fix**: Regenerate the parameter file using `convert_params_to_prms.py`.

### 6. Segmentation fault during initialization

**Causes**:
- Dimension mismatch (nhru in param file != nhru in CBH files)
- Array out of bounds from incorrect parameter counts
- Memory allocation failure for very large nhru

**Fix**: Verify all dimension values are consistent across control, parameter, data, and CBH files.

### 7. "ERROR in declare procedure"

**Cause**: Module initialization failed, usually due to missing parameters or incompatible module combination.

**Fix**: Check that all required parameters for the selected modules are present in the parameter file. Run with `-print` flag to see what parameters are expected.

### 8. Model runs but produces zero streamflow

**Causes**:
- Precipitation in wrong units (too small after conversion error)
- All precipitation classified as snow but never melts (temperature units wrong)
- soil_moist_max too large (all water absorbed, none reaches stream)

**Fix**: Check unit conversions. Verify temperature is in Fahrenheit and precipitation in inches.

### 9. Model runs but produces extreme flooding

**Causes**:
- Precipitation not converted from mm to inches (25.4x too much)
- soil_moist_max too small
- smidx_coef too large

**Fix**: Check mean annual precipitation. Typical US basins: 15-60 inches/year.

### 10. "Decoding error at line N in data file"

**Cause**: Malformed data in the data file. Common issues:
- Non-numeric values in data columns
- Missing values (empty fields)
- Wrong number of columns

**Fix**: Check data file at the reported line number. Ensure all values are numeric and column count matches header declarations.

## Diagnostic Checklist

When PRMS fails, check in this order:

1. **Does the binary exist and is it executable?**
   ```bash
   ls -la ./prms_hpc && ./prms_hpc 2>&1 | head -1
   ```

2. **Does the control file parse correctly?**
   ```bash
   ./prms_hpc -C/path/to/control -print
   ```

3. **Are all referenced files present?**
   ```bash
   grep -A2 "param_file\|data_file\|tmax_day\|tmin_day\|precip_day" control
   ```

4. **Are dimensions consistent?**
   Check `nhru` in parameter file matches column count in CBH files.

5. **Are units correct?**
   - Temperature: mean should be 30-80 F for temperate regions
   - Precipitation: mean should be 0.01-0.3 inches/day
   - Elevation: should be > 100 if in feet

6. **Is the data period correct?**
   The data/CBH files must cover the full `start_time` to `end_time` range.

## Performance Diagnostics

| Symptom | Likely Cause | Parameter to Adjust |
|---------|-------------|-------------------|
| Simulated flow too high | soil_moist_max too small | Increase soil_moist_max |
| Simulated flow too low | soil_moist_max too large | Decrease soil_moist_max |
| Baseflow too quick | gwflow_coef too high | Decrease gwflow_coef |
| Baseflow too slow | gwflow_coef too low | Increase gwflow_coef |
| Peak flows too high | smidx_coef too high | Decrease smidx_coef |
| Peak flows too low | smidx_coef too low | Increase smidx_coef |
| Snow persists too long | tmax_allsnow too high | Decrease tmax_allsnow |
| Snow melts too fast | tmax_allsnow too low | Increase tmax_allsnow |
| ET too high | jh_coef too high | Decrease jh_coef |
| ET too low | jh_coef too low | Increase jh_coef |
