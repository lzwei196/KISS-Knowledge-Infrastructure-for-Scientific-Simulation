# S5: Output Analysis

## Purpose

Parse Daisy's `.dlf` (Daisy Log File) output into structured formats (CSV, DataFrames) for analysis, visualization, and validation.

## Inputs

| Input | Source | Format | Required |
|-------|--------|--------|----------|
| `.dlf` output files | S4 output | Daisy Log File | Yes |
| Observed data | Field measurements | CSV | For validation |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `harvest.csv` | CSV | Parsed harvest events |
| `field_water.csv` | CSV | Water balance time series |
| `field_nitrogen.csv` | CSV | Nitrogen balance time series |
| `soil_water.csv` | CSV | Soil water content profiles |
| `summary.json` | JSON | Aggregated metrics |

## Procedure

1. **Parse DLF format** — The `.dlf` format has:
   - Header: `dlf-0.0 -- Description` (first line)
   - Metadata: `KEY: value` pairs (VERSION, LOGFILE, RUN, COLUMN, etc.)
   - Separator: line of dashes `----...`
   - Column names: tab-separated names
   - Column units: tab-separated unit strings
   - Data: tab-separated numeric/string values

2. **Extract key variables**:

   **From harvest.dlf**:
   - `sorg_DM` — Grain yield (Mg DM/ha) — the primary crop output
   - `total_DM` — Total aboveground biomass harvested
   - `sorg_N` — Grain nitrogen content (kg N/ha)
   - `harvest_index` — Grain / total DM ratio
   - `water_stress_days` — Days with water limitation
   - `nitrogen_stress_days` — Days with N limitation

   **From field_water.dlf**:
   - `Precipitation`, `Irrigation` — Water inputs
   - `Evapotranspiration` — Water loss to atmosphere
   - `Drain`, `Percolation` — Water loss below root zone
   - `Surface_runoff` — Surface water loss

   **From field_nitrogen.dlf**:
   - `Fertilizer` — Applied N
   - `Harvest_N` — N removed in harvest
   - `Denitrification` — N lost to atmosphere
   - `Leaching` — N lost below root zone
   - `Fixation` — Biological N fixation

   **From crop .dlf**:
   - `DS` — Development stage (0=emergence, 1=flowering, 2=ripe)
   - `LAI` — Leaf area index (m²/m²)
   - `Height` — Crop height (cm)
   - `Root_Depth` — Root depth (cm)

3. **Compute derived metrics**:
   - N Use Efficiency = sorg_DM / Fertilizer_N
   - Water Productivity = sorg_DM / ET
   - N balance = inputs − outputs
   - Water balance = precip + irrigation − ET − drain − runoff

4. **Quality checks**:
   - Yield range: 0–20 Mg DM/ha for cereals
   - ET range: 200–800 mm/year for temperate
   - N leaching: typically < 100 kg N/ha/year for well-managed fields
   - Water balance closure: |residual| < 10 mm/year

## Verification

- [ ] All expected .dlf files parsed without errors
- [ ] No all-NaN columns in output
- [ ] Harvest events present for each sown crop
- [ ] Yield values in expected range for crop type
- [ ] Water balance approximately closes
- [ ] Nitrogen balance approximately closes
- [ ] Time series spans full simulation period

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Tab vs space parsing | Columns misaligned | Use tab-aware parser; DLF uses tabs |
| Header lines counted as data | NaN or string values in numeric columns | Skip to line after `----` separator |
| Unit row parsed as data | First data row has unit strings | Detect and skip the units row |
| Multiple harvest events | Only last event captured | Parse all rows, not just last |
| Missing datetime | Cannot align with observations | Construct from year + month + mday columns |
| Mixed units in same file | Incorrect aggregation | Check units row; each column has own units |
| Flux vs state variables | Wrong temporal aggregation | Fluxes: sum; states: mean |

## Example

```bash
# Parse all outputs
python ki/tools/parse_daisy_output.py \
    --work-dir /tmp/daisy-test \
    --output-dir /tmp/daisy-test/csv

# Parse specific files
python ki/tools/parse_daisy_output.py \
    --work-dir /tmp/daisy-test \
    --output-dir /tmp/daisy-test/csv \
    --files harvest.dlf field_water.dlf field_nitrogen.dlf

# Output:
# csv/harvest.csv
# csv/field_water.csv
# csv/field_nitrogen.csv
# csv/summary.json
```

### Reading DLF in R (alternative)

```r
# Using daisyrVis package
library(daisyrVis)
harvest <- read_dlf("harvest.dlf")
```

### Reading DLF in Python (manual)

```python
import pandas as pd

def read_dlf(path):
    """Quick DLF reader — finds data after ---- separator."""
    with open(path) as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("----"):
            break
    col_names = lines[i+1].strip().split("\t")
    # Skip unit line
    data = pd.read_csv(path, sep="\t", skiprows=i+3,
                        names=col_names, header=None)
    return data
```
