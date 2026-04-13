# Stage 4: Model Compilation and Execution

## Purpose

Compile and run the CLASSIC model binary. CLASSIC is a Fortran model compiled with gfortran (serial) or mpif90 (parallel), linked against the netCDF-Fortran library.

## Inputs

| Input | Description |
|-------|-------------|
| Source code | `src/*.f90`, `src/*.F90` |
| Makefile | Root `Makefile` |
| Job options file | Configured in Stage 3 |
| All input netCDF files | Met, init, GHG, optional fire/LUC |

## Outputs

| Output | Path |
|--------|------|
| Binary | `bin/CLASSIC_serial` or `bin/CLASSIC_parallel` |
| NetCDF outputs | `outputFiles/*.nc` |
| Restart file | `rs_file_to_overwrite` (overwritten in place) |

## Procedure

### 1. Install dependencies

```bash
# Ubuntu/Debian
sudo apt install gfortran make libnetcdff-dev netcdf-bin zlib1g-dev

# Verify
gfortran --version
nf-config --all
```

### 2. Compile

```bash
cd /path/to/classic
make clean mode=serial    # Clean previous build
make mode=serial          # Compile serial binary
ls -la bin/CLASSIC_serial # Verify binary exists
```

**Compilation flags (serial)**:
- `-O3` optimization
- `-fdefault-real-8` (all reals are 8-byte / double precision)
- `-ffree-line-length-none` (no line length limit)
- `-fbacktrace` (stack trace on crash)
- `-ffpe-trap=invalid,zero,overflow` (trap floating-point exceptions)
- `-fbounds-check` (array bounds checking)

### 3. Pre-flight checks

```bash
# Verify binary runs
bin/CLASSIC_serial
# Should print usage message

# Verify input files exist
python ki/tools/run_classic.py \
    --source_dir . \
    --job_options my_job_options.txt \
    --coords "0/0" \
    --skip_compile
```

### 4. Execute

**Point simulation:**
```bash
bin/CLASSIC_serial my_job_options.txt lon/lat
# Example:
bin/CLASSIC_serial configurationFiles/template_job_options_file.txt 105.23/40.91
```

**Grid simulation (parallel):**
```bash
make mode=parallel
mpirun -np 4 bin/CLASSIC_parallel my_job_options.txt Wlon/Elon/Slat/Nlat
```

### 5. Monitor execution

- CLASSIC prints progress to stdout
- Check for error messages in stderr
- Runtime varies: seconds (point, 1 year) to hours (global, decades)

## Verification

```bash
# Check output directory
ls -la outputFiles/*.nc

# Quick check of an output file
ncdump -h outputFiles/gpp_mo.nc

# Verify physically reasonable values
python -c "
import netCDF4 as nc
ds = nc.Dataset('outputFiles/gpp_mo.nc')
for v in ds.variables:
    if v not in ['lat','lon','time']:
        d = ds.variables[v][:]
        print(f'{v}: min={d.min():.4f}, max={d.max():.4f}')
ds.close()
"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Missing libnetcdff.so | Linker error: cannot find -lnetcdff | Install libnetcdff-dev |
| Wrong netCDF version | Compile error in fileIOModule | Ensure netCDF-4 (HDF5-based) |
| Segfault on start | Array bounds violation (often dimension mismatch) | Check ican/icc match between params and init file |
| "ZRFM < vegetation height" crash | Reference height too low | Increase ZRFM in job options |
| NaN in output | Usually bad forcing data (negative SW, wrong units) | Check forcing files |
| Infinite loop / no progress | Time encoding mismatch in met files | Verify met time is "day as %Y%m%d.%f" |
| "No valid gridcells" | Coordinates don't match any grid cell in init file | Check lon/lat match init file grid |
| Output files empty | Wrong output year range settings | Set JMOSTY within simulation period |

## Example

```bash
# Full workflow
cd /path/to/classic
make mode=serial
cp init_file.nc rsFile.nc
bin/CLASSIC_serial my_job_options.txt 0/0
ls outputFiles/*.nc
```
