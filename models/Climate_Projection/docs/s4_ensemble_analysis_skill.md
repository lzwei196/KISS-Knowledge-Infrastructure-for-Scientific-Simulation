# Ensemble VIC Run & Analysis — Skill Document

> **Stage ID**: s4_ensemble_analysis
> **Pipeline order**: 4 of 4
> **Depends on**: s3_apply_deltas (projected forcing), VIC calibrated parameters

## Purpose

Run VIC with projected forcing for multiple CMIP6 models and SSP scenarios, then compare historical vs future hydrology to quantify climate change impacts. This produces multi-model ensemble results showing projected changes in streamflow, flood risk, drought risk, and water balance components.

## Prerequisites

Before starting this stage, verify:

- [ ] Projected forcing files generated for at least 1 model × 1 scenario
- [ ] VIC global parameter file from baseline run (for calibrated parameters)
- [ ] Routing parameters from baseline run (flow direction, UH, station location)
- [ ] Python environment activated

## Procedure

### Step 1: Prepare VIC global parameter file for projected run

Copy the baseline global parameter file and modify:

```bash
cp outputs/{basin}/vic_temp/global_param_{basin}.txt \
   outputs/{basin}/climate_projection/global_param_{basin}_{MODEL}_{ssp}.txt
```

Edit the copy:
- `STARTYEAR` → future start (e.g., 2041)
- `ENDYEAR` → future end (e.g., 2070)
- `FORCING1` → `outputs/{basin}/climate_projection/forcing_final_{MODEL}_{ssp}/{prefix}`
- `RESULT_DIR` → `outputs/{basin}/climate_projection/vic_result_{MODEL}_{ssp}/`
- Keep all calibrated soil/veg parameters **unchanged**

### Step 2: Run VIC for each model × scenario

```bash
mkdir -p outputs/{basin}/climate_projection/vic_result_{MODEL}_{ssp}

/mnt/disk1/Hydrocraft_server/model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe \
  -g outputs/{basin}/climate_projection/global_param_{basin}_{MODEL}_{ssp}.txt
```

**Runtime**: Same as baseline VIC run (1-20 minutes depending on grid cells and years).

### Step 3: Run routing with projected VIC output

Follow the same routing workflow (Lohmann or CaMa-Flood) as the baseline run, pointing to the projected VIC result directory.

### Step 4: Multi-model ensemble analysis

For a robust climate change assessment, run at least **5 models × 3 scenarios**. Recommended ensemble:

| Model | Type | Origin |
|-------|------|--------|
| ACCESS-CM2 | GCM | Australia |
| BCC-CSM2-MR | GCM | China |
| EC-Earth3 | ESM | Europe |
| MIROC6 | GCM | Japan |
| MRI-ESM2-0 | GCM | Japan |

### Step 5: Generate comparison plots

Key analyses:

1. **Annual discharge change**: Box plots of mean annual discharge across models
   - Historical mean vs SSP126/245/585 ensemble median + spread

2. **Seasonal cycle change**: Monthly hydrograph comparison
   - Historical climatology vs future climatology (ensemble mean ± 1 std)

3. **Flood frequency change**: Annual maximum discharge distribution
   - Compare return periods (10-year, 50-year, 100-year floods)

4. **Water balance change**: ET, soil moisture, runoff partitioning
   - How does increased temperature affect ET and runoff ratio?

5. **Uncertainty decomposition**: Model spread vs scenario spread
   - Which source of uncertainty dominates at different time horizons?

```bash
python skills/plot/plot_climate_projection.py \
  --historical_discharge outputs/{basin}/routing_result/{station}.day \
  --projected_dir outputs/{basin}/climate_projection/ \
  --models ACCESS-CM2,BCC-CSM2-MR,EC-Earth3,MIROC6,MRI-ESM2-0 \
  --scenarios 126,245,585 \
  --output outputs/{basin}/climate_projection/ensemble_comparison.png \
  --title "{Basin Name} Climate Change Impact"
```

## Expected Outputs

| Output | Path | Description |
|--------|------|-------------|
| VIC results per model | `climate_projection/vic_result_{MODEL}_{ssp}/` | Gridded runoff/ET/SM |
| Routed discharge per model | `climate_projection/routing_{MODEL}_{ssp}/` | Daily discharge at outlet |
| Ensemble comparison plot | `climate_projection/ensemble_comparison.png` | Multi-model multi-scenario |
| Summary statistics | `climate_projection/change_summary.csv` | % change in mean Q, Q_max, Q_min |

## Validation Checks

1. **Ensemble spread**: Models should show different magnitudes but generally consistent direction of change
2. **Physical consistency**: Higher SSP should show larger changes than lower SSP
3. **Scenario ordering**: SSP585 changes > SSP245 changes > SSP126 changes (on average)
4. **Conservation**: Total water balance should close (P ≈ ET + Q + dS/dt)

## Common Pitfalls

> **PITFALL**: Using uncalibrated parameters for projection
> Climate change projections with uncalibrated VIC parameters will amplify errors. The relative changes (future/historical) are more robust than absolute values, but calibration is still strongly recommended.
> **Do this instead**: Calibrate VIC against observed discharge first, then use calibrated parameters for all projection runs.

> **PITFALL**: Interpreting single-model results as definitive
> One CMIP6 model is one realisation of possible future climate. Always use an ensemble of at least 5 models to quantify uncertainty.
> **Do this instead**: Run the recommended 5-model ensemble and report median ± spread.

---

*This skill document is part of the climate-projection knowledge infrastructure.*
*Stage 4 of 4 | Tools used: VIC, routing (from baseline skills) | Related triplets: dt_cc_008*
