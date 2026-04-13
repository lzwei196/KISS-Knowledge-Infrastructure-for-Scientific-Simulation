# Stage 0: Environment Configuration and Installation

## Purpose

Set up the computing environment required to build and run ELM. This includes
installing compilers, libraries, and the E3SM/CIME infrastructure. ELM requires
a full HPC software stack — it cannot run as a standalone binary.

## Prerequisites

- Access to a supported HPC machine, OR a Linux workstation with:
  - MPI implementation (mpich or openmpi)
  - Fortran 2003+ compiler (gfortran 9+, Intel ifort 19+, or NVHPC)
  - CMake 3.18+
  - NetCDF-Fortran with HDF5
  - Python 3.7+
- Git (for cloning and submodule initialization)
- ~20 GB disk space for source + input data

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| E3SM source code | GitHub | `git clone --recursive https://github.com/E3SM-Project/E3SM` |
| Input data | CESM inputdata server | Downloaded automatically by CIME on first run |
| Machine configuration | `cime_config/machines/` | XML files defining machine-specific settings |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| E3SM source tree | User-specified | Complete source with submodules |
| Compiler verification | stdout | Successful compiler detection |
| Machine configuration | `config_machines.xml` | Validated machine entry |

## Procedure

### 1. Clone E3SM with submodules

```bash
git clone --recursive https://github.com/E3SM-Project/E3SM.git
cd E3SM

# If submodules are missing:
git submodule update --init --recursive --depth=1
```

### 2. Verify CIME is available

```bash
cd cime/scripts
./query_config --machines
```

This should list supported machines. If your machine is listed, you can proceed
directly to case creation (Stage 3).

### 3. For unsupported machines

Create a custom machine configuration in `cime_config/machines/`:
- Add entry to `config_machines.xml` with compiler paths, MPI config
- Add CMake macros in `cmake_macros/`
- Add batch system config if applicable

### 4. Verify compiler toolchain

```bash
which mpifort || which mpif90
mpifort --version
which cmake
cmake --version
nc-config --all    # NetCDF configuration
nf-config --all    # NetCDF-Fortran configuration
```

### 5. Install Python KI tools

```bash
pip install numpy pandas netCDF4 xarray matplotlib pyyaml
```

## Verification

- [ ] `git submodule status` shows all submodules initialized (no `-` prefix)
- [ ] `./query_config --machines` lists your machine
- [ ] `mpifort --version` returns a Fortran 2003+ compiler
- [ ] `nc-config --version` returns NetCDF 4.x
- [ ] `python3 -c "import netCDF4; print(netCDF4.__version__)"` succeeds

## Traps

| Trap | dt_ID | Description |
|------|-------|-------------|
| Missing submodules | — | `git submodule update --init --recursive` must complete fully |
| Wrong NetCDF build | dt_017 | NetCDF must be built with the same compiler used for ELM |
| Python 2 vs 3 | — | CIME requires Python 3.7+; older machines may default to Python 2 |

## Example

```bash
# On NERSC Perlmutter:
git clone --recursive https://github.com/E3SM-Project/E3SM.git
cd E3SM/cime/scripts
./query_config --machines | grep -i perlmutter
# Output: pm-cpu, pm-gpu
```
