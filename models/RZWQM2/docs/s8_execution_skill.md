# Skill Document: Model Execution (S8)

**Stage:** s8_execution
**Pipeline Order:** 8
**Depends On:** s7_scenario_assembly (complete, validated scenario directory)
**Tool:** `run_rzwqm2`

---

## Purpose

Execute the RZWQM2 binary to run the simulation. RZWQM2 is a compiled Fortran program that reads `ipnames.dat` from the current working directory and processes all input files to simulate soil water movement, nutrient cycling, crop growth, and pesticide fate over the specified simulation period. The binary must be run from within the scenario directory (or with the working directory set to the scenario directory), as it expects `ipnames.dat` to be in the current working directory.

The execution environment depends on the platform: native Windows executable, Linux binary compiled for x86-64 with AVX2 instruction set, or Docker container for cross-platform execution. ARM-based Macs (Apple Silicon) cannot run the binary natively or through Rosetta 2 emulation due to AVX2 requirements.

---

## Prerequisites

1. A complete, validated scenario directory (S7 complete):
   - `ipnames.dat` with all correct paths and simulation dates
   - All referenced input files exist and are readable
2. The RZWQM2 binary is available for the target platform.
3. Platform-specific requirements are met (see Platform Details below).

---

## Inputs

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `scenario_dir` | string (directory) | Scenario directory containing `ipnames.dat` | `/projects/534/` |
| `binary_path` | string (file) | Path to RZWQM2 executable | `./main_ryzen` |
| `platform` | string | Execution platform: `windows`, `linux`, `docker` | `docker` |

---

## Procedure

### Platform 1: Windows (Native)

The Windows binary is `RZWQMrelease.exe`. It reads `ipnames.dat` from the current working directory.

```batch
cd C:\RZWQM2\projects\534\
C:\RZWQM2\bin\RZWQMrelease.exe
```

Or equivalently:
```python
import subprocess
import os

os.chdir(scenario_dir)
subprocess.run([binary_path], check=True)
```

### Platform 2: Linux (Native x86-64)

The Linux binary is `main_ryzen`, compiled for ComputeCanada clusters targeting the x86-64-v3 microarchitecture (requires AVX2 instruction set support).

#### Step 2a: Fix the ELF Interpreter (One-Time Setup)

The binary may be compiled with a non-standard interpreter path. Use `patchelf` to set the correct dynamic linker:

```bash
patchelf --set-interpreter /lib64/ld-linux-x86-64.so.2 ./main_ryzen
```

This only needs to be done once. Without this fix, the binary will fail with "No such file or directory" even though the file exists (the error refers to the ELF interpreter, not the binary itself).

#### Step 2b: Run the Binary

```bash
cd /projects/534/
/path/to/main_ryzen
```

Or:
```python
import subprocess
import os

os.chdir(scenario_dir)
subprocess.run([binary_path], check=True)
```

### Platform 3: Docker (Cross-Platform, Recommended for Linux Binaries on Mac)

For running the Linux binary on systems without native x86-64 support, use Docker with platform emulation:

```bash
docker run --platform linux/amd64 \
    -v $(pwd):/workspace \
    -w /workspace/534 \
    ubuntu:22.04 \
    ./main_ryzen
```

Breakdown:
- `--platform linux/amd64`: Forces x86-64 emulation (via QEMU on ARM hosts)
- `-v $(pwd):/workspace`: Mounts the project directory into the container
- `-w /workspace/534`: Sets the working directory to the scenario directory
- `ubuntu:22.04`: Base image (provides libc and other dependencies)
- `./main_ryzen`: The binary to execute (must be accessible in the mounted volume)

**Important:** On ARM Macs (M1/M2/M3/M4), Docker's QEMU emulation of x86-64 does NOT support AVX2 instructions. The binary will segfault. You must use native x86-64 hardware.

### Platform 4: ComputeCanada / SLURM Clusters

For HPC execution on ComputeCanada:

```bash
#!/bin/bash
#SBATCH --job-name=rzwqm2
#SBATCH --time=01:00:00
#SBATCH --mem=4G
#SBATCH --cpus-per-task=1

cd /scratch/$USER/projects/534/
./main_ryzen
```

### Step 3: Monitor Execution

During execution, RZWQM2 writes progress messages to stdout. Look for:

- `Reading...` messages: Indicates input files are being parsed successfully.
- `Computing day...` or year progress: Indicates the simulation is advancing.
- Error messages: Fortran runtime errors indicate input file problems.

A typical simulation for 10 years of daily data completes in 1-30 minutes depending on the number of soil nodes and complexity of the configuration.

### Step 4: Verify Outputs

After execution completes, check for the existence of output files:

