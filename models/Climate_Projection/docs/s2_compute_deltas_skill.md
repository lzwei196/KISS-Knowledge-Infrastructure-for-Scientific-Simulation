# Climate Change Delta Computation — Skill Document

> **Stage ID**: s2_compute_deltas
> **Pipeline order**: 2 of 4
> **Depends on**: s1_extract_cmip (extracted CMIP6 data)

## Purpose

Compute monthly climate change signals (deltas) by comparing CMIP6 future climatology against CMIP6 historical climatology. These deltas encode the projected change in precipitation and temperature for each month and grid cell, enabling the delta-change method for generating future VIC forcing.

## Prerequisites

Before starting this stage, verify:

- [ ] CMIP6 historical (r1) data extracted: `cmip6_extracted/{MODEL}_r1_pr_{basin}.nc`
- [ ] CMIP6 future scenario data extracted: `cmip6_extracted/{MODEL}_{ssp}_pr_{basin}.nc`
- [ ] Python environment activated

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| HIST_DIR | directory | Stage 1 | Directory with `*_r1_*_{basin}.nc` files |
| FUTURE_DIR | directory | Stage 1 | Directory with `*_{ssp}_*_{basin}.nc` files |
| REF_PERIOD | year range | Practitioner choice | Historical reference (default: 1981-2010) |
| FUTURE_PERIOD | year range | User choice | Future target window (e.g., 2041-2070) |

### Choosing Reference and Future Periods

| Future window | Common name | Use case |
|---------------|------------|----------|
| 2021-2050 | Near-term | Adaptation planning, infrastructure |
| 2041-2070 | Mid-century | Policy analysis (default recommendation) |
| 2071-2099 | End-century | Long-term risk assessment |

The reference period should be **30 years within 1961-2014** for statistical robustness. The standard is **1981-2010**.

## Procedure

### Step 1: Run delta computation

```bash
python skills/climate-projection/tools/s2_compute_deltas/compute_climate_deltas.py \
  outputs/{basin}/climate_projection/cmip6_extracted \
  outputs/{basin}/climate_projection/cmip6_extracted \
  {MODEL_NAME} {SCENARIO} {basin} \
  1981-2010 2041-2070 \
  outputs/{basin}/climate_projection/deltas
```

**Expected result**: One NetCDF file with 3 variables × 12 months × N cells:
- `delta_pr` (ratio, typically 0.7-1.5 for most China basins)
- `delta_tasmax` (degC, typically +1 to +6 depending on scenario/period)
- `delta_tasmin` (degC, similar range)

**Runtime**: < 1 minute.

### Step 2: Inspect delta values

Check that delta magnitudes are physically reasonable:

```python
import xarray as xr
ds = xr.open_dataset("outputs/{basin}/climate_projection/deltas/{MODEL}_{ssp}_deltas_{basin}_2041-2070.nc")
print("Precip ratio range:", ds.delta_pr.values.min(), "-", ds.delta_pr.values.max())
print("Tasmax delta range:", ds.delta_tasmax.values.min(), "-", ds.delta_tasmax.values.max())
print("Tasmin delta range:", ds.delta_tasmin.values.min(), "-", ds.delta_tasmin.values.max())
```

**Expected ranges for China (mid-century SSP2-4.5)**:
- delta_pr: 0.8-1.3 (humid) to 0.5-2.0 (arid)
- delta_tasmax: +1.0 to +3.5 °C
- delta_tasmin: +1.0 to +4.0 °C

**If delta_pr is exactly 1.0 everywhere**: Something went wrong — historical and future are identical. See dt_cc_004.

**If temperature deltas are > 8°C**: Check if you're comparing the right periods. End-century SSP5-8.5 can reach 6-8°C, but mid-century should be lower.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Delta file | `deltas/{MODEL}_{ssp}_deltas_{basin}_{start}-{end}.nc` | 3 variables, dims (month=12, cell=N), delta_pr > 0 |

## Validation Checks

1. **Precipitation ratios are positive**: All delta_pr values must be > 0
2. **Temperature deltas are non-zero**: If all zeros, reference and future periods likely overlap incorrectly
3. **Seasonal pattern**: Deltas should show month-to-month variation (not flat)

## Common Pitfalls

> **PITFALL**: Reference period extends beyond CMIP6 historical
> The r1 historical run ends at 2014-12-31. If REF_PERIOD includes years after 2014, the climatology will be computed from truncated data.
> **Do this instead**: Use 1981-2010 (the WMO standard 30-year reference).

> **PITFALL**: Dry-month precipitation ratio explosion
> In arid months with near-zero historical precip, even small future precip produces huge ratios (e.g., 100x). The tool caps ratios at 5.0 and floors historical at 0.1 mm/day.
> See diagnostic triplet dt_cc_005.

---

*This skill document is part of the climate-projection knowledge infrastructure.*
*Stage 2 of 4 | Tools used: compute_climate_deltas | Related triplets: dt_cc_004, dt_cc_005*
