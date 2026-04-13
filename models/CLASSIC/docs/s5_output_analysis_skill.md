# Stage 5: Output Parsing and Analysis

## Purpose

Extract CLASSIC netCDF output variables into CSV format for analysis, plotting, and comparison with observations. Compute summary diagnostics including carbon budget balance, energy closure, and water balance.

## Inputs

| Input | Description |
|-------|-------------|
| CLASSIC output netCDFs | `outputFiles/*_yr.nc`, `*_mo.nc`, `*_d.nc`, `*_hh.nc` |
| Output variable descriptors XML | Defines variable metadata |
| Observation data (optional) | For validation comparison |

## Outputs

| Output | Description |
|--------|-------------|
| CSV time series | Extracted variable time series |
| Diagnostics JSON | Summary statistics and budget checks |
| Validation figures | Comparison plots (if observations provided) |

## Procedure

### 1. Scan output directory

```python
import os
nc_files = [f for f in os.listdir("outputFiles") if f.endswith(".nc")]
# Categorize by frequency
annual = [f for f in nc_files if "_yr" in f]
monthly = [f for f in nc_files if "_mo" in f]
```

### 2. Extract variables

```bash
python ki/tools/parse_classic_output.py \
    --output_dir outputFiles \
    --variables "gpp,npp,nep,rh,ra,lai,mrro,hfss,hfls,snw" \
    --frequency monthly \
    --csv_out results_monthly.csv \
    --compute_diagnostics
```

### 3. Check carbon budget

For CTEM runs, verify: **NEP ≈ GPP - Ra - Rh** (with spinfast=1)

```python
import pandas as pd
df = pd.read_csv("results_monthly.csv", index_col=0, parse_dates=True)
annual = df.resample("Y").sum()
print("GPP:", annual["gpp"].mean(), "kgC/m2/yr")
print("Ra:", annual["ra"].mean())
print("Rh:", annual["rh"].mean())
print("NEP:", annual["nep"].mean())
print("Expected NEP:", (annual["gpp"] - annual["ra"] - annual["rh"]).mean())
```

### 4. Check energy balance

Verify: **Rnet ≈ H + LE + G**

```python
# rss + rls ≈ hfss + hfls + ground heat flux
rnet = df["rss"] + df["rls"]  # net radiation
turbulent = df["hfss"] + df["hfls"]
residual = rnet - turbulent  # should be ~ ground heat flux
print("Energy residual (ground heat flux):", residual.mean(), "W/m2")
```

### 5. Check water balance

```python
# Total runoff should be reasonable fraction of precipitation
print("Annual runoff:", annual["mrro"].mean() * 86400 * 365, "mm/yr")
```

### 6. Convert units for comparison

CLASSIC monthly outputs are typically accumulated (kgC/m2/month for carbon, kg/m2/s for water). Common conversions:

| Variable | CLASSIC units | Common comparison units | Conversion |
|----------|--------------|----------------------|------------|
| GPP | kgC/m2/month | gC/m2/day | * 1000 / days_in_month |
| Runoff | kg/m2/s | mm/day | * 86400 |
| ET | kg/m2/s | mm/day | * 86400 |
| LAI | m2/m2 | m2/m2 | no conversion |

### 7. Use built-in CSV converter (alternative)

```bash
# CLASSIC includes a simple converter
python tools/convertOutputToCSV/convertNetCDFOutputToCSV.py outputFiles/gpp_mo.nc
# Creates outputFiles/gpp_mo.csv
```

## Verification

```python
# Check output is physically reasonable
import pandas as pd
df = pd.read_csv("results_monthly.csv", index_col=0, parse_dates=True)

# GPP should be positive
assert (df["gpp"] >= 0).all(), "GPP has negative values!"

# LAI should be 0-15
assert df["lai"].max() < 15, f"LAI unreasonably high: {df['lai'].max()}"

# Snow should be >= 0
if "snw" in df:
    assert (df["snw"] >= 0).all(), "Negative snow!"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| No output files created | Output year range outside simulation period | Check JMOSTY, JDSTY etc. |
| All values zero | CTEM off but expecting carbon outputs | Turn ctem_on = .true. |
| GPP negative | Impossible — indicates wrong variable | Check variable name in XML |
| Runoff >> precipitation | Wrong precipitation units in forcing | Check pre.nc units (kg/m2/s) |
| NEP != GPP - Ra - Rh | spinfast > 1 (accelerated C) | Set spinfast = 1 for budget check |
| Time axis wrong | Time encoding mismatch | Use classic_time_to_datetime() |
| Per-PFT files confusing | Extra dimensions | Specify lat_idx, lon_idx, PFT index |

## Example

```bash
# Extract monthly carbon fluxes
python ki/tools/parse_classic_output.py \
    --output_dir outputFiles \
    --variables "gpp,npp,nep,rh,ra,cVeg,cSoil" \
    --frequency annual \
    --csv_out carbon_annual.csv \
    --compute_diagnostics

# Plot
python -c "
import pandas as pd
import matplotlib.pyplot as plt
df = pd.read_csv('carbon_annual.csv', index_col=0, parse_dates=True)
df[['gpp','npp','nep']].plot()
plt.ylabel('kgC/m2/yr')
plt.title('CLASSIC Carbon Fluxes')
plt.savefig('carbon_fluxes.png', dpi=150)
"
```
