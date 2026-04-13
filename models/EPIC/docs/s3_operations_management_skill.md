# Stage 3: Operations and Management Scheduling

## Purpose

Create and configure EPIC .OPC (Operation Schedule) files that define the
complete crop management sequence: planting dates, harvest dates, fertilizer
applications, tillage operations, irrigation, and crop rotations.

## Prerequisites

- Stage 0 (Configuration) completed
- Knowledge of crop type and management practices
- Crop code from CROPCOM.DAT (e.g., 2=Corn, 1=Soybean)
- PHU (Potential Heat Units) for the crop and region

## Inputs

| Input | Description | Example |
|-------|-------------|---------|
| Crop code | From CROPCOM.DAT | 2 (Corn) |
| Planting date | Month/day | May 1 |
| Harvest date | Month/day | October 15 |
| PHU | Thermal units (deg C-day) | 1700 (Corn, Iowa) |
| Fertilizer rate | kg N/ha | 150 |
| Rotation years | Number of years in cycle | 2 (corn-soy) |

## Outputs

| Output | Format | Location |
|--------|--------|----------|
| {site}.OPC | Fixed-width text | opc/ |
| crop_templates/MAPPING | CSV | opc/crop_templates/ |

## Procedure

### Creating an OPC file

```python
from geoEpic.io import OPC

# Load from template
opc = OPC.load('opc/crop_templates/CORN.OPC')

# Edit planting date
opc.edit_plantation_date('2015-05-01', crop_code=2)

# Edit harvest date
opc.edit_harvest_date('2015-10-15', crop_code=2)

# Edit fertilizer rate
opc.edit_fertilizer_rate(150.0, year=1, month=4, day=15)

# Save
opc.save('opc/site1.OPC')
```

### OPC File Format

**Header:**
```
Corn irrigated : 2015
   3  72
```
- Line 1: Description : start_year
- Line 2: LUN (3=cropland), IAUI (72=auto-irrigation, 0=none)

**Data rows (fixed-width, 15 columns):**
```
  1  5  1    2    0    2    01700.000    0.00    0.00   0.000    0.00    0.00    0.00    0.00
```

### Key Operation Codes

| Code | Operation | OPV1 | XMTU | Notes |
|------|-----------|------|------|-------|
| 2 | Plant (spring) | PHU (deg C-day) | - | CRP = crop code |
| 3 | Plant (summer) | PHU | - | CRP = crop code |
| 4 | Plant (fall) | PHU | - | For winter crops |
| 650 | Harvest | - | - | Removes above-ground biomass |
| 71 | Fertilizer | Rate (kg/ha) | Fertilizer ID | 52 = UAN-28 |
| 72 | Auto-irrigation | - | - | Set in header IAUI |
| 41 | Residue mgmt | - | - | Post-harvest |
| 9 | Fallow | - | - | No crop |

### PHU (Potential Heat Units) Guide

PHU = sum of (daily_avg_temp - base_temp) from planting to maturity.

| Crop | Region | Typical PHU |
|------|--------|-------------|
| Corn | Iowa/Illinois | 1600-1800 |
| Corn | Nebraska | 1500-1700 |
| Soybean | Iowa | 1400-1600 |
| Winter wheat | Kansas | 2000-2400 |

**Wrong PHU is the #1 cause of zero yields.** If too low, crop matures
prematurely with minimal biomass. If too high, crop never reaches maturity.

### Crop Rotation Example (Corn-Soybean)

```
Corn-Soy rotation : 2015
   3  72
  1  4 15   71    0    2   52 150.000    0.00    0.00   0.000    0.00    0.00    0.00    0.00
  1  5  1    2    0    2    01700.000    0.00    0.00   0.000    0.00    0.00    0.00    0.00
  1 10 15  650    0    2    0   0.000    0.00    0.00   0.000    0.00    0.00    0.00    0.00
  2  5 15    2    0    1    01500.000    0.00    0.00   0.000    0.00    0.00    0.00    0.00
  2 10  1  650    0    1    0   0.000    0.00    0.00   0.000    0.00    0.00    0.00    0.00
```

## Verification

1. Each planting (code 2/3/4) has a matching harvest (code 650) in the same year
2. PHU values are reasonable for crop and region
3. Fertilizer applied before or at planting, not after harvest
4. Crop codes match entries in CROPCOM.DAT
5. Year IDs are sequential (1, 2, ... for rotation)
6. Dates are physically reasonable (not planting in January in northern hemisphere)

## Traps

| Trap | Symptom | Root Cause | Fix |
|------|---------|------------|-----|
| PHU too low | Zero or tiny yield | Crop matures too fast | Increase PHU to match region |
| PHU too high | Zero yield, never matures | Crop doesn't finish | Decrease PHU |
| No harvest operation | Output shows no yield | Missing code 650 | Add harvest before year end |
| Wrong crop code | Wrong crop simulated | Code doesn't match CROPCOM | Verify crop code in CROPCOM.DAT |
| Planting after harvest | No growth period | Dates swapped | Fix planting < harvest date |
| Fertilizer rate in lb/ac | Under-fertilization | US units not converted | Multiply by 1.121 to get kg/ha |
| IAUI=0 with dryland crop | Water stress | No irrigation | Set IAUI=72 for irrigated |

## Example

```python
from geoEpic.io import OPC

opc = OPC.load('opc/Ne2.OPC')
print(f"Start year: {opc.start_year}")
print(f"LUN: {opc.lun}, IAUI: {opc.iaui}")

for season in opc.iter_seasons():
    print(f"  Crop {season['crop_code']}: "
          f"Plant {season['plantation_date']} → "
          f"Harvest {season['harvest_date']}")
```
