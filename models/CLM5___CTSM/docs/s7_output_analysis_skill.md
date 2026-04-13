# Stage 7: Output Analysis and Validation

## Purpose

Extract, analyse, and validate CLM5 history file outputs. Convert NetCDF
history files to analysis-friendly formats (CSV, JSON), compute summary
statistics, and compare against observations or published reference values.

## Prerequisites

- Stage 6 complete (model execution finished successfully)
- History files available in run directory or short-term archive
- Python environment with `xarray`, `netCDF4`, `pandas`, `matplotlib`

## Inputs

| Input | Description | Location |
|---|---|---|
| History files | CLM5 h0/h1 NetCDF | `$DOUT_S_ROOT/lnd/hist/` or `$RUNDIR/` |
| Observation data | Flux tower, streamflow, etc. | Site-specific |
| Published values | Literature benchmarks | Lawrence et al. 2019 |

### Key CLM5 History Variables

| Variable | Long Name | Units | Category |
|---|---|---|---|
| GPP | Gross Primary Production | gC/m2/s | Carbon |
| NPP | Net Primary Production | gC/m2/s | Carbon |
| NEE | Net Ecosystem Exchange | gC/m2/s | Carbon |
| EFLX_LH_TOT | Total Latent Heat | W/m2 | Energy |
| FSH | Sensible Heat Flux | W/m2 | Energy |
| QRUNOFF | Total Runoff | mm/s | Hydrology |
| H2OSOI | Soil Moisture (per layer) | mm3/mm3 | Hydrology |
| TSOI | Soil Temperature (per layer) | K | Temperature |
| TOTSOMC | Total Soil Organic C | gC/m2 | Carbon Pool |
| TOTVEGC | Total Vegetation C | gC/m2 | Carbon Pool |

### Unit Conversion for Annual Totals

| Variable | Rate Units | Annual Conversion | Annual Units |
|---|---|---|---|
| GPP | gC/m2/s | * 86400 * 365 | gC/m2/yr |
| QRUNOFF | mm/s | * 86400 * 365 | mm/yr |
| EFLX_LH_TOT | W/m2 | (already power) | W/m2 (mean) |

## Procedure

### Step 1: Extract variables to CSV

```bash
python ki/tools/parse_clm_output.py \
    --history-dir /path/to/archive/lnd/hist/ \
    --variables GPP,QRUNOFF,EFLX_LH_TOT,FSH,NEE,TOTSOMC \
    --output results.csv \
    --format csv
```

### Step 2: Quick inspection with xarray

```python
import xarray as xr

ds = xr.open_dataset("case.clm2.h0.2000-01.nc")
print(ds.data_vars)     # List all variables
print(ds["GPP"].attrs)  # Check units and metadata
ds["GPP"].mean(dim=["lat", "lon"]).plot()  # Quick plot
```

### Step 3: Compute summary statistics

```python
import pandas as pd
import numpy as np

df = pd.read_csv("results.csv", parse_dates=["time"], index_col="time")

# Annual mean GPP (convert gC/m2/s → gC/m2/yr)
annual_gpp = df["GPP"].resample("YE").mean() * 86400 * 365
print(f"Mean annual GPP: {annual_gpp.mean():.0f} gC/m2/yr")

# Annual total runoff (convert mm/s → mm/yr)
annual_runoff = df["QRUNOFF"].resample("YE").mean() * 86400 * 365
print(f"Mean annual runoff: {annual_runoff.mean():.0f} mm/yr")
```

### Step 4: Compare to observations

For flux tower sites, compute standard metrics:

```python
from sklearn.metrics import r2_score

# Nash-Sutcliffe Efficiency
def nse(obs, sim):
    return 1 - np.sum((obs - sim)**2) / np.sum((obs - np.mean(obs))**2)

# Kling-Gupta Efficiency
def kge(obs, sim):
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    return 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)

# Percent Bias
def pbias(obs, sim):
    return 100 * np.sum(sim - obs) / np.sum(obs)
```

### Step 5: Create validation figure

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(obs_time, obs_gpp, color="black", label="Observed", linewidth=1)
ax.plot(sim_time, sim_gpp, color="#2563EB", label="CLM5", linewidth=1)
ax.set_ylabel("GPP (gC/m²/yr)")
ax.legend()

# Add metrics box
metrics_text = f"NSE = {nse_val:.2f}\nKGE = {kge_val:.2f}\nPBIAS = {pbias_val:.1f}%"
ax.text(0.98, 0.95, metrics_text, transform=ax.transAxes,
        verticalalignment="top", horizontalalignment="right",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

plt.savefig("validation.png", dpi=150, bbox_inches="tight")
```

## Outputs

| Output | Format | Description |
|---|---|---|
| results.csv | CSV | Time series of extracted variables |
| summary.json | JSON | Metadata, warnings, variable statistics |
| validation.png | PNG | Obs vs sim figure with metrics |

## Verification

1. No NaN-only variables in the output
2. GPP should be 0–3000 gC/m2/yr for vegetated land
3. Runoff should be 0–3000 mm/yr (globally ~500 mm/yr mean)
4. Latent heat should be 0–200 W/m2 annual mean
5. Soil carbon (TOTSOMC) should be 1000–30000 gC/m2 for mature ecosystems
6. Soil temperature seasonal cycle should match air temperature (lagged)

## Common Traps

### Flux rate misinterpretation

CLM5 GPP in gC/m2/s looks tiny (~4e-6). Multiply by 86400*365 to get
meaningful gC/m2/yr values. Forgetting this conversion makes validation
against published values (e.g., GPP ~1200 gC/m2/yr for temperate forest)
impossible.

### noleap calendar alignment

CLM5 uses 365-day years. When comparing to observations with leap years,
dates after Feb 28 will be offset by 1 day in leap years. Use
`cftime`-aware operations or align by day-of-year.

### Grid cell vs point comparison

CLM5 at coarse resolution (e.g., 1 degree) represents ~100 km grid cells.
Comparing to a flux tower (footprint ~1 km) introduces representativeness
errors. Use single-point mode for fair comparisons.

### Fill value contamination

CLM5 uses 1e36 as fill value. If not masked, statistics (mean, std) will
be wildly wrong. Always filter values > 1e35 before analysis.

## Example

Full analysis workflow for Harvard Forest:

```bash
# Extract key variables
python ki/tools/parse_clm_output.py \
    --history-dir ~/archive/US-Ha1/lnd/hist/ \
    --variables GPP,NEE,EFLX_LH_TOT,FSH,QRUNOFF,TOTSOMC,TOTVEGC \
    --output harvard_results.csv

# Compare to AmeriFlux observations
python -c "
import pandas as pd
import numpy as np

sim = pd.read_csv('harvard_results.csv', parse_dates=['time'], index_col='time')
# Convert GPP to gC/m2/yr
sim['GPP_annual'] = sim['GPP'] * 86400 * 365

print(f'Mean GPP: {sim[\"GPP_annual\"].mean():.0f} gC/m2/yr')
print(f'Expected: ~1200 gC/m2/yr (Urbanski et al. 2007)')
"
```
