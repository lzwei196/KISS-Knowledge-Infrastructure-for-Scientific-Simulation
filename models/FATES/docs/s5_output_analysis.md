# S5: FATES Output Analysis

## Purpose

Parse, analyze, and visualize FATES simulation output from CLM/ELM NetCDF history
files. Extract time series of key ecosystem variables, compute performance metrics
against observations, and generate diagnostic plots.

## Inputs

| Input | Format | Source | Required |
|-------|--------|--------|----------|
| CLM history files | NetCDF | `*.clm2.h0.*.nc` from case run directory | Yes |
| Observation data | CSV | Field measurements, flux tower, remote sensing | Optional |
| Variable list | String | FATES variable names | Yes |

### Key FATES Output Variables

**Carbon Pools** (kgC/m²):
- `FATES_VEGC` — Total vegetation carbon (most commonly validated)
- `FATES_LEAFC` — Leaf carbon pool
- `FATES_SAPWOODC` — Sapwood carbon
- `FATES_STRUCTC` — Structural (dead) wood carbon
- `FATES_STOREC` — Storage carbon
- `FATES_FROOTC` — Fine root carbon
- `FATES_CWDC` — Coarse woody debris
- `FATES_LITTERC` — Litter carbon

**Carbon Fluxes** (kgC/m²/s — convert for analysis!):
- `FATES_GPP` — Gross primary production
- `FATES_NPP` — Net primary production
- `FATES_AUTORESP` — Autotrophic respiration
- `FATES_HETRESP` — Heterotrophic respiration (if coupled)

**Structural Variables**:
- `FATES_LAI` — Leaf area index (m²/m²)
- `FATES_NPLANT` — Stem density (stems/m²)
- `FATES_CANOPY_AREA` — Canopy area fraction
- `FATES_DDBH_CANOPY_SZPF` — Diameter growth by size class and PFT

**Disturbance**:
- `FATES_MORTALITY` — Total mortality rate (stems/m²/yr)
- `FATES_RECRUITMENT` — Recruitment rate (stems/m²/yr)
- `FATES_DISTURBANCE_RATE_FIRE` — Fire disturbance rate (fraction/yr)

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Time series CSV | CSV | Extracted variables with units |
| Diagnostic plots | PNG | Time series with optional observations |
| Performance metrics | JSON | NSE, KGE, RMSE, PBIAS, r² |

## Procedure

### Step 1: Extract Variables

```bash
python tools/parse_fates_output.py \
    --input /path/to/run/*.clm2.h0.*.nc \
    --variables FATES_GPP,FATES_LAI,FATES_VEGC,FATES_NPP \
    --output fates_timeseries.csv
```

### Step 2: Generate Plots

```bash
python tools/parse_fates_output.py \
    --input /path/to/run/*.clm2.h0.*.nc \
    --variables FATES_GPP,FATES_LAI \
    --plot fates_diagnostics.png
```

### Step 3: Compare with Observations

```bash
python tools/parse_fates_output.py \
    --input /path/to/run/*.clm2.h0.*.nc \
    --variables FATES_GPP \
    --obs-file tower_gpp.csv --obs-column GPP_gC_m2_day \
    --metrics \
    --output comparison.csv --plot comparison.png
```

### Step 4: Unit Conversion for Analysis

FATES outputs carbon fluxes in **kgC/m²/s**. For comparison with most published
data and flux tower observations, convert:

| Original | Target | Factor | Common Use |
|----------|--------|--------|------------|
| kgC/m²/s | gC/m²/day | × 1000 × 86400 | Daily flux analysis |
| kgC/m²/s | tC/ha/yr | × 86400 × 365 × 10 | Annual ecosystem budgets |
| kgC/m²/s | µmol CO₂/m²/s | × 1e6 / 12.011 | Flux tower comparison |
| stems/m² | stems/ha | × 10000 | Forest inventory |

**The parser applies conversions automatically with `--convert-units` (default).**

### Performance Metrics

| Metric | Formula | Perfect Score | Interpretation |
|--------|---------|---------------|----------------|
| NSE | 1 - Σ(sim-obs)²/Σ(obs-mean)² | 1.0 | >0.5 = acceptable |
| KGE | 1 - √[(r-1)²+(α-1)²+(β-1)²] | 1.0 | >0.5 = acceptable |
| RMSE | √[mean((sim-obs)²)] | 0 | Lower is better |
| PBIAS | 100×Σ(sim-obs)/Σobs | 0% | ±10% = good |
| r² | Correlation² | 1.0 | >0.6 = acceptable |

## Verification

- [ ] Extracted variables are non-zero and non-NaN
- [ ] GPP has realistic range (0–30 gC/m²/day for most ecosystems)
- [ ] LAI has realistic range (0–12 m²/m²)
- [ ] VEGC has realistic range (0–30 kgC/m² for forests)
- [ ] Time series shows expected seasonal cycle (if applicable)
- [ ] Unit conversions applied correctly (check magnitude)

## Traps

| Trap ID | Description | Detection |
|---------|-------------|-----------|
| dt_001 | Biomass per individual vs per m² confusion | Magnitude check |
| dt_004 | GPP unit conversion chain error (kgC/m²/s → gC/m²/day) | Range check |
| dt_002 | Stem density stems/m² vs stems/ha | Magnitude check |

### Critical: FATES_GPP Unit Conversion

The most common error when analyzing FATES output is incorrect unit conversion
of carbon fluxes. FATES outputs GPP in **kgC/m²/s**:

```python
# WRONG — forgot the 1000× factor (kg to g)
gpp_daily = gpp_kgC_m2_s * 86400  # This gives kgC/m²/day, not gC/m²/day!

# CORRECT — full conversion
gpp_daily_gC = gpp_kgC_m2_s * 1000 * 86400  # gC/m²/day

# Typical result check:
# Tropical forest GPP: ~5-15 gC/m²/day (monthly mean)
# If your values are 0.005-0.015, you forgot the ×1000
# If your values are 5000-15000, you applied ×1000 twice
```

### Critical: All-Zero Output

If all FATES variables are zero, the most common causes are:
1. **Bare ground initialization**: FATES starts with no vegetation by default.
   Allow 50-100 years of spinup, or use inventory initialization.
2. **Wrong compset**: Ensure `use_fates = .true.` in `user_nl_clm`
3. **Missing seed supplement**: Set `fates_recruit_seed_supplement > 0` to
   enable recruitment from bare ground.

## Example

**Scenario**: Analyze a 10-year FATES run at BCI and compare GPP with eddy
covariance observations.

```bash
# Extract GPP and LAI time series
python tools/parse_fates_output.py \
    --input ~/cases/bci_fates/run/*.clm2.h0.*.nc \
    --variables FATES_GPP,FATES_LAI,FATES_VEGC,FATES_NPLANT \
    --output bci_fates_results.csv \
    --plot bci_diagnostics.png

# Compare GPP with tower data
python tools/parse_fates_output.py \
    --input ~/cases/bci_fates/run/*.clm2.h0.*.nc \
    --variables FATES_GPP \
    --obs-file bci_tower_gpp.csv --obs-column GPP_gC_m2_day \
    --metrics \
    --plot bci_gpp_comparison.png

# Expected output:
# {
#   "r": 0.72,
#   "nse": 0.55,
#   "kge": 0.61,
#   "rmse": 2.1,
#   "pbias_pct": -8.5,
#   "mean_sim": 8.7,
#   "mean_obs": 9.5
# }
```
