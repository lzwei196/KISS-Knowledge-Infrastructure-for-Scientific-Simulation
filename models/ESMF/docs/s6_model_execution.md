# Stage 6: Model Execution

## Purpose

Build the ESMF library from source and execute ESMF-based applications.
This stage handles compilation, MPI configuration, runtime environment,
and execution monitoring. It covers both building ESMF itself and compiling
user applications that link against ESMF.

## Inputs

| Input                  | Source              | Required |
|------------------------|---------------------|----------|
| ESMF source code       | Stage s0_config     | Yes      |
| Environment variables  | Stage s0_config     | Yes      |
| Application source     | User code           | Yes (if compiling) |
| Grid files             | Stage s1_domain     | Yes      |
| Forcing data           | Stage s4_forcing    | Yes      |
| Config/namelist files  | Stage s5_parameters | Yes      |

## Outputs

| Output                 | Format       | Description                          |
|------------------------|--------------|--------------------------------------|
| ESMF library           | .a / .so     | Compiled ESMF library                |
| esmf.mk               | Makefile     | Build fragment for dependent codes   |
| Application binary     | ELF          | Compiled user application            |
| PET log files          | Text         | Per-process ESMF log output          |
| Output data            | NetCDF       | Model simulation results             |

## Procedure

1. **Build ESMF library**:
   ```bash
   cd $ESMF_DIR
   make -j$(nproc) lib
   ```
   Build time: 10–30 minutes depending on system.

2. **Verify build**:
   ```bash
   make build_unit_tests
   make run_unit_tests_uni  # serial tests only
   ```

3. **Compile user application** (Fortran example):
   ```bash
   export ESMFMKFILE=$(find $ESMF_DIR/lib -name "esmf.mk" | head -1)
   include $(ESMFMKFILE)
   mpif90 -o my_model my_model.F90 $(ESMF_F90COMPILEPATHS) $(ESMF_F90LINKPATHS) $(ESMF_F90LINKRPATHS) $(ESMF_F90ESMFLINKLIBS)
   ```

4. **Run application**:
   ```bash
   # With MPI
   mpirun -np 4 ./my_model

   # Serial (if built with mpiuni)
   ./my_model

   # Using run wrapper
   python run_esmf_application.py \
       --esmf-dir $ESMF_DIR \
       --compiler gfortran \
       --comm openmpi \
       --app-binary ./my_model \
       --np 4
   ```

5. **Monitor execution**:
   - Check PET*.ESMF_LogFile for errors
   - Enable tracing: `export ESMF_RUNTIME_TRACE=ON`

## Verification

- `make lib` completes with return code 0
- `esmf.mk` file exists in lib/ directory
- Application binary is executable
- MPI processes launch correctly (`mpirun -np N` matches DELayout)
- PET log files show no ERRORs
- Output NetCDF files are created and non-empty

## Traps

| Trap | Description | Severity |
|------|-------------|----------|
| DELayout PET count mismatch | `-np` doesn't match regDecomp product | fatal |
| Double MPI_Init | Built with mpiuni but run with mpirun | fatal |
| Missing NetCDF at runtime | ESMF built without NetCDF but I/O attempted | fatal |
| Wrong library path | LD_LIBRARY_PATH doesn't include ESMF libs | fatal |
| Stagger mismatch | Field created at CENTER but used with CORNER data | fatal |
| Halo too narrow | Regrid stencil wider than halo → reads garbage memory | fatal |
| Timeout | Long simulation with no output → appears hung (but running) | operational |

## Example

```bash
# Complete build-and-run workflow
export ESMF_DIR=/home/user/esmf
export ESMF_COMPILER=gfortran
export ESMF_COMM=mpiuni
export ESMF_BOPT=g

# Build
cd $ESMF_DIR && make -j4 lib

# Run ESMF built-in system test
make build_system_tests
cd src/system_tests/ESMF_FieldRegrid/
mpirun -np 4 ./ESMF_FieldRegridSTest

# Check logs
grep -i error PET*.ESMF_LogFile
```
