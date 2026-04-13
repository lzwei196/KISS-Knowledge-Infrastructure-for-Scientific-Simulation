# s0: Data Preparation — Loading and Converting Field Data

## Purpose

Convert raw field geophysical data from instrument-native formats into pyGIMLi's
DataContainer format. This is the critical first step where most unit-related
errors enter the pipeline.

## Inputs

| Input               | Format                 | Unit              | Source               |
|---------------------|------------------------|-------------------|----------------------|
| ERT field data      | Res2DInv `.dat`        | Ω·m (rhoa)        | ABEM, Syscal, etc.  |
| ERT field data      | ABEM `.ohm`            | Ω·m               | Terrameter LS/SAS   |
| ERT field data      | CSV (a,b,m,n,rhoa)     | Ω·m               | Custom export        |
| SRT first-arrival   | SEG-2 `.sg2`           | s (travel time)   | Seismograph          |
| SRT pick file       | CSV (sx,rx,t)          | s                 | Manual or auto picks |
| Electrode positions | CSV/TXT                | m (local coords)  | Survey notes/GPS     |

## Outputs

| Output              | Format                 | Unit              | Destination          |
|---------------------|------------------------|-------------------|----------------------|
| ERT DataContainer   | `.ohm` / `.dat`        | Ω·m               | s1 mesh generation   |
| SRT DataContainer   | `.sgt` / `.gtt`        | s                 | s1 mesh generation   |
| Metadata JSON       | `.meta.json`           | —                 | QC and documentation |

## Procedure

### Step 1: Identify data format
Determine the instrument/software that produced the file. Key indicators:
- Res2DInv: starts with a title line, then array type code (1-11)
- ABEM: `.ohm` extension, ABEM header format
- Syscal: `.csv` or `.txt` with Syscal-specific column headers
- SEG-2: binary format with SEG-2 header
- CSV: comma/tab-delimited with column headers

### Step 2: Load and parse
```python
# Native pyGIMLi loading (if format is supported)
import pygimli as pg
data = pg.load("field_data.dat")

# Or use the KI tool for CSV:
# python convert_data_to_gimli.py --input data.csv --method ert --format csv --output data.ohm
```

### Step 3: Validate electrode positions
```python
# Check electrode positions are in metres, not lat/lon
sensors = data.sensors()
x_range = max([s.x() for s in sensors]) - min([s.x() for s in sensors])
if x_range < 1.0:
    print("WARNING: Electrode spread < 1 m — coordinates may be in degrees")
if x_range > 100000:
    print("WARNING: Electrode spread > 100 km — coordinates may need projection")
```

### Step 4: Validate data values
```python
# ERT: check apparent resistivity range
rhoa = data['rhoa']
print(f"rhoa range: {min(rhoa):.1f} – {max(rhoa):.1f} Ohm·m")
# Typical near-surface: 1 – 10000 Ohm·m

# SRT: check travel time range
t = data['t']
print(f"t range: {min(t):.6f} – {max(t):.6f} s")
# Typical near-surface: 0.001 – 0.1 s
```

### Step 5: Apply error estimation
```python
from pygimli.physics import ert
data['err'] = ert.estimateError(data, relativeError=0.03, absoluteUError=5e-5)
```

## Verification

1. **Electrode count**: matches field log
2. **Data count**: matches expected number of measurements
3. **Resistivity range**: 1–10000 Ω·m for typical near-surface surveys
4. **Travel time range**: 0.001–0.1 s for near-surface refraction
5. **No negative values**: in resistivity or travel times
6. **No NaN/Inf**: in any data column

## Traps

| Trap | Symptom | Cause | Fix |
|------|---------|-------|-----|
| dt_001 | Resistivity values 1000× expected | Data in Ω instead of Ω·m | Apply geometric factor |
| dt_002 | Travel times seem too large | Times in ms instead of s | Divide by 1000 |
| dt_003 | Mesh generation fails | Coordinates in lat/lon | Project to local metres |
| dt_004 | IP phase has wrong sign | Convention mismatch | Negate phase values |
| dt_005 | Error too small/large | % vs. fraction confusion | Error as fraction 0–1 |

## Example

```bash
# Convert CSV ERT data with 1 m electrode spacing
python ki/tools/convert_data_to_gimli.py \
    --input field_survey.csv \
    --method ert \
    --format csv \
    --electrode-spacing 1.0 \
    --output data/survey.ohm

# Convert CSV SRT picks (times in milliseconds)
python ki/tools/convert_data_to_gimli.py \
    --input first_arrivals.csv \
    --method srt \
    --format csv \
    --time-unit ms \
    --output data/picks.sgt
```
