# Stage 6: Model Execution

## Purpose

Compile the Noah-MP HRLDAS driver binary (if needed), validate all prerequisites,
run the model, and verify output completeness. This stage transforms prepared inputs
(forcing, parameters, namelist) into LDASOUT result files.

## Inputs

| Input | Source | Required |
|-------|--------|----------|
| Noah-MP source code | `source/repo/` | Yes |
| `namelist.hrldas` | Stage s0 | Yes |
| LDASIN forcing files | Stage s4 | Yes |
| HRLDAS setup file (wrfinput) | Stage s1 | Yes |
| NoahmpTable.TBL | `parameters/` | Yes |
| SNICAR optics files | `parameters/` | Only if snow_albedo_option=3 |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `YYYYMMDDHH00.LDASOUT_DOMAIN1` | NetCDF | Model state/flux output per timestep |
| `RESTART.YYYYMMDDHH_DOMAIN1` | NetCDF | Restart files (if configured) |

## Procedure

### 1. Compilation

#### Prerequisites
- Fortran compiler: `gfortran >= 8.0` or `ifort >= 19.0`
- NetCDF-Fortran: `nf-config --fflags --flibs` must work
- C preprocessor: `cpp`

#### Build steps

```bash
cd source/repo/drivers/hrldas/

# Create or edit user_build_options
# Set COMPILERF90, NETCDFMOD, NETCDFLIB

# Build (order matters: utility -> src -> driver)
cd ../../utility && make
cd ../src && make
cd ../drivers/hrldas && make
```

The binary will be created in `drivers/hrldas/` (name depends on Makefile target).

#### Common build errors

| Error | Cause | Fix |
|-------|-------|-----|
| `netcdf.mod not found` | NetCDF-Fortran not in include path | Add `-I$(nf-config --includedir)` to NETCDFMOD |
| `undefined reference to nf90_*` | NetCDF-Fortran not linked | Add `$(nf-config --flibs)` to NETCDFLIB |
| `user_build_options: No such file` | Missing config | Copy template or create from scratch |
| Dependency errors | Wrong build order | Clean all, rebuild utility → src → driver |

### 2. Setup run directory

```
run_dir/
├── namelist.hrldas          # Configuration
├── NoahmpTable.TBL          # Parameter table (copy from parameters/)
├── wrfinput_d01              # HRLDAS setup file (or symlink)
├── forcing/                  # LDASIN files (or set indir path)
│   ├── 2010010100.LDASIN_DOMAIN1
│   ├── 2010010101.LDASIN_DOMAIN1
│   └── ...
└── output/                   # Will be created (outdir)
```

**Critical**: `NoahmpTable.TBL` must be in the run directory (or CWD of binary).

### 3. Preflight checklist

- [ ] Binary exists and is executable
- [ ] `namelist.hrldas` exists in run directory
- [ ] `hrldas_setup_file` path resolves from run directory
- [ ] `indir` contains LDASIN files covering the simulation period
- [ ] `NoahmpTable.TBL` is present
- [ ] `outdir` exists (create if needed)
- [ ] Timestep consistency: forcing_timestep % noah_timestep == 0

### 4. Execute

```bash
cd run_dir/
./path/to/noahmp_binary

# Or using the wrapper:
python ki/tools/run_noahmp.py \
  --source_dir ./source/ \
  --run_dir ./run/ \
  --namelist ./run/namelist.hrldas
```

### 5. Runtime expectations

| Domain size | Period | Timestep | Approximate runtime |
|------------|--------|----------|-------------------|
| 1×1 (point) | 1 year | 3600s | < 1 second |
| 1×1 (point) | 10 years | 3600s | < 5 seconds |
| 100×100 | 1 year | 3600s | ~5-30 minutes |
| 500×500 | 1 year | 3600s | ~2-6 hours |

### 6. Post-execution checks

- Output files in `outdir/` matching expected count
- First and last LDASOUT files are non-empty
- No NaN values in key variables (TSK, SMOIS)
- Energy balance: |HFX + LH + GRDFLX - (SWDOWN - SWUP + LWDOWN - LWUP)| < 5 W/m²

## Verification

- [ ] Binary compiled successfully (exit code 0)
- [ ] Model completed without runtime errors
- [ ] LDASOUT files written for full simulation period
- [ ] Output variables have physically reasonable values
- [ ] Restart file written (if restart_frequency_hours > 0)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dt_008 | Wrong parameters used | MMINLU in setup file doesn't match NoahmpTable.TBL section |
| dt_014 | Crash at first timestep | Missing or corrupt LDASIN files |
| dt_015 | Crash mid-simulation | Gap in LDASIN file sequence |
| dt_016 | NaN propagation | Forcing data out of physical range |
| dt_009 | Subtle timing errors | Timestep not evenly divisible |

## Example

Full execution sequence for a 1-year point simulation:

```bash
# 1. Compile
cd source/repo/
cd utility && make && cd ../src && make && cd ../drivers/hrldas && make

# 2. Setup run directory
mkdir -p run/output
cp parameters/NoahmpTable.TBL run/
cp namelist.hrldas run/
ln -s $(pwd)/forcing run/forcing

# 3. Run
cd run/
../source/repo/drivers/hrldas/hrldas.exe

# 4. Check output
ls output/*.LDASOUT_DOMAIN1 | wc -l   # Should be ~365 for daily output
ncdump -h output/201001010000.LDASOUT_DOMAIN1 | head -20
```
