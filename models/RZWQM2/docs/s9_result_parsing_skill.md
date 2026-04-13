# Skill Document: Result Parsing and Evaluation (S9)

**Stage:** s9_result_parsing
**Pipeline Order:** 9
**Depends On:** s8_execution (model must have completed successfully, producing output files)
**Tools:** `parse_ana_output`, `parse_layer_output`

---

## Purpose

Parse the RZWQM2 simulation output files to extract specific variables as time series for analysis, visualization, and comparison with observed data. RZWQM2 produces two primary output files: (1) the `.ana` file containing daily aggregated values for water balance, nutrient, and crop variables (approximately 100 columns), and (2) the `Layer.plt` file containing depth-resolved soil state variables at each computational node. Both files use fixed-width or whitespace-delimited formats with a non-standard date encoding (`YYYY.JJJ` for Julian day).

Correct parsing requires knowledge of column indices, unit conventions, and header structure. Critical unit conversions must be applied during parsing -- most notably, tile drainage in the `.ana` file is reported in **centimeters** and must be multiplied by 10 to obtain **millimeters**.

---

## Prerequisites

1. RZWQM2 has completed execution successfully (S8 complete).
2. The `.ana` file exists at `{project_path}/Analysis/{station_id}.ana`.
3. The `Layer.plt` file exists at `{project_path}/{station_id}/Layer.plt` (if depth-resolved output is needed).
4. Python environment with access to `rzwqm_file.py` (specifically the `RZWQM` class).

---

## Inputs

### For .ana Parsing

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `project_path` | string (directory) | RZWQM2 project root | `/Users/leo/Desktop/RZWQM2/projects/` |
| `station_id` | string | Station identifier | `534` |
| `variable` | string | Variable to extract | `"snow"` or `"tile_drainage"` |

### For Layer.plt Parsing

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `project_path` | string (directory) | RZWQM2 project root | `/Users/leo/Desktop/RZWQM2/projects/` |
| `station_id` | string | Station identifier | `534` |
| `column_num` | int | Column index for desired variable | `4` (soil temperature) |
| `desired_depths` | list of int | Node depths to extract | `[10, 30, 60, 100]` |

---

## Procedure

### Part A: Parsing the .ana File

#### Step A1: Understand .ana File Structure

The `.ana` file has the following structure:

- **Line 1:** Blank or header identifier (removed during parsing).
- **Lines 2-24 (indices 1-23 after removal of line 0):** Header lines with column descriptions.
- **Lines 25+ (index 24+):** Daily data rows, one per simulation day.

Each data row is whitespace-separated. The first column (index 0) contains the date in `YYYY.JJJ` format where `JJJ` is the 3-digit Julian day of the year (001-366).

**Key column indices (0-based):**

| Column Index | Variable | Unit in .ana | Conversion Needed |
|-------------|----------|-------------|-------------------|
| 0 | Date | YYYY.JJJ | Parse with `datetime.strptime(val, '%Y.%j')` |
| 10 | Tile drainage | cm | Multiply by 10 for mm |
| 91 | Snow depth | cm | None (use as cm) |

#### Step A2: Parse Using the RZWQM Class

```python
from rzwqm_file import RZWQM

rz = RZWQM(project_path, station_id)

# Extract tile drainage (returns dict of {datetime: value_in_mm})
tile_drainage = rz.rzwqm_res_parse('tile_drainage')

# Extract snow depth (returns dict of {datetime: value_in_cm})
snow = rz.rzwqm_res_parse('snow')
```

The `rzwqm_res_parse` method performs the following steps internally:

1. Reads the `.ana` file using `read_text_file` (splits each line by whitespace).
2. Removes the first line (line 0).
3. Skips the next 23 lines (header), so data starts at index 23 after the deletion (effectively line 24 of the original file).
4. For each data row:
   - Extracts the date from column 0 using `datetime.strptime(line[0], '%Y.%j')`.
   - Extracts the value from the specified column.
   - For `tile_drainage`: multiplies by 10 to convert cm to mm.
   - For other variables: returns the raw value.
5. Returns a dictionary mapping `datetime` objects to float values.

**Date parsing fallback:** If the standard `%Y.%j` parsing fails (e.g., Julian day 366 in a non-leap year), the code falls back to using `%j%Y` format with day `001` of the given year. This is a safety mechanism; check the output for such fallback dates.

