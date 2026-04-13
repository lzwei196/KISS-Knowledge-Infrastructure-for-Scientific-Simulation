# Skill Document: Scenario Assembly (S7)

**Stage:** s7_scenario_assembly
**Pipeline Order:** 7
**Depends On:** s2_met_prep, s3_brk_generation, s4_soil_setup, s5_node_discretization, s6_initial_conditions
**Tools:** `initialize_scenario`, `update_ipnames_paths`, `update_rzx_paths`

---

## Purpose

Assemble a complete, runnable RZWQM2 scenario by creating a scenario directory from a template, configuring `ipnames.dat` with correct file paths and simulation dates, and optionally configuring DSSAT crop model paths in `.RZX` files. The `ipnames.dat` file is the master control file that RZWQM2 reads first -- it contains the paths to all other input files and the simulation period. If any path in `ipnames.dat` is wrong, the model fails immediately. This stage is the final integration step before execution.

---

## Prerequisites

1. All input files have been created:
   - `RZWQM.dat` with site properties, soil properties, and node discretization (S1, S4, S5)
   - `.met` file with meteorological data (S2)
   - `.brk` file with breakpoint rainfall (S3)
   - `RZINIT.dat` with initial conditions (S6)
   - `cntrl.dat` (control file, typically from template)
   - `plgen.dat` (plant growth file, typically from template)
2. A template scenario directory exists containing baseline versions of all required files.
3. Python environment with access to `rzwqm_file.py`.

---

## Inputs

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `project_path` | string (directory) | RZWQM2 project root | `/Users/leo/Desktop/RZWQM2/projects/` |
| `template_name` | string | Name of template scenario subdirectory | `New Scenario` |
| `new_name` | string | Name for the new scenario | `534` |
| `start_date` | datetime or tuple | Simulation start date | `(datetime(2011,1,1), datetime(2021,12,31))` |
| `end_date` | datetime or tuple | Simulation end date | included in tuple above |
| `if_snow` | bool | Whether to copy .sno file from template | `True` |
| `if_met` | bool | Whether to create new .met and .brk paths | `False` (uses existing) |

---

## Procedure

### Step 1: Copy Template Scenario Directory

The `initialize_scneario_based_on_existing` function copies the template scenario to a new directory:

```python
from rzwqm_file import initialize_scneario_based_on_existing
from datetime import datetime

initialize_scneario_based_on_existing(
    original_instance_project_path=project_path,
    original_instance_name=template_name,
    name_of_new_instance=new_name,
    if_snow=True,
    operation_date=(datetime(2011, 1, 1), datetime(2021, 12, 31)),
    if_met=False
)
```

This function:
1. Copies the entire template directory using `shutil.copytree`.
2. If the destination already exists, it is **deleted first** (`shutil.rmtree`).
3. Updates `ipnames.dat` with the new paths (see Step 2).
4. If `if_snow=True`, copies the `.sno` file from `Meteorology/` with the new name.
5. If `if_met=True`, updates the `.met` and `.brk` paths in `ipnames.dat`.

### Step 2: Understand ipnames.dat Format

The `ipnames.dat` file has exactly 17+ lines. The critical lines are:

| Line # (0-indexed) | Content | Example |
|-----|---------|---------|
| 0 | Path to `cntrl.dat` | `/projects/534/cntrl.dat` |
| 1 | Path to `RZWQM.dat` | `/projects/534/rzwqm.dat` |
| 2 | Path to `.met` file | `/projects/Meteorology/534.met` |
| 3 | Path to `.brk` file | `/projects/Meteorology/534.brk` |
| 4 | Path to `RZINIT.dat` | `/projects/534/rzinit.dat` |
| 5 | Path to `plgen.dat` | `/projects/534/plgen.dat` |
| 6 | Path to `.sno` file | `/projects/Meteorology/534.sno` |
| 7 | Path to `.ana` output file | `/projects/Analysis/534.ana` |
| 8 | Simulation dates | `1 1 2011  31 12 2021` |
| 9-16 | Climate modification factors | `0` or `100` |

