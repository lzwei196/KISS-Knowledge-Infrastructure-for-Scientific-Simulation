# Stage 4: Model Execution

## Purpose

Compile (if needed) and run the TRIGRS model binary. This includes running the TopoIndex utility for grid dimensions and flow routing setup, then executing TRIGRS itself. The execution stage also includes preflight validation and post-run output checking.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| tr_in.txt | Text file | Stage 2/3 / generate_tr_in.py | TRIGRS initialization file |
| tpx_in.txt | Text file | Manual / template | TopoIndex initialization file |
| All input grids | ESRI ASCII (.asc) | Stages 1-3 | DEM, slope, zones, depth, rainfall, etc. |
| Fortran source | .f90/.f95/.f files | USGS repository | TRIGRS source code |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| trg (or prg) | Binary executable | Compiled TRIGRS serial (or parallel) |
| tpx | Binary executable | Compiled TopoIndex |
| TRfs_min_*.asc | ESRI ASCII grid | Factor of safety grids |
| TRz_at_fs_min_*.asc | ESRI ASCII grid | Depth of minimum FS |
| TRp_at_fs_min_*.asc | ESRI ASCII grid | Pressure head at min FS depth |
| TrigrsLog.txt | Text file | Run log with mass balance |

## Procedure

### Step 1: Install compiler

```bash
# Ubuntu/Debian
sudo apt install gfortran libopenmpi-dev make

# Verify
gfortran --version
```

### Step 2: Compile TRIGRS

```bash
cd src/TRIGRS

# Serial version only
make trg

# Both serial and parallel
make all

# TopoIndex (if Makefile target exists)
make tpx

# Verify compilation
ls -la trg prg tpx 2>/dev/null
```

**Common compilation issues:**

| Error | Cause | Fix |
|-------|-------|-----|
| `mpif90: not found` | MPI not installed | `apt install libopenmpi-dev` |
| `undefined reference to dgsl*` | GSL library missing | `apt install libgsl-dev` or remove GSL flags from Makefile |
| `Error: Rank mismatch` | Compiler strictness | Add `-w` flag to suppress warnings |

### Step 3: Run TopoIndex

```bash
# From the working directory containing tpx_in.txt
./tpx
# or
/path/to/tpx
```

TopoIndex creates:
- `TIgrid_size.txt` in the DEM folder (required by TRIGRS)
- D8 neighbor cell grids (for runoff routing)
- Cell index lists
- Weighting factor lists

### Step 4: Run TRIGRS

```bash
# Serial execution
./trg

# Parallel execution (4 processes)
mpirun -np 4 ./prg
```

TRIGRS reads `tr_in.txt` from the **current working directory**. There is no command-line option to specify a different init file.

### Step 5: Monitor execution

TRIGRS prints progress to stdout:
```
TRIGRS: Transient Rainfall Infiltration
and Grid-based Regional Slope-Stability
               Analysis
       Version  2.1.00c, 02 Feb 2022
  By Rex L. Baum and William Z. Savage
       U.S. Geological Survey
-----------------------------------------
```

Check `TrigrsLog.txt` for detailed output including mass balance.

## Verification

```bash
# Check TRIGRS completed
grep -i "error\|warning\|finished" TrigrsLog.txt

# Verify output grids exist
ls -la data/output/TR*.asc

# Quick sanity check on FS values
python3 -c "
import numpy as np
fs = np.loadtxt('data/output/TRfs_min_run01_1.asc', skiprows=6)
valid = fs[fs != -9999]
print(f'FS range: {valid.min():.3f} to {valid.max():.3f}')
print(f'Unstable cells (FS<1): {(valid<1).sum()} / {valid.size}')
"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| No TIgrid_size.txt | TRIGRS reads DEM directly (slower) | Run TopoIndex first |
| tr_in.txt not in cwd | TRIGRS hangs waiting for input | cd to dir with tr_in.txt |
| File paths in tr_in.txt wrong | "File not found" errors in log | Use relative paths from cwd |
| Grid size mismatch | Array bounds crash | Run GridMatch on all grids |
| Infinite series non-convergence | Very long runtime | Increase nmax or reduce domain |
| Memory overflow on large grids | Segfault or killed | Use parallel version or subsample |

## Example

```bash
# Complete execution workflow
cd /my/project/

# 1. Compile
cd src/TRIGRS && make trg && cd ../..

# 2. Copy binary to working directory (optional)
cp src/TRIGRS/trg .

# 3. Run TopoIndex
./tpx

# 4. Run TRIGRS
./trg

# 5. Check results
python parse_trigrs_output.py \
    --output_dir data/output/ \
    --suffix run01 \
    --result_csv results.csv
```
