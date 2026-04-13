# Skill Document: Breakpoint Rainfall Generation (S3)

**Stage:** s3_brk_generation
**Pipeline Order:** 3
**Depends On:** s2_met_prep (requires a completed .met file with daily precipitation data)
**Tool:** `create_breakpoint_file`

---

## Purpose

Convert daily precipitation totals (from the `.met` file) into a breakpoint rainfall file (`.brk`) that RZWQM2 uses to drive its infiltration model. RZWQM2's infiltration module operates on sub-daily time steps and requires rainfall to be specified as cumulative depth vs. time pairs (breakpoints). The breakpoint format allows the model to simulate rainfall intensity, which is critical for surface runoff and macropore flow calculations. Each rain event gets a control line (metadata) and breakpoint pairs that describe the cumulative rainfall progression within the storm.

**Critical unit note:** The `.brk` file uses **inches** for precipitation depth, while the `.met` file uses **millimeters**. The conversion (divide by 25.4) must be applied. Failure to convert produces a silent error -- the model runs but all infiltration calculations are wrong by a factor of 25.4.

---

## Prerequisites

1. A completed `.met` file exists at `{project_path}/Meteorology/{station_id}.met` with valid daily precipitation data in column 10 (mm).
2. The `.met` file has passed quality checks (S2 complete).
3. Python environment with access to `rzwqm_file.py` (specifically the `RZWQM` class and its `create_breakpoint_file` method).

---

## Inputs

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `project_path` | string (directory) | RZWQM2 project root directory | `/Users/leo/Desktop/RZWQM2/projects/` |
| `station_id` | string | Station/scenario identifier | `534` |

The tool reads precipitation data directly from the `.met` file. No separate precipitation input is needed.

---

## Procedure

### Step 1: Read Precipitation from .met File

The `create_breakpoint_file` method reads the .met file, extracts daily precipitation from column 10 (index 9), and converts each date/value pair into a (datetime, precip_mm) tuple:

```python
from rzwqm_file import RZWQM

rz = RZWQM(project_path, station_id)
# This reads the .met file internally
rz.create_breakpoint_file()
```

### Step 2: Understand the .brk File Format

The generated `.brk` file has the following structure:

#### Header (20 lines)
```
===============================================================================
=
=                         R Z W Q M 2
=           User created breakpoint rainfall file from daily met file
=
=
==       B R E A K P O I N T  R A I N F A L L   D A T A
==
== Rec 1: calendar code: =1 - date counted as Julian days within year
== Rec 2: control info for a breakpoint event:
==        year, date, no. breakpoints, midnight (day spanning, 1=yes),
==        code, total storm depth [in]
== Rec 3: pairs of cum storm dep [in] & clock time [min]
==        5 pairs per rec
== REPEAT Rec 3 to complete data for an event
==
== REPEAT Rec's 2 & 3 for subsequent events
=
===============================================================================
1
```

The last line (`1`) is the calendar code indicating Julian day counting within each year.

#### Event Records (for each rainy day)

For each day with precipitation > 0, two lines are written:

**Control line (Rec 2):**
```
    YYYY       JJJ        2        0     P.PPP
```
Where:
- `YYYY` = year
- `JJJ` = Julian day of year
- `2` = number of breakpoints (always 2 in this simplified scheme)
- `0` = midnight flag (0 = event does not span midnight)
- `P.PPP` = total storm depth in **inches** (3 decimal places)

**Breakpoint line (Rec 3):**
```
    0.000        0     P.PPP        TTT
```
Where:
- `0.000` = cumulative depth at time 0 (start of event)
- `0` = clock time 0 minutes (start)
- `P.PPP` = cumulative depth at end of event (= total depth in inches)
- `TTT` = clock time in minutes at end of event (estimated duration)

### Step 3: Unit Conversion (mm to inches)

The conversion is performed internally by the tool:

```python
precip_inches = precip_mm / 25.4
```

This division by 25.4 converts millimeters to inches. The result is written with 3 decimal places (`.3f` format).

### Step 4: Duration Estimation

For each rain event, the storm duration in minutes is estimated using a simple heuristic:

```python
duration_minutes = min(precip_inches * 1500, 120)
```

