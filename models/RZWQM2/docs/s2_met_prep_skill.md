# Skill Document: Meteorological Data Preparation (S2)

**Stage:** s2_met_prep
**Pipeline Order:** 2
**Depends On:** None (independent of site config, but needed before breakpoint generation)
**Tools:** `generate_met_file`, `met_quality_check`

---

## Purpose

Prepare a daily meteorological input file (`.met`) for RZWQM2. This file provides the weather forcing data that drives evapotranspiration, soil water movement, crop growth, and snowmelt processes. The `.met` file has a strict format: a 36-line header followed by one row per simulation day, with 10 whitespace-separated columns. RZWQM2 has **no missing value handler** -- every day in the simulation period must have a complete data row, and every value must be numeric (no NaN, NA, or blank fields). Errors in meteorological data propagate through the entire simulation.

---

## Prerequisites

1. Daily weather data covering the entire simulation period (start date to end date, inclusive), with no gaps.
2. Required variables: minimum temperature, maximum temperature, wind speed, solar radiation, relative humidity, and precipitation.
3. Optional variables: pan evaporation and photosynthetically active radiation (PAR). These can be set to 0 if unavailable.
4. Python environment with access to `rzwqm_file.py` (specifically the `generate_rzwqm_met_header` and `write_to_rzwqm_met` functions).

---

## Inputs

### Source Data Requirements

| Variable | Column in .met | Unit | Valid Range | Required? |
|----------|---------------|------|-------------|-----------|
| Julian day | 1 | day of year (1-365/366) | 1-366 | Yes |
| Year | 2 | YYYY | any valid year | Yes |
| Tmin | 3 | degrees Celsius | -60 to 50 | Yes |
| Tmax | 4 | degrees Celsius | -60 to 60 | Yes |
| Wind run | 5 | km/day | 0 to 2000 | Yes |
| Solar radiation | 6 | MJ/m^2/day | 0 to 50 | Yes |
| Pan evaporation (E-pan) | 7 | cm H2O/day | 0 to 5 | No (use 0) |
| Relative humidity | 8 | % (0-100) | 0 to 100 | Yes |
| PAR | 9 | moles quanta/m^2/day | 0 to 100 | No (use 0) |
| Rainfall | 10 | mm | 0 to 500 | Yes |

### Tool Inputs

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `input_csv` | file path | CSV with daily weather columns | `weather_data.csv` |
| `output_met_path` | file path | Output .met file path | `Meteorology/station.met` |
| `start_date` | string | Simulation start date (YYYY-MM-DD) | `2011-01-01` |
| `end_date` | string | Simulation end date (YYYY-MM-DD) | `2021-12-31` |

---

## Procedure

### Step 1: Generate the 36-Line Header

The header is generated using `generate_rzwqm_met_header(start_date, end_date)`. It contains exactly 36 lines with the following structure:

- Lines 1-15: Banner and record 1 description (general information)
- Line 16: Data line with begin date, end date, and met flag (0 = daily)
  - Format: `    YYYY   MM   DD   YYYY   MM   DD   0`
- Lines 17-36: Record 2 description (column definitions) ending with a separator

```python
from datetime import datetime
from rzwqm_file import generate_rzwqm_met_header

start = datetime.strptime('2011-01-01', '%Y-%m-%d')
end = datetime.strptime('2021-12-31', '%Y-%m-%d')
header = generate_rzwqm_met_header(start, end)
# header is a list of exactly 36 strings
assert len(header) == 36
```

### Step 2: Prepare Daily Data Rows

For each day from start_date to end_date (inclusive), create a row with 10 values. Each row is a list of 10 string values:

```python
from datetime import timedelta

data_rows = []
current = start
while current <= end:
    julian_day = current.timetuple().tm_yday
    year = current.year
    row = [
        str(julian_day),           # Column 1: Julian day
        str(year),                 # Column 2: Year
        str(tmin_for_day),         # Column 3: Tmin (C)
        str(tmax_for_day),         # Column 4: Tmax (C)
        str(wind_for_day),         # Column 5: Wind run (km/day)
        str(radiation_for_day),    # Column 6: Solar radiation (MJ/m2/day)
        str(epan_for_day),         # Column 7: E-pan (cm) -- use '0' if unavailable
        str(rh_for_day),           # Column 8: RH (%)
        str(par_for_day),          # Column 9: PAR -- use '0' if unavailable
        str(precip_for_day)        # Column 10: Rainfall (mm)
    ]
    data_rows.append(row)
    current += timedelta(days=1)
```

### Step 3: Unit Conversions

Common source data may need conversion:

| Source Unit | Target Unit | Conversion |
|------------|-------------|------------|
| Wind speed (m/s) | Wind run (km/day) | multiply by 86.4 (= 3600 * 24 / 1000) |
| Wind speed (km/h) | Wind run (km/day) | multiply by 24 |
| Solar radiation (W/m^2) | MJ/m^2/day | multiply by 0.0864 (= 3600 * 24 / 1e6) |
| Precipitation (inches) | mm | multiply by 25.4 |
| Temperature (F) | Celsius | (F - 32) * 5/9 |
| RH as fraction (0-1) | % (0-100) | multiply by 100 |

### Step 4: Write the .met File

Use the `write_to_rzwqm_met` function to combine the header and data, then write to disk:

```python
from rzwqm_file import write_to_rzwqm_met

write_to_rzwqm_met(output_met_path, data_rows, header)
```

This writes each data row formatted as:
```
   {julian}   {year}   {tmin}   {tmax}   {wind}   {rad}   {epan}   {rh}   {par}    {rain}
```