**Line 8 date format:** `DD MM YYYY DD MM YYYY` (start date then end date, space-separated). The `custom_date_format` function generates this: `"{day} {month} {year}"` (no zero-padding).

**Lines 9-16 (climate modification factors):**
- These modify the meteorological inputs. Each line corresponds to a variable.
- `0` means no change (additive: add 0).
- `100` means no change for percentage-based modifications (100% of original).
- These are typically left at their default values unless running climate sensitivity scenarios.

### Step 3: Update ipnames.dat Paths

The initialization function sets paths following this pattern:

```python
ip[0] = project_path + new_name + "//cntrl.dat"
ip[1] = project_path + new_name + "//rzwqm.dat"
ip[2] = project_path + "Meteorology//" + new_name + ".met"   # if if_met=True
ip[3] = project_path + "Meteorology//" + new_name + ".brk"   # if if_met=True
ip[4] = project_path + new_name + "//rzinit.dat"
ip[5] = project_path + new_name + "//plgen.dat"
ip[6] = project_path + "Meteorology//" + new_name + ".sno"   # if if_snow=True
ip[7] = project_path + "Analysis//" + new_name + ".ana"
ip[8] = "1 1 2011  31 12 2021"  # formatted dates
```

Note the double forward slashes (`//`) in the paths. These are valid on both Windows (where `//` is treated as `\`) and Linux/macOS.

### Step 4: Manually Update Paths If Needed

If the paths need to be updated after initial creation (e.g., moving to a different system), use the RZWQM class:

```python
from rzwqm_file import RZWQM

rz = RZWQM(project_path, station_id)
ip = rz.ipnames

# Modify specific lines
ip[0] = new_root + station_id + "/cntrl.dat"
ip[1] = new_root + station_id + "/rzwqm.dat"
# ... etc

# Write back
with open(rz.ipnames_path, 'w') as f:
    for line in ip:
        f.write(line + '\n')
```

### Step 5: Update RZX Paths (DSSAT Crop Model)

If using the DSSAT crop model integration (RZWQM2-DSSAT), the `.RZX` files in the scenario directory need their internal paths updated. These files contain absolute paths to the DSSAT database directory and the project directory.

This step is platform-specific and must be done when moving scenarios between machines:

```python
# Read the .RZX file
# Find lines containing the DSSAT database path and project path
# Replace with the correct paths for the current platform
```

The specific format depends on the DSSAT version integrated with RZWQM2.

### Step 6: Verify All Referenced Files Exist

Before running the model, validate that every file referenced in `ipnames.dat` actually exists:

```python
import os

rz = RZWQM(project_path, station_id)
ip = rz.ipnames

files_to_check = {
    'cntrl.dat': ip[0].strip(),
    'rzwqm.dat': ip[1].strip(),
    '.met file': ip[2].strip(),
    '.brk file': ip[3].strip(),
    'rzinit.dat': ip[4].strip(),
    'plgen.dat': ip[5].strip(),
    '.sno file': ip[6].strip(),
}

for name, path in files_to_check.items():
    # Normalize path separators
    path = path.replace('//', '/')
    if not os.path.exists(path):
        print(f"MISSING: {name} at {path}")
    else:
        print(f"OK: {name}")

# Line 7 (.ana) is an output file -- it doesn't need to exist yet,
# but its parent directory must exist
ana_dir = os.path.dirname(ip[7].strip().replace('//', '/'))
if not os.path.exists(ana_dir):
    print(f"MISSING: Analysis directory {ana_dir}")
```

---

## Expected Outputs

- **New directory:** `{project_path}/{new_name}/` containing:
  - `ipnames.dat` (with updated paths and simulation dates)
  - `cntrl.dat` (from template)
  - `RZWQM.dat` (from template, to be updated by S1/S4/S5)
  - `RZINIT.dat` (from template, to be updated by S6)
  - `plgen.dat` (from template)
  - Various `.RZX` files (if DSSAT integration is used)
- **Meteorology files:** `{project_path}/Meteorology/{new_name}.met`, `.brk`, `.sno`
- **Analysis directory:** `{project_path}/Analysis/` must exist for output files

---

## Validation Checks

1. **All 8 file paths in ipnames.dat point to existing files** (except line 7 which is the output path).
2. **Simulation dates on line 8 are valid** and match the .met file date range.
3. **Date format is correct:** `DD MM YYYY DD MM YYYY` (day first, then month, then year).
4. **Start date is before end date.**
5. **Start date falls within the .met file date range.**
6. **Climate modification factors (lines 9-16) are reasonable:** typically 0 for additive or 100 for multiplicative.
7. **All input files use consistent horizon counts** (RZWQM.dat and RZINIT.dat).
8. **File paths use appropriate separators for the platform.**

---

## Common Pitfalls

### PITFALL 1: Windows Backslashes vs Linux Forward Slashes (FATAL ON WRONG PLATFORM)
**Severity:** Fatal -- file not found.
**Symptom:** Model reports "cannot open file" for an input file.
**Cause:** `ipnames.dat` contains Windows-style backslashes (`\`) when running on Linux, or vice versa. The RZWQM2 Fortran binary on Linux expects forward slashes; on Windows it accepts both.
**Fix:** When moving scenarios between platforms, update all paths in `ipnames.dat` to use the correct separator. On Linux, use forward slashes (`/`). On Windows, either works but forward slashes are safer. The code uses `//` (double forward slash) which works on both platforms.

### PITFALL 2: RZX Paths Forgotten When Moving Between Platforms
**Severity:** Fatal if DSSAT crop model is enabled.
**Symptom:** DSSAT crop model fails to initialize; error messages about missing database files.
**Cause:** `.RZX` files contain hardcoded absolute paths to the DSSAT database and project directory. These paths are not updated by the `initialize_scenario` function.
**Fix:** After moving a scenario to a new machine, manually update the paths inside all `.RZX` files in the scenario directory.

### PITFALL 3: Overwriting an Existing Scenario Without Warning
**Severity:** Operational risk -- data loss.
**Cause:** The `initialize_scneario_based_on_existing` function calls `shutil.rmtree` on the destination if it already exists, then copies the template. This permanently deletes any modified files in the existing scenario.
**Fix:** Before calling the initialization function, check if the destination directory exists and back up any important files. Or use a unique name for each scenario.

### PITFALL 4: Simulation Dates Outside Met File Range (FATAL)
**Severity:** Fatal -- model crashes when trying to read met data beyond available dates.
**Symptom:** Fortran runtime error or unexpected end-of-file.
**Cause:** The start or end date in `ipnames.dat` line 8 falls outside the date range of the `.met` file.
**Fix:** Ensure the simulation period in `ipnames.dat` is a subset of (or equal to) the `.met` file period. The `.met` header line 16 contains the begin and end dates.

### PITFALL 5: Date Format Error on Line 8 (FATAL)
**Severity:** Fatal -- model reads incorrect dates.
**Cause:** Using YYYY-MM-DD format instead of DD MM YYYY, or zero-padding inconsistently.
**Fix:** The `custom_date_format` function produces the correct format: `"{day} {month} {year}"` without zero-padding. Example: `"1 1 2011  31 12 2021"`. Do not use dashes, slashes, or ISO format.

### PITFALL 6: Missing Analysis Directory
**Severity:** Fatal -- output file cannot be created.
**Cause:** Line 7 of `ipnames.dat` points to `{project_path}/Analysis/{station_id}.ana`, but the `Analysis/` directory does not exist.
**Fix:** Create the `Analysis/` directory before running the model:
```python
os.makedirs(os.path.join(project_path, 'Analysis'), exist_ok=True)
```
