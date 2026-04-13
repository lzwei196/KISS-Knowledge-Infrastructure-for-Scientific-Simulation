# Stage 5: Output Analysis and Validation

## Purpose

Parse HydroTrend output files, compute summary statistics, validate against
observed data, and generate diagnostic figures.

## Inputs

HydroTrend output files:

| File | Content | Units |
|------|---------|-------|
| `{PREFIX}ASCII.Q` | Daily water discharge | m³/s |
| `{PREFIX}ASCII.QS` | Daily suspended sediment | kg/s |
| `{PREFIX}ASCII.QB` | Daily bedload | kg/s |
| `{PREFIX}ASCII.CS` | Daily sediment concentration | kg/m³ |
| `{PREFIX}ASCII.VWD` | Daily velocity, width, depth | m/s, m, m |
| `{PREFIX}.TRN3` | Annual comprehensive summary | mixed |

Optional: Observed data CSV for validation.

## Outputs

- Combined CSV: all daily variables with dates
- JSON summary: statistics, annual aggregates, metrics
- Validation figure (if observed data provided)

## Procedure

### Step 1: Parse output files

```bash
python parse_hydrotrend_output.py \
    --out-dir ./HYDRO_OUTPUT \
    --prefix HYDRO \
    --start-year 1908 \
    --output-csv results.csv \
    --output-json summary.json
```

### Step 2: Compute statistics

Key metrics to compute:
- **Mean annual discharge** (m³/s): Should match expectations for basin size
- **Annual water yield** (km³/yr): `Q_mean × 365.25 × 86400 / 1e9`
- **Runoff ratio**: Annual yield / (P × Area) — typically 0.2–0.8
- **Sediment yield** (t/km²/yr): `Qs_annual × 86400 × 365 / (Area × 1e6)`
- **Peak-to-mean ratio**: Q_max / Q_mean — typically 5–50

### Step 3: Validate against observations

**Hydrological metrics**:
- **NSE** (Nash-Sutcliffe Efficiency): > 0.5 is acceptable, > 0.7 is good
- **KGE** (Kling-Gupta Efficiency): > 0.5 is acceptable
- **PBIAS** (Percent Bias): |PBIAS| < 25% is acceptable

**Sediment metrics**:
- Compare annual sediment load to published values
- Compare to BQART global relationships
- Check sediment concentration range (typically 0.01–100 kg/m³)

### Step 4: Diagnostic figures

**Figure 1: Discharge time series**
- Observed (black) vs simulated (#2563EB)
- Monthly or annual averages for long simulations

**Figure 2: Flow duration curve**
- Sort Q descending, plot exceedance probability
- Compare observed vs simulated shapes

**Figure 3: Sediment load**
- Annual Qs vs Q scatter plot
- Rating curve comparison

**Figure 4: Monthly climatology**
- 12-month average Q, Qs
- Compare simulated seasonality to observed

## Verification

- [ ] All output files contain the expected number of lines
  - For N years: Q file should have N × 365 lines (approx)
- [ ] Discharge values are non-negative
- [ ] No NaN values in output
- [ ] Mean Q is reasonable for basin area and precipitation
- [ ] Sediment concentration typically 0.001–100 kg/m³
- [ ] Annual sediment yield in range for geomorphic setting
- [ ] Runoff ratio between 0 and 1

## Traps

### Empty output files
If output files are empty or missing, check:
1. Line 2 of HYDRO.IN — must be "ON" for ASCII output
2. Output directory exists and is writable
3. Model completed without crash (check return code)

### Date alignment
HydroTrend output has no date column. Dates must be reconstructed from the
start year (line 5 of HYDRO.IN) assuming 365 days per year. The model does
NOT use leap years — every year has exactly 365 days.

### Unrealistic sediment values
If Qs is extremely high or low:
- Check area units in hypsometry (km² not m²)
- Check BQART lithology/anthropogenic factors
- Check temperature — BQART doubles Qsbar below 2°C
- Check reservoir trapping (TE can mask true loads)

### Monthly vs daily interpretation
When timestep is set to "M" (monthly), output values represent monthly
averages, not monthly totals. Each line is still one time step, but
represents the average over that month.

## Example

```bash
# Parse and compute metrics
python parse_hydrotrend_output.py \
    --out-dir ./HYDRO_OUTPUT \
    --prefix HYDRO \
    --start-year 1908 \
    --observed observed_monthly_Q.csv \
    --obs-date-col date \
    --obs-value-col Q_m3s \
    --output-csv results.csv \
    --output-json summary.json

# Check results
python -c "
import json
with open('summary.json') as f:
    d = json.load(f)
print(f'Mean Q: {d[\"discharge_stats\"][\"mean_m3s\"]} m³/s')
print(f'NSE: {d[\"metrics\"].get(\"NSE\", \"N/A\")}')
print(f'KGE: {d[\"metrics\"].get(\"KGE\", \"N/A\")}')
"
```

## Published Reference Values

### Global sediment yield ranges (Syvitski & Milliman, 2007)
| Setting | Yield (t/km²/yr) |
|---------|------------------|
| Arctic/glacial | 50–500 |
| Temperate humid | 100–1000 |
| Tropical humid | 200–5000 |
| Arid | 10–100 |
| Active tectonic | 1000–10000+ |

### Hydraulic geometry exponents (Leopold & Maddock, 1953)
| Parameter | Typical range |
|-----------|--------------|
| Velocity exponent (m) | 0.3–0.6 |
| Width exponent (b) | 0.2–0.5 |
| Depth exponent (f) | 0.1–0.4 |
| Sum m+b+f | = 1.0 |
