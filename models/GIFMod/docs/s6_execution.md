# Stage 6: Model Execution

## Purpose

Build the GIFMod binary from source and execute simulations. GIFMod is a Qt5 GUI
application; headless execution requires a virtual framebuffer (xvfb) or the
built-in JavaScript scripting engine.

## Inputs

| Input              | Source          | Format          | Required |
|--------------------|-----------------|-----------------|----------|
| GIFMod source code | GitHub/USEPA    | C++ / Qt project| Yes      |
| Qt5 dev libraries  | System packages | Shared libs     | Yes      |
| LAPACK/BLAS        | System packages | Shared libs     | Yes      |
| Project file       | Previous stages | .GIFMod         | For run  |

## Outputs

| Output             | Format          | Location              |
|--------------------|-----------------|-----------------------|
| GIFMod binary      | Executable      | build/GIFMod          |
| Model output       | Text time series| Output directory      |
| Build log          | Text            | build/                |

## Procedure

### Building

1. **Install dependencies**:
   ```bash
   sudo apt-get install qt5-default qtbase5-dev liblapack-dev libblas-dev \
       libgomp1 build-essential
   ```

2. **Run qmake** to generate Makefile:
   ```bash
   cd /path/to/GIFMod/source/repo
   mkdir build && cd build
   qmake ../GIFMod.pro CONFIG+=release
   ```

3. **Compile** with make:
   ```bash
   make -j$(nproc)
   ```

4. **Verify binary** exists and is executable:
   ```bash
   ls -la build/GIFMod
   file build/GIFMod  # Should show ELF executable
   ```

### Running

5. **Headless execution** via xvfb:
   ```bash
   xvfb-run -a ./build/GIFMod project.GIFMod
   ```

6. **GUI execution** (interactive):
   ```bash
   ./build/GIFMod
   ```

7. **Scripted execution** via JavaScript engine:
   - GIFMod embeds Duktape for scripting
   - Scripts can automate model building, parameter setting, and simulation

## Verification

- [ ] Binary compiled without errors
- [ ] Binary is executable (`chmod +x` if needed)
- [ ] Qt libraries found at runtime (`ldd build/GIFMod`)
- [ ] LAPACK/BLAS libraries linked
- [ ] Output files created after run

## Traps

| ID     | Trap                            | Severity | Consequence                     |
|--------|---------------------------------|----------|---------------------------------|
| dt_014 | Qt version mismatch             | degraded | Build fails or GUI crashes      |
| dt_015 | LAPACK/BLAS not found           | fatal    | Linker error at build time      |
| --     | Missing OpenMP support          | degraded | Single-threaded, slow execution |
| --     | No xvfb for headless run        | fatal    | Cannot create QApplication      |
| --     | Insufficient memory for Jacobian| fatal    | OOM with large block networks   |

## Example

```bash
# Full build-and-run pipeline
python run_gifmod.py \
  --source-dir /path/to/GIFMod/source/repo \
  --mode build-and-run \
  --project /path/to/model.GIFMod \
  --timeout 3600
```

### Common Build Errors

| Error                          | Cause                    | Fix                           |
|--------------------------------|--------------------------|-------------------------------|
| `qmake: command not found`     | Qt5 not installed        | `apt install qtbase5-dev`     |
| `-llapack not found`           | LAPACK missing           | `apt install liblapack-dev`   |
| `QApplication: no display`     | Headless without xvfb    | `apt install xvfb`           |
| `undefined reference to dgemm` | BLAS missing             | `apt install libblas-dev`     |
| `c++14 not supported`          | Old compiler             | `apt install g++-7` or newer  |
