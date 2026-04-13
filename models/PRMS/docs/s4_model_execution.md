# Stage 4: Model Execution

## Purpose

Run the PRMS binary with preflight validation and post-run diagnostics.

## Inputs

- Compiled PRMS binary (`prms_hpc`)
- Control file from Stage 3
- All referenced input files (parameter, data, CBH)

## Outputs

- Model output file (water balance summary)
- CSV output (if enabled)
- NetCDF output (if enabled)
- Log/stdout output

## Procedure

### Step 1: Preflight checks

```python
from tools.run_prms import validate_inputs
validated = validate_inputs(binary, control, work_dir)
```

Checks performed:
1. Binary exists and is executable
2. Control file is readable
3. All referenced files (param, data, CBH) exist
4. Sufficient disk space for output

### Step 2: Execute PRMS

```bash
# CRITICAL: No space between -C and the path
./prms_hpc -C/path/to/control
```

**Common flags**:
- `-C<path>`: Control file path (REQUIRED, no space)
- `-print`: Print parameters and exit (useful for debugging)
- `-set <var> <val>`: Override a control variable

### Step 3: Monitor execution

PRMS prints module initialization to stdout:
```
U.S. Geological Survey
Precipitation-Runoff Modeling System (PRMS)
Version 5.1.0 05/01/2020

Process                Available Modules
--------------------------------------------------------------------
Basin Definition: basin
...
```

Typical runtime: 1-30 seconds for single basins, minutes for NHM-scale.

### Step 4: Post-run validation

```python
from tools.run_prms import validate_outputs
findings = validate_outputs(work_path, referenced_files, run_result)
```

Checks:
1. Exit code = 0
2. Output files created and non-empty
3. No error messages in stderr

## Verification

- [ ] Exit code is 0
- [ ] Model output file exists and is non-empty
- [ ] CSV output file has data rows (if enabled)
- [ ] No "ERROR" messages in stdout/stderr
- [ ] Runtime is reasonable (< 60s for typical basins)

## Traps

### 1. -C flag space trap (CRITICAL)

```bash
# CORRECT — no space
./prms -C/home/user/prms/control

# WRONG — space causes failure
./prms -C /home/user/prms/control
```

With a space, PRMS treats `/home/user/prms/control` as a separate argument and defaults to looking for a file called "control" in the current directory.

### 2. Library not found (libnetcdf, libgfortran)

If PRMS was compiled with NetCDF support, the runtime libraries must be available:
```bash
export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/hdf5/serial:$LD_LIBRARY_PATH
```

### 3. "Variable X not declared" error

This means the data file contains a variable that PRMS doesn't expect for the selected modules. Remove the variable from the data file header or select the appropriate module.

### 4. Dimension mismatch crash

If the parameter file says `nhru = 42` but the CBH file has 40 columns, PRMS crashes during initialization. Always verify dimensions are consistent.

### 5. Silent wrong results

PRMS may run to completion but produce incorrect results if:
- Units are wrong (see Stage 1 traps)
- Parameters are out of physical range
- Wrong module selected for available data

Always compare output against observed data when available.

## Example

```bash
# Full run
python tools/run_prms.py \
    --binary /prms/source/repo/prms/prms_hpc \
    --control /prms/control \
    --work_dir /prms/output

# Quick test (print mode)
./prms_hpc -C/prms/control -print
```

Output:
```
[preflight] Parameter file: /prms/input/prms.params (OK)
[preflight] CBH file: /prms/input/tmax.cbh (OK)
[preflight] CBH file: /prms/input/tmin.cbh (OK)
[preflight] CBH file: /prms/input/precip.cbh (OK)
[run] Command: /prms/prms_hpc -C/prms/control
[run] SUCCESS — completed in 3.2s
[post] Model output: /prms/output/prms.out (45678 bytes)
[post] CSV output: /prms/output/prms.csv (23456 bytes)
```