```python
import os

ana_path = os.path.join(project_path, 'Analysis', station_id + '.ana')
layer_path = os.path.join(project_path, station_id, 'Layer.plt')

assert os.path.exists(ana_path), f".ana output not found at {ana_path}"
print(f".ana file size: {os.path.getsize(ana_path)} bytes")

# Check for Layer.plt (optional, depends on output settings)
if os.path.exists(layer_path):
    print(f"Layer.plt size: {os.path.getsize(layer_path)} bytes")
```

---

## Expected Outputs

| File | Location | Description |
|------|----------|-------------|
| `.ana` | `{project_path}/Analysis/{station_id}.ana` | Daily output with ~100 columns of water balance, nutrient, and crop variables |
| `Layer.plt` | `{project_path}/{station_id}/Layer.plt` | Depth-resolved output (soil temperature, moisture by node) |
| Various `.OUT` files | `{project_path}/{station_id}/` | Additional output files depending on cntrl.dat settings |

---

## Validation Checks

1. **Binary exists and is executable:** `os.access(binary_path, os.X_OK)` returns True.
2. **ipnames.dat is in the working directory** when the binary starts.
3. **Exit code is 0:** The subprocess returns without error.
4. **No segfault:** Exit code is not -11 (SIGSEGV) or 139.
5. **.ana file is created** and has non-zero size.
6. **.ana file has data rows:** More than 23 header lines plus at least one data row.
7. **Runtime is reasonable:** A 10-year simulation should not take more than 1 hour on modern hardware (unless the profile has > 200 nodes).

---

## Common Pitfalls

### PITFALL 1: Binary Requires AVX2 -- Will Not Work Under ARM Emulation (FATAL)
**Severity:** Fatal -- segmentation fault.
**Symptom:** The binary starts but immediately crashes with `SIGSEGV` (segfault), `Illegal instruction`, or Docker QEMU reports `qemu: uncaught target signal 4 (Illegal instruction)`.
**Cause:** The `main_ryzen` binary is compiled with AVX2 instructions (x86-64-v3 microarchitecture level). ARM processors (Apple Silicon M1/M2/M3/M4) cannot execute AVX2 even through Rosetta 2 or Docker's QEMU emulation layer. QEMU's user-mode emulation does not implement AVX2.
**Fix:** Run the binary on native x86-64 hardware:
- Use a ComputeCanada cluster (Cedar, Graham, Narval -- all have modern x86-64 CPUs with AVX2).
- Use a cloud VM with x86-64 architecture (AWS EC2, GCP, Azure).
- Use a physical x86-64 Linux or Windows machine.
- If the Fortran source code is available, recompile without AVX2 (`-march=x86-64` instead of `-march=x86-64-v3`).

### PITFALL 2: File with Spaces in Name (MET FILE) -- Shell Quoting Issues
**Severity:** Moderate -- may cause "file not found" if paths are not properly quoted.
**Symptom:** The model cannot find the .met file even though it exists.
**Cause:** Some station names or file names contain spaces. In shell commands and scripts, unquoted paths with spaces are interpreted as multiple arguments.
**Fix:** Always quote file paths in shell commands:
```bash
cd "/projects/Station 534/"
```
In `ipnames.dat`, the paths should NOT be quoted -- RZWQM2's Fortran parser reads entire lines as paths and handles spaces internally. This works because each path is on its own line.

### PITFALL 3: ELF Interpreter Not Found on Linux (FATAL)
**Severity:** Fatal -- "No such file or directory" error even though the binary exists.
**Symptom:** Running `./main_ryzen` returns `bash: ./main_ryzen: No such file or directory` despite the file being present and executable.
**Cause:** The binary was compiled with a non-standard dynamic linker path (e.g., `/cvmfs/soft.computecanada.ca/nix/store/.../ld-linux-x86-64.so.2` on ComputeCanada).
**Fix:** Use patchelf to set the standard interpreter:
```bash
patchelf --set-interpreter /lib64/ld-linux-x86-64.so.2 ./main_ryzen
```
Install patchelf if not available: `apt-get install patchelf` (Ubuntu/Debian).

### PITFALL 4: Working Directory Not Set to Scenario Directory
**Severity:** Fatal -- model cannot find ipnames.dat.
**Symptom:** Model reports "cannot open ipnames.dat" or similar error.
**Cause:** The RZWQM2 binary reads `ipnames.dat` from the current working directory (CWD). If the binary is run from a different directory, it cannot find the file.
**Fix:** Always `cd` into the scenario directory before running the binary, or use `subprocess.run` with the `cwd` parameter:
```python
subprocess.run([binary_path], cwd=scenario_dir, check=True)
```

### PITFALL 5: Insufficient Memory or Stack Size
**Severity:** Fatal on large profiles or long simulations.
**Symptom:** Segfault or "stack overflow" during execution.
**Cause:** Very deep soil profiles with many nodes (> 200) or very long simulation periods (> 50 years) may exceed the default stack size.
**Fix:** Increase the stack size limit before running:
```bash
ulimit -s unlimited  # Linux/Mac
./main_ryzen
```