#### Step A3: Manual Parsing (If Extending to Other Columns)

To extract a variable at a column index not handled by `rzwqm_res_parse`:

```python
from datetime import datetime

rz = RZWQM(project_path, station_id)
lines = rz.read_text_file(rz.simulate_path)

# Remove first line and skip 23 header lines
del lines[0]
data_lines = lines[23:]

# Extract column 5 (example: some other variable)
target_column = 5
result = {}
for line in data_lines:
    try:
        date = datetime.strptime(line[0], '%Y.%j')
        value = float(line[target_column])
        result[date] = value
    except Exception as e:
        print(f"Parsing error on line: {e}")
        continue
```

### Part B: Parsing the Layer.plt File

#### Step B1: Understand Layer.plt File Structure

The `Layer.plt` file contains depth-resolved output at each computational node. The structure is:

- **Header:** Variable number of header lines ending with `'****************** DATA STARTS HERE *****************'`
- **Data:** One row per (time step, node) combination.

Each data row contains:

| Column Index | Variable | Description |
|-------------|----------|-------------|
| 0 | Time identifier | Time step or date code |
| 1 | Depth | Node depth in cm |
| 2-N | Variables | Various soil state variables |

Key column indices for Layer.plt:

| Column Index | Variable | Unit |
|-------------|----------|------|
| 1 | Depth | cm |
| 4 | Soil temperature | degrees C |

#### Step B2: Parse Using the RZWQM Class

```python
rz = RZWQM(project_path, station_id)

# Get soil temperature at specific depths
soil_temp = rz.return_soil_temperature(column_num=4)
# Returns: {depth: [list of values over time]}
# Example: {10: [5.2, 5.3, 5.5, ...], 30: [8.1, 8.0, 7.9, ...]}
```

The `return_soil_temperature` method:

1. Finds the header end line using `'****************** DATA STARTS HERE *****************'`.
2. Gets the list of node depths from `parse_soil_discretization_nodes()`.
3. Calls `rzwqm_parse_layer` which:
   - Reads all lines after the header.
   - Groups values by depth (column 1).
   - For each depth in the `desired_depth` list, collects all values from the specified `column_num`.

#### Step B3: Parse for Specific Depths

To extract data for specific depths rather than all nodes:

```python
# Get all discretization node depths
nodes = rz.parse_soil_discretization_nodes()
# Returns: [1, 2, 5, 8, 12, 17, 23, 30, ...]

# Choose depths of interest
desired_depths = [10, 30, 60, 100]
# Find the closest node depths
actual_depths = []
for target in desired_depths:
    closest = min(nodes, key=lambda x: abs(x - target))
    actual_depths.append(closest)

# Parse Layer.plt for those depths
head_line = rz.line_number_of_soil_temperature()[0]
soil_data = rz.rzwqm_parse_layer(actual_depths, rz.layer_data, head_line, 4)
# Returns: {depth: [values]}
```

### Part C: Post-Processing and Evaluation

#### Step C1: Convert Parsed Data to Time Series

The `.ana` parser returns datetime-indexed dictionaries. Convert to sorted lists for time series analysis:

```python
import sorted

# Sort by date
sorted_data = sorted(tile_drainage.items(), key=lambda x: x[0])
dates = [item[0] for item in sorted_data]
values = [item[1] for item in sorted_data]
```

#### Step C2: Compare with Observations

To evaluate model performance, compare parsed simulation output with observed data:

```python
# Example: compute Nash-Sutcliffe Efficiency
import numpy as np

sim = np.array([tile_drainage.get(d, np.nan) for d in obs_dates])
obs = np.array(obs_values)

# Remove NaN pairs
mask = ~np.isnan(sim) & ~np.isnan(obs)
sim_clean = sim[mask]
obs_clean = obs[mask]

nse = 1 - np.sum((obs_clean - sim_clean)**2) / np.sum((obs_clean - np.mean(obs_clean))**2)
print(f"NSE = {nse:.3f}")
```

---

## Expected Outputs

### From .ana Parsing
- **Return type:** `dict` of `{datetime: float}`
- **Keys:** `datetime` objects for each simulation day
- **Values:** Floating-point values in the appropriate unit (mm for tile drainage, cm for snow)
- **Coverage:** One entry per simulation day

### From Layer.plt Parsing
- **Return type:** `dict` of `{int: list[float]}`
- **Keys:** Integer depths in cm (node depths)
- **Values:** Lists of floating-point values (one per output time step)

