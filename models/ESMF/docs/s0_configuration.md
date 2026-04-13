# Stage 0: Configuration

## Purpose

Set up the ESMF build and runtime environment. This stage configures compiler
selection, MPI library, NetCDF paths, optimization level, and installation
directories. Correct configuration is essential — wrong settings cause build
failures or silent runtime errors.

## Inputs

| Input                  | Source                          | Required |
|------------------------|---------------------------------|----------|
| ESMF source directory  | GitHub clone or release tarball | Yes      |
| Fortran compiler       | System installation             | Yes      |
| C/C++ compiler         | System installation             | Yes      |
| MPI library            | System installation             | Yes*     |
| NetCDF-C library       | System or conda                 | Recommended |
| NetCDF-Fortran library | System or conda                 | Recommended |

*`ESMF_COMM=mpiuni` allows serial builds without MPI.

## Outputs

| Output                  | Description                              |
|-------------------------|------------------------------------------|
| Environment variables   | ESMF_DIR, ESMF_COMPILER, ESMF_COMM, etc. |
| Build configuration     | Validated compiler/library paths         |
| esmf.mk                 | Makefile fragment for dependent builds   |

## Procedure

1. **Clone or download ESMF source**:
   ```bash
   git clone https://github.com/esmf-org/esmf.git
   cd esmf
   ```

2. **Set required environment variables**:
   ```bash
   export ESMF_DIR=$(pwd)
   export ESMF_COMPILER=gfortran
   export ESMF_COMM=openmpi
   export ESMF_BOPT=O
   ```

3. **Set optional NetCDF paths** (if not auto-detected):
   ```bash
   export ESMF_NETCDF=split
   export ESMF_NETCDF_INCLUDE=$(nc-config --includedir)
   export ESMF_NETCDF_LIBPATH=$(nc-config --libdir)
   ```

4. **Verify compiler availability**:
   ```bash
   gfortran --version
   gcc --version
   mpirun --version
   nc-config --all
   ```

5. **Test configuration**:
   ```bash
   make info 2>&1 | head -30
   ```

## Verification

- `make info` completes without error
- All required compilers found in PATH
- NetCDF include/lib directories exist (if specified)
- `ESMF_DIR/makefile` exists
- `ESMF_DIR/src/` directory exists

## Traps

| Trap | Description | Severity |
|------|-------------|----------|
| Wrong ESMF_DIR | Points to install prefix instead of source root | fatal |
| ESMF_COMM mismatch | Built with mpiuni but running with mpirun | fatal |
| Missing NetCDF-Fortran | ESMF_NETCDF=split but only NetCDF-C installed | fatal |
| GNU make required | Standard Unix make will fail; need `gmake` or GNU `make` | fatal |
| Compiler version mismatch | Built with gfortran-11 but linking with gfortran-12 objects | fatal |

## Example

```bash
# Minimal serial configuration (no MPI needed)
export ESMF_DIR=/opt/esmf
export ESMF_COMPILER=gfortran
export ESMF_COMM=mpiuni
export ESMF_BOPT=g    # debug mode
make info
make -j4 lib
```