Note the spacing: columns are separated by 3 spaces, except between PAR and Rain which uses 4 spaces.

### Step 5: Run Quality Check

After generating the file, run the quality check **validated tool**:

```bash
python knowledge_infrastructure/tools/s2_met_prep/met_quality_check.py \
  <project_path> <station_id>
```

**Arguments:**
- `project_path` — RZWQM2 project root (the directory containing `Meteorology/`)
- `station_id` — Station or grid identifier (filename stem, e.g., `bengbu_32.9375_117.3125`)

The tool constructs the met file path as `{project_path}/Meteorology/{station_id}.met`.

**Do NOT pass a met file path directly** — the tool expects `project_path` + `station_id` separately.

The quality check performs two corrections:
1. **Tmin > Tmax swap:** If Tmin exceeds Tmax for any day, the values are swapped.
2. **RH cap at 100:** If relative humidity exceeds 100%, it is capped at 100.

These corrections are applied in-place to the .met file.

### Step 6: Verify File Structure

```python
with open(output_met_path) as f:
    lines = f.readlines()

# Verify header length
assert len(lines[:36]) == 36, "Header must be exactly 36 lines"

# Verify data row count
expected_days = (end - start).days + 1
data_lines = lines[36:]
# Filter out empty lines
data_lines = [l for l in data_lines if l.strip()]
assert len(data_lines) == expected_days, f"Expected {expected_days} data rows, got {len(data_lines)}"
```

---

## Expected Outputs

- **File created:** `{project_path}/Meteorology/{station_id}.met`
- **File structure:**
  - Lines 1-36: Header (banner, date info, column descriptions)
  - Lines 37+: One data row per day with 10 whitespace-separated numeric values
- **Total line count:** 36 + number of simulation days

---

## Validation Checks

### Structural Checks
1. The file has exactly 36 header lines.
2. Each data row has exactly 10 whitespace-separated values.
3. The number of data rows equals the number of days in the simulation period.
4. Julian day in column 1 cycles from 1 to 365 (or 366 in leap years) and resets.
5. Year in column 2 increases monotonically within each Julian day cycle.

### Physical Consistency Checks
1. **Tmin <= Tmax** for every row (the QC tool auto-corrects this).
2. **0 <= RH <= 100** for every row (the QC tool caps at 100).
3. **Wind >= 0**: Negative wind values are physically impossible.
4. **Radiation >= 0**: Negative solar radiation is impossible.
5. **Precipitation >= 0**: Negative rainfall is impossible.
6. **Temperature range:** Tmin and Tmax should be within plausible bounds for the region (e.g., -50 to 50 C for temperate regions).

### Temporal Completeness Checks
1. No gaps in the date sequence (every day must be present).
2. Julian day 1 should appear on January 1 of each year.
3. Julian day 365 or 366 should appear on December 31.

---

## Common Pitfalls

### PITFALL 1: E-pan and PAR Set to Non-Zero Garbage (DEGRADED RESULTS)
**Severity:** Degraded -- model runs but PET may be wrong.
**Symptom:** Evapotranspiration values are unrealistically high or low.
**Cause:** If E-pan or PAR data are not available, some users fill them with arbitrary non-zero values instead of 0.
**Fix:** Set E-pan (column 7) and PAR (column 9) to `0` if not available. When these are 0, RZWQM uses its internal estimation methods (Penman-Monteith or Shuttleworth-Wallace) which are well-tested.

### PITFALL 2: Missing Data -- RZWQM Has No Missing Value Handler (FATAL)
**Severity:** Fatal -- model may crash or produce garbage.
**Symptom:** Fortran runtime error, NaN in output, or model hangs.
**Cause:** RZWQM2 reads each row expecting exactly 10 numeric values. If any value is missing, blank, `NA`, `NaN`, or `-9999`, the Fortran parser will either crash or interpret it as a numeric value, corrupting the simulation.
**Detection:** Search the .met data section for any non-numeric tokens.
**Fix:** Before generating the .met file, gap-fill all missing data. Common strategies:
- Temperature: linear interpolation between adjacent days.
- Radiation: use the average of surrounding days.
- Wind: use the monthly or seasonal average.
- Precipitation: use 0 for missing days (conservative assumption).
- RH: use monthly average.

### PITFALL 3: Wind Unit Confusion (SILENT ERROR)
**Severity:** Silent -- PET will be wrong.
**Cause:** Weather station data often reports wind speed in m/s or km/h, but RZWQM expects wind run in **km/day**.
**Detection:** If all wind values are between 0 and 20, they are likely in m/s or km/h (not km/day). Typical wind run values range from 50 to 500 km/day.
**Fix:** Convert: `km/day = m/s * 86.4` or `km/day = km/h * 24`.

### PITFALL 4: Incorrect Header Date Mismatch (OPERATIONAL ERROR)
**Severity:** May cause the model to read incorrect date ranges.
**Cause:** The dates embedded in header line 16 do not match the actual data rows.
**Fix:** Always generate the header using `generate_rzwqm_met_header(start_date, end_date)` with the same dates used to generate the data rows.

### PITFALL 5: Solar Radiation in W/m^2 Instead of MJ/m^2/day (SILENT ERROR)
**Severity:** Silent -- radiation values will be ~11.6x too high.
**Cause:** Source data provides instantaneous or mean daily irradiance in W/m^2. RZWQM expects daily accumulated radiation in MJ/m^2/day.
**Detection:** If radiation values routinely exceed 35-40, they may be in W/m^2. Typical MJ/m^2/day values range from 1 to 35 depending on latitude and season.
**Fix:** Convert: `MJ/m^2/day = W/m^2 * 0.0864`.