---

## Validation Checks

1. **Data coverage:** The parsed dictionary should have entries for every day in the simulation period. Missing days indicate parsing errors or incomplete simulation.
2. **Value reasonableness:**
   - Tile drainage: typically 0-10 mm/day for most events, up to 50 mm/day for extreme events.
   - Snow depth: 0-200 cm depending on region and season.
   - Soil temperature: -20 to 50 degrees C depending on depth and season.
3. **Total tile drainage:** Annual tile drainage for tile-drained agricultural fields is typically 50-500 mm/year depending on climate and soil.
4. **Seasonal patterns:** Snow should appear in winter, tile drainage peaks during snowmelt and after large rain events.
5. **Date range:** Parsed dates should cover exactly the simulation period specified in `ipnames.dat` line 8.

---

## Common Pitfalls

### PITFALL 1: Tile Drainage in .ana is in cm -- Must Multiply by 10 for mm (SILENT ERROR)
**Severity:** Silent -- values are off by a factor of 10.
**Symptom:** Tile drainage values seem unrealistically low when compared with observed data in mm.
**Cause:** The `.ana` file reports tile drainage volume in **centimeters**, but most observed drainage data and water balance calculations use **millimeters**.
**Detection:** If the `rzwqm_res_parse` method is used with `var_name='tile_drainage'`, the multiplication by 10 is applied automatically. If parsing manually, the raw column 10 values are in cm.
**Fix:** Always multiply column 10 values by 10 to convert to mm:
```python
drainage_mm = float(line[10]) * 10
```
The `rzwqm_res_parse('tile_drainage')` method does this automatically.

### PITFALL 2: Date Format is YYYY.JJJ, Not Standard Calendar (PARSING ERROR)
**Severity:** Moderate -- incorrect date assignment.
**Symptom:** Dates are parsed incorrectly, leading to misalignment with observed data.
**Cause:** The `.ana` file uses `YYYY.JJJ` format where `JJJ` is the Julian day of the year (001-366), not a standard calendar date (YYYY-MM-DD). For example, `2015.032` means February 1, 2015 (32nd day of the year).
**Fix:** Always use `datetime.strptime(value, '%Y.%j')` to parse dates:
```python
from datetime import datetime
date = datetime.strptime('2015.032', '%Y.%j')
# Returns: datetime(2015, 2, 1, 0, 0)
```
Note: The `%j` format specifier in Python expects zero-padded 3-digit day (001-366). The `.ana` file provides this format.

### PITFALL 3: Off-by-One in Header Lines
**Severity:** Moderate -- first day's data may be interpreted as header, or last header line as data.
**Cause:** The `.ana` header has 23 lines (after removing line 0, making it effectively lines 1-23 of the parsed array). Counting errors can cause the first data row to be skipped or the last header row to be parsed as data.
**Detection:** Check if the first "data" value has a valid `YYYY.JJJ` date format. If it contains text or non-numeric values, the header offset is wrong.
**Fix:** The code uses `del lines[0]` then `lines = lines[23:]`, which skips the first 24 lines total (1 deleted + 23 skipped). Verify this matches the actual `.ana` file structure by inspecting the first few data rows.

### PITFALL 4: Layer.plt Node Depths vs Horizon Depths
**Severity:** Minor -- confusion in interpretation.
**Cause:** `Layer.plt` reports data at computational node depths, which may not match the original horizon depths exactly (due to discretization adjustments in S5). A user looking for "the 30 cm horizon" may not find an exact match.
**Fix:** Use `parse_soil_discretization_nodes()` to get the actual node depths, then select the closest node to the desired depth. Do not assume node depths match horizon boundary depths.

### PITFALL 5: Large .ana Files Slow to Parse
**Severity:** Operational -- slow performance.
**Cause:** For long simulations (> 30 years), the `.ana` file can be very large (> 100 MB with ~100 columns per day). Reading and parsing the entire file line-by-line in Python is slow.
**Fix:** For performance-critical applications, consider using `pandas.read_csv` with `skiprows=24` and `sep='\s+'` to leverage C-based parsing. Or, pre-process the `.ana` file to extract only the columns of interest using command-line tools:
```bash
awk 'NR>24 {print $1, $11}' station.ana > drainage.csv
```
(Column 11 in awk = index 10 in Python, since awk is 1-based.)
