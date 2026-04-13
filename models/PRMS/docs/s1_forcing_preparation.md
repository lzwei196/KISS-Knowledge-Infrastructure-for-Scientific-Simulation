# Stage 1: Forcing Data Preparation

## Purpose

Convert global gridded or station meteorological data into PRMS-compatible forcing files with correct units. This is the most error-prone stage due to unit conversions.

## Inputs

| Source | Variables | Native Units |
|--------|-----------|-------------|
| CMFD | tmax, tmin, precip, radiation | C, mm/3hr, W/m2 |
| ERA5 | 2m temp, total precip, radiation | K, m/timestep, J/m2 |
| MSWX | tmax, tmin, precip | C, mm/day |
| Station CSV | tmax, tmin, precip, runoff | varies |

## Outputs

**Station mode**: Single PRMS data file (`prms.data`)
**CBH mode**: Separate per-HRU files (`tmax.cbh`, `tmin.cbh`, `precip.cbh`)

## Procedure

### Step 1: Read raw forcing data

```python
from tools.convert_forcing_to_prms import process_forcing
data = process_forcing(input_path, "cmfd", start_dt, end_dt, nhru)
```

### Step 2: Apply unit conversions

**CRITICAL — these conversions MUST be applied:**

| Variable | Source Unit | PRMS Unit | Formula |
|----------|-----------|-----------|---------|
| Temperature | Celsius | Fahrenheit | `F = C * 9/5 + 32` |
| Temperature | Kelvin | Fahrenheit | `F = (K - 273.15) * 9/5 + 32` |
| Precipitation | mm/day | inches/day | `in = mm / 25.4` |
| Precipitation | mm/3hr | inches/day | `in = mm * 8 / 25.4` |
| Precipitation | m/timestep | inches/day | `in = m * 1000 / 25.4` |
| Solar radiation | W/m2 | Langleys/day | `Ly = W/m2 * 0.0864` |
| Streamflow | m3/s | cfs | `cfs = cms / 0.028317` |

### Step 3: Validate converted values

Expected ranges after conversion:

| Variable | Typical Range | Red Flag |
|----------|--------------|----------|
| tmax (F) | -20 to 120 | < -40 or > 130 |
| tmin (F) | -40 to 100 | < -60 or > 110 |
| precip (in/day) | 0 to 10 | > 20 (likely mm not converted) |
| solrad (Ly/day) | 0 to 800 | > 1000 (likely W/m2 not converted) |

### Step 4: Write output files

**Data file format**:
```
PRMS data file for Basin_Name
tmax 1
tmin 1
precip 1
runoff 1
####
1980 10 1 0 0 0 55.4 32.1 0.00 10.5
```

**CBH file format**:
```
tmax 42
########################################
1980 10 1 0 0 0 55.4 56.2 54.8 ... (42 values)
```

## Verification

- [ ] Temperature values are in Fahrenheit range (typically 0-100 F for temperate basins)
- [ ] Mean annual precipitation is reasonable (e.g., 15-60 inches for most US basins)
- [ ] tmin < tmax for all timesteps
- [ ] No negative precipitation values
- [ ] No NaN or missing values
- [ ] Data file covers full simulation period
- [ ] CBH file has correct number of HRU columns

## Traps

### 1. Celsius fed as Fahrenheit (SILENT FAILURE)

If you feed 20C directly, PRMS interprets it as 20F = -6.7C. Snow never melts, ET is near zero. The model runs without errors but produces garbage output.

**Detection**: Check if mean tmax is unreasonably low (< 40F for temperate basins).

### 2. mm/day fed as inches/day (25.4x too much precipitation)

If you feed 5 mm/day directly, PRMS treats it as 5 inches/day = 127 mm/day. Extreme flooding, unrealistic runoff ratios.

**Detection**: Check if total annual precipitation > 100 inches for non-tropical basins.

### 3. CBH header format

The CBH header must be exactly:
```
variable_name nhru_count
########################################
```

Extra spaces, wrong delimiter characters, or missing nhru count cause read errors.

### 4. Data file column order

Variables in the data file MUST appear in the same order as declared in the header. PRMS reads positionally, not by name.

## Example

```bash
python tools/convert_forcing_to_prms.py \
    --input_dir /data/cmfd/sagehen/ \
    --output_dir /prms/input/ \
    --mode cbh \
    --start_date 1980-10-01 \
    --end_date 2010-09-30 \
    --nhru 42 \
    --input_format cmfd
```

Output:
```
[convert] tmax: -15.2-38.5 C -> 4.6-101.3 F
[convert] tmin: -28.1-22.4 C -> -18.6-72.3 F
[convert] precip: 2.84 mm/d -> 0.1118 in/d
[write] CBH file: /prms/input/tmax.cbh (10958 days, 42 HRUs)
[write] CBH file: /prms/input/tmin.cbh (10958 days, 42 HRUs)
[write] CBH file: /prms/input/precip.cbh (10958 days, 42 HRUs)
All checks passed.
```
