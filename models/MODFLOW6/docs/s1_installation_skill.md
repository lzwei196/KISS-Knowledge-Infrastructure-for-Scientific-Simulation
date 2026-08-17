# Installation & Environment Setup — Skill Document

> **Stage ID**: s1_installation
> **Pipeline order**: 1 of 9
> **Depends on**: none

## Purpose

Install and verify the MODFLOW 6 binary (`mf6`) and the FloPy Python package. Without these, no groundwater simulation can be built or executed. MODFLOW 6 is a standalone Fortran executable; FloPy is the Python interface that generates its input files and reads its output files.

## Prerequisites

Before starting this stage, verify:

- [ ] Python 3.8+ is available (preferably the HydroCraft venv)
- [ ] Internet access for downloading binaries or pip packages (first-time only)
- [ ] Write access to a directory for the mf6 binary

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| python_env | directory | HydroCraft config | Python environment path (`KISSPATH_PYTHON_ENV/`) |

## Procedure

### Step 1: Install FloPy

```bash
source KISSPATH_PYTHON_ENV/bin/activate
pip install flopy
```

Verify:
```bash
python -c "import flopy; print(f'FloPy {flopy.__version__}')"
```

**Expected result**: FloPy version >= 3.4.0 printed.

**If this fails**: Check pip is from the correct venv. See diagnostic triplet dt_mf6_007.

### Step 2: Obtain MODFLOW 6 Binary

**Option A — Pre-built binary (recommended):**

Download from USGS GitHub releases:
```bash
python -c "
import flopy.utils
flopy.utils.get_modflow(bindir='KISSPATH_KI_ROOT/MODFLOW6/bin/')
"
```

This downloads the latest mf6 binary for your platform.

**Option B — Compile from source:**

Requires gfortran and meson:
```bash
git clone https://github.com/MODFLOW-ORG/modflow6.git
cd modflow6
meson setup builddir --prefix=$(pwd)/install
meson compile -C builddir
meson install -C builddir
```

The binary will be at `install/bin/mf6`.

### Step 3: Verify mf6 Binary

```bash
KISSPATH_KI_ROOT/MODFLOW6/bin/mf6 --version
```

**Expected result**: Version string like `mf6: 6.5.0 Release 12/01/2023`

**If this fails**: Check executable permissions (`chmod +x mf6`). On Linux, verify glibc compatibility. See dt_mf6_007.

### Step 4: Run Verification Tool

```bash
python tools/s1/verify_mf6_installation.py
```

**Expected result**: JSON output with `status: "ok"`, `mf6_version`, `flopy_version`.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| mf6 binary | `models/MODFLOW6/bin/mf6` | Executable, returns version string |
| FloPy package | Python site-packages | `import flopy` succeeds |

## Validation Checks

1. **FloPy import**: `python -c "import flopy"` exits with code 0
   - Expected: No error
   - If unexpected: See dt_mf6_007

2. **mf6 runs**: `mf6 --version` returns version string
   - Expected: Version >= 6.4.0
   - If unexpected: Check PATH, executable permissions, glibc version

3. **FloPy finds mf6**: `python -c "import flopy; print(flopy.which('mf6'))"`
   - Expected: Returns path to mf6 binary
   - If unexpected: Add mf6 directory to PATH or pass explicit path to `sim.run_simulation(exe_name=...)`

## Common Pitfalls

> **PITFALL**: FloPy version incompatibility with MODFLOW 6 version
> Older FloPy versions may not support newer MODFLOW 6 packages (e.g., CSUB, PRT). Always use FloPy >= 3.4.0 with MODFLOW 6 >= 6.4.0.
> **Do this instead**: `pip install --upgrade flopy`
> See diagnostic triplet dt_mf6_007.

> **PITFALL**: mf6 binary not on PATH
> FloPy's `sim.run_simulation()` searches PATH for `mf6`. If the binary is in a custom location, the run will fail with "mf6 not found".
> **Do this instead**: Pass the full path: `sim.run_simulation(exe_name="/path/to/mf6")`

---

*This skill document is part of the modflow6-knowledge-infrastructure package.*
*Stage 1 of 9 | Tools used: verify_mf6_installation | Related triplets: dt_mf6_007*
