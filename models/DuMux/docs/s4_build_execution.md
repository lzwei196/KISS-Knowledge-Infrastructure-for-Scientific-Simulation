# Stage 4: Building and Running DuMux

## Purpose

Compile the DuMux simulation executable and run the groundwater simulation with the prepared parameter file. This stage handles the CMake/Make build system, binary execution, and runtime monitoring.

## Inputs

| Input | Format | Source |
|-------|--------|--------|
| DuMux source code | C++ headers + CMakeLists.txt | github.com/dumux/dumux |
| DUNE modules | Installed libraries | dune-project.org |
| Parameter file | `.input` (INI format) | Stages 1–3 |
| Problem/SpatialParams sources | `.hh` C++ headers | User or example |

## Outputs

| Output | Format | Consumed by |
|--------|--------|-------------|
| Compiled binary | executable | This stage (run) |
| VTK output files | `.vtu`, `.pvd` | Stage 5 (parsing) |
| Terminal output | text (Newton info) | Monitoring |
| Restart files (optional) | binary | Continuation runs |

## Procedure

### Step 1: Install DUNE dependencies

```bash
# Option A: DuMux install script
cd dumux
./bin/installexternal.py dul

# Option B: Manual DUNE module installation
for module in dune-common dune-geometry dune-grid dune-localfunctions dune-istl; do
    git clone https://gitlab.dune-project.org/core/${module}.git
done

# Option C: Package manager (Debian/Ubuntu)
apt install libdune-common-dev libdune-geometry-dev libdune-grid-dev \
            libdune-localfunctions-dev libdune-istl-dev
```

### Step 2: Configure with CMake

```bash
mkdir -p build && cd build
cmake /path/to/dumux/source \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_FLAGS="-O3 -march=native -funroll-loops" \
    -DDUNE_CHECK_BOUNDS=OFF
```

**Important CMake options**:
| Option | Default | Description |
|--------|---------|-------------|
| `CMAKE_BUILD_TYPE` | Debug | Release for production, Debug for development |
| `DCMAKE_CXX_FLAGS` | - | Compiler optimization flags |
| `DDUNE_CHECK_BOUNDS` | ON | Array bounds checking (slow in Debug) |
| `DDUMUX_ENABLE_PYTHONBINDINGS` | OFF | Python interface (requires shared libs) |
| `DBUILD_SHARED_LIBS` | OFF | Required for Python bindings |

### Step 3: Build a specific target

```bash
# Build a specific example
make -j$(nproc) example_1ptracer

# Build all tests for 1p model
cmake --build . --target build_1p_tests -- -j$(nproc)

# Build everything (slow — thousands of targets)
make -j$(nproc)
```

### Step 4: Run the simulation

```bash
# Basic run
./example_1ptracer params.input

# Override parameters on command line
./example_1ptracer params.input \
    -Problem.Name my_run \
    -TimeLoop.TEnd 86400 \
    -SpatialParams.Permeability 1e-11

# Run with MPI (parallel)
mpirun -np 4 ./example_1ptracer params.input
```

### Step 5: Monitor execution

DuMux prints Newton solver progress to stdout:
```
 -- Newton iteration 1 (residual norm = 1.234e+05)
 -- Newton iteration 2 (residual norm = 4.567e+02)
 -- Newton iteration 3 (residual norm = 8.901e-03)
 -- Newton converged after 3 iterations

 Time step 1 done: dt = 100.0, t = 100.0
```

**Watch for**:
- **Residual not decreasing**: Linear solver may be struggling
- **Many iterations (>15)**: Time step may be too large
- **"Convergence failed, reducing dt"**: Newton didn't converge, trying smaller step
- **dt shrinking to near-zero**: Simulation is stuck — check parameters

### Step 6: Verify output files

```bash
ls -la *.vtu *.pvd
# Should see: problem_name-00000.vtu, problem_name-00001.vtu, ...
# And: problem_name.pvd (index file for ParaView)
```

## Verification

1. **Binary exists and is executable**: `ls -l ./example_1ptracer`
2. **Return code is 0**: Non-zero means failure
3. **VTK files created**: At least one `.vtu` file in the working directory
4. **Output file size > 0**: Empty VTK files indicate no data was written
5. **Newton converged**: Check terminal output for "Newton converged"
6. **Simulation reached TEnd**: Final "t = ..." should match TimeLoop.TEnd

## Traps

### TRAP: CMake can't find DUNE modules
If DUNE modules are not in standard paths, CMake fails with `Could NOT find dune-common`.

**Fix**: Set `CMAKE_PREFIX_PATH` to DUNE installation:
```bash
cmake .. -DCMAKE_PREFIX_PATH="/path/to/dune-install"
```

### TRAP: C++20 compiler required
DuMux 3.x requires C++20 features. GCC < 11 or Clang < 14 will fail with template errors.

**Detection**: Errors about `std::ranges`, `concepts`, or template parameter packs.
**Fix**: Use GCC >= 11 or Clang >= 14.

### TRAP: Missing parameter crashes at runtime
If a required parameter is not in the `.input` file and has no default, DuMux throws `ParameterException`.

**Detection**: Error message includes "Key 'Section.Key' not found in the parameter tree."
**Fix**: Add the missing key to the `.input` file.

### TRAP: Build target name mismatch
The `make` target name is defined in `CMakeLists.txt` and may differ from the directory name. Check with:
```bash
grep -r "add_executable" CMakeLists.txt
```

### TRAP: Newton solver diverges with extreme parameters
If permeability or pressure BCs are physically unreasonable, the Newton solver may diverge immediately.

**Detection**: "Newton: convergence failed" on the first time step.
**Fix**: Check parameter values and units. Start with a steady-state test.

### TRAP: Time step too large for transient problems
A large initial time step can cause Newton failure. DuMux will reduce dt, but if `DtInitial` is absurdly large, the solver may waste hours reducing.

**Fix**: Set `DtInitial` to ~1% of `TEnd` as a starting point. Reduce further if Newton needs > 10 iterations.

## Example

```bash
# Full build-and-run workflow
cd /path/to/dumux

# Build
mkdir -p build && cd build
cmake ../source/repo -DCMAKE_BUILD_TYPE=Release
make -j4 example_1ptracer

# Run
cd examples/1ptracer
./example_1ptracer params.input -Problem.Name groundwater_test

# Verify
ls groundwater_test*.vtu
```

**Tool**:
```bash
python tools/run_dumux.py \
    --source_dir /path/to/dumux/source/repo \
    --build_dir /path/to/build \
    --target example_1ptracer \
    --params params.input \
    --overrides "Problem.Name=test TimeLoop.TEnd=5000"
```