This means:
- Small events (< 0.08 inches / 2 mm): Duration is proportional to depth, around 1-2 hours.
- Large events (> 0.08 inches / 2 mm): Duration is capped at 120 minutes (2 hours).
- The duration is cast to integer: `int(precip_inches * 1500)`.

This is a simplified approach. For studies where rainfall intensity matters significantly (erosion, macropore flow), consider using actual sub-daily rainfall data or a more sophisticated temporal disaggregation method.

### Step 5: Verify Output

```python
import os
brk_path = project_path + "/Meteorology/" + station_id + ".brk"
assert os.path.exists(brk_path), ".brk file was not created"

with open(brk_path) as f:
    lines = f.readlines()

# Check header
assert len(lines) >= 20, "File too short for header"
assert lines[19].strip() == '1', "Calendar code should be 1"

# Count events: every event produces 2 lines (control + breakpoints)
event_lines = lines[20:]
event_lines = [l for l in event_lines if l.strip()]
assert len(event_lines) % 2 == 0, "Event lines should come in pairs"
num_events = len(event_lines) // 2
print(f"Number of rain events: {num_events}")
```

---

## Expected Outputs

- **File created:** `{project_path}/Meteorology/{station_id}.brk`
- **File structure:**
  - Lines 1-20: Header with banner and format description
  - Line 20: Calendar code (`1`)
  - Lines 21+: Pairs of event records (control line + breakpoint line) for each rainy day
- **Precipitation values in the file are in INCHES, not mm.**
- **Number of events:** Equal to the number of days with precipitation > 0 in the .met file.

---

## Validation Checks

1. **File exists** at the expected path after running the tool.
2. **Event count matches:** Count the number of days with precip > 0 in the .met file and compare with the number of events in the .brk file.
3. **Precipitation totals:** For each event, the total depth in the control line should match the cumulative depth in the breakpoint line. Both should equal `daily_precip_mm / 25.4`.
4. **Duration reasonableness:** All durations should be between 1 and 120 minutes.
5. **Year and Julian day consistency:** The year and Julian day in each control line should correspond to valid dates within the simulation period.
6. **No zero-precipitation events:** The .brk file should not contain events for days with 0 precipitation.

---

## Common Pitfalls

### PITFALL 1: BRK Uses INCHES, Not mm (SILENT ERROR)
**Severity:** Silent -- the model runs but all infiltration and runoff calculations are wrong.
**Symptom:** Runoff is vastly overestimated (if mm values are written as inches, the model sees 25.4x too much rain) or underestimated if the inverse error occurs.
**Cause:** Writing precipitation in mm directly to the .brk file without dividing by 25.4.
**Detection:** Open the .brk file and check if precipitation values seem reasonable. A 25 mm (1 inch) rainfall event should show as approximately 0.984 in the .brk file. If it shows as 25.000, the conversion was not applied.
**Fix:** The `create_breakpoint_file` method handles this conversion automatically. If writing manually, always divide mm by 25.4:
```python
precip_inches = precip_mm / 25.4
```

### PITFALL 2: Missing Rain Events
**Severity:** Moderate -- the model will underestimate precipitation.
**Cause:** If the .met file has precipitation data encoded incorrectly (e.g., trace amounts as negative values), those days will not generate breakpoint events.
**Fix:** Ensure all precipitation values in the .met file are >= 0 and that trace amounts are either set to 0 or a small positive value.

### PITFALL 3: Duration Heuristic Too Coarse for Intensity-Sensitive Studies
**Severity:** Moderate for runoff/erosion studies, minor for water balance studies.
**Cause:** The simplified duration formula (`min(precip_inches * 1500, 120)`) assigns all rainfall uniformly within the estimated duration. Real storms have varying intensity patterns.
**Fix:** For studies where rainfall intensity matters (macropore flow, erosion, surface runoff partitioning), replace the heuristic with actual sub-daily rainfall data or use a temporal disaggregation model (e.g., cascade-based or rectangular pulse methods).

### PITFALL 4: Leap Year Julian Day Mismatch
**Severity:** Minor -- may cause a 1-day offset in rain timing.
**Cause:** If the .met file uses Julian days that do not account for leap years (e.g., day 366 in a non-leap year), the corresponding .brk event will reference an invalid date.
**Fix:** The tool reads dates from the .met file and uses Python's `datetime.timetuple().tm_yday` which correctly handles leap years. Ensure the .met file itself has correct Julian days.
