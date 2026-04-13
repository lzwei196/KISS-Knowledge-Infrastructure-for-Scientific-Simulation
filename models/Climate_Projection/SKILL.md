---
name: climate-projection
description: Climate change impact assessment using CMIP6 data. Two extraction paths — China (26 models, local files) or Global (34 models, NASA NEX-GDDP-CMIP6 API). Computes delta-change signals, generates future VIC forcing, runs multi-model ensemble analysis.
---

> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

---



# Climate Change Projection — Knowledge Infrastructure

**Part of HydroCraft** — AI-driven distributed hydrological simulation framework by the Jianyun Zhang Research Group.

This knowledge infrastructure enables an AI agent to autonomously run climate change impact assessments on any basin already set up in HydroCraft. It takes a calibrated (or uncalibrated) VIC model and produces projected future hydrology under CMIP6 climate scenarios.

---

## When to Use This Skill

Use this skill **after** the VIC model has been set up and (ideally) calibrated for a basin. It is the natural next step:

```
VIC Setup → Calibration → Climate Change Projection ← YOU ARE HERE
```

The user may ask for this by saying:
- "Run climate change projections"
- "What will discharge look like under SSP2-4.5?"
- "Climate change impact on this basin"
- "Future hydrology" / "CMIP6 analysis"

---

## Pipeline Overview

| Stage | Tool | Skill Document | Description |
|-------|------|----------------|-------------|
| **S1** | `extract_cmip6_basin` (China) OR `fetch_nex_gddp_global` (global) | `docs/s1_extract_cmip_skill.md` | Extract CMIP6 data for basin grid cells |
| **S2** | `compute_climate_deltas` | `docs/s2_compute_deltas_skill.md` | Compute monthly change factors (future vs historical) |
| **S3** | `apply_deltas_forcing` | `docs/s3_apply_deltas_skill.md` | Apply deltas to baseline CMFD/MSWX forcing |
| **S4** | *(VIC + routing from baseline)* | `docs/s4_ensemble_analysis_skill.md` | Run VIC ensemble & compare historical vs future |

**Dependencies**: S1 → S2 → S3 → S4. Each stage must complete before the next begins.

---

## Choosing an Extraction Method (S1)

| Method | Script | Coverage | Models | When to use |
|--------|--------|----------|--------|-------------|
| **China local** | `extract_cmip6_basin.py` | China only | 26 | Chinese basins (fastest, ~3 min) |
| **Global API** | `fetch_nex_gddp_global.py` | Worldwide | 34 | Any basin, no local data needed (~15 min) |

Both produce **identical output format** — downstream tools (S2-S4) work unchanged.

## Quick Start

### Option A: China (local files)
```bash
source /mnt/disk1/Hydrocraft_server/python_env/bin/activate
BASIN="bengbu"
MODEL="ACCESS-CM2"
SSP="245"

# S1: Extract CMIP6 data (historical + future)
python skills/climate-projection/tools/s1_extract_cmip/extract_cmip6_basin.py \
  /mnt/disk3/CMIP_China/Cmip6BaisCorrect_for_China \
  outputs/${BASIN}/vic_temp/grid/basin_grid.nc \
  ${MODEL} r1 outputs/${BASIN}/climate_projection/cmip6_extracted ${BASIN}

python skills/climate-projection/tools/s1_extract_cmip/extract_cmip6_basin.py \
  /mnt/disk3/CMIP_China/Cmip6BaisCorrect_for_China \
  outputs/${BASIN}/vic_temp/grid/basin_grid.nc \
  ${MODEL} ${SSP} outputs/${BASIN}/climate_projection/cmip6_extracted ${BASIN}

# S2: Compute deltas (1981-2010 baseline vs 2041-2070 future)
python skills/climate-projection/tools/s2_compute_deltas/compute_climate_deltas.py \
  outputs/${BASIN}/climate_projection/cmip6_extracted \
  outputs/${BASIN}/climate_projection/cmip6_extracted \
  ${MODEL} ${SSP} ${BASIN} 1981-2010 2041-2070 \
  outputs/${BASIN}/climate_projection/deltas

# S3: Apply deltas to baseline forcing
python skills/climate-projection/tools/s3_apply_deltas/apply_deltas_forcing.py \
  outputs/${BASIN}/vic_temp/forcing/forcing_1d \
  outputs/${BASIN}/climate_projection/deltas/${MODEL}_${SSP}_deltas_${BASIN}_2041-2070.nc \
  outputs/${BASIN}/vic_temp/grid/basin_grid.nc \
  outputs/${BASIN}/climate_projection/forcing_${MODEL}_${SSP} \
  ${BASIN} ${MODEL} ${SSP} 2041 2070

# S4: Run VIC + routing with projected forcing (see s4 skill document)
```

### Option B: Global (NASA NEX-GDDP-CMIP6 API, any basin worldwide)
```bash
source /mnt/disk1/Hydrocraft_server/python_env/bin/activate
BASIN="koksilah"
MODEL="ACCESS-CM2"

# S1: Fetch CMIP6 data via THREDDS (no local files needed)
python skills/climate-projection/tools/s1_extract_cmip/fetch_nex_gddp_global.py \
  --grid_nc outputs/${BASIN}/vic_temp/grid/basin_grid.nc \
  --model ${MODEL} --scenario historical --years 1981-2010 \
  --output_dir outputs/${BASIN}/climate_projection/cmip6_extracted \
  --basin_name ${BASIN}

python skills/climate-projection/tools/s1_extract_cmip/fetch_nex_gddp_global.py \
  --grid_nc outputs/${BASIN}/vic_temp/grid/basin_grid.nc \
  --model ${MODEL} --scenario ssp245 --years 2041-2070 \
  --output_dir outputs/${BASIN}/climate_projection/cmip6_extracted \
  --basin_name ${BASIN}

# S2-S4: Same as Option A (output format is identical)

# Multi-model ensemble (recommended 5 models):
python skills/climate-projection/tools/s1_extract_cmip/fetch_nex_gddp_global.py \
  --grid_nc outputs/${BASIN}/vic_temp/grid/basin_grid.nc \
  --models recommended --scenario ssp245 --years 2041-2070 \
  --output_dir outputs/${BASIN}/climate_projection/cmip6_extracted \
  --basin_name ${BASIN}
```

---

## CMIP6 Data Reference

### Location
`/mnt/disk3/CMIP_China/Cmip6BaisCorrect_for_China/`

### Structure
```
Cmip6BaisCorrect_for_China/
├── pr/               # Precipitation (mm/day)
│   ├── r1/           # Historical (1961-2014)
│   ├── 126/          # SSP1-2.6 (2015-2099)
│   ├── 245/          # SSP2-4.5 (2015-2099)
│   └── 585/          # SSP5-8.5 (2015-2099)
├── tasmax/            # Daily max temperature (deg C)
│   └── (same structure)
└── tasmin/            # Daily min temperature (deg C)
    └── (same structure)
```

### File Format
- Tab-separated text, ~650 MB per file
- Row 1: `NaN NaN NaN [longitudes for 4,163 cells]`
- Row 2: `NaN NaN NaN [latitudes for 4,163 cells]`
- Row 3+: `Year Month Day [daily values for 4,163 cells]`
- Coverage: China (73.75-135.25E, 15.25-53.75N), 0.25-degree grid
- Units: already bias-corrected, °C for temperature, mm/day for precipitation

### Available Models (26 with all 3 variables)

ACCESS-CM2, ACCESS-ESM1-5, BCC-CSM2-MR, CanESM5, CESM2, CMCC-ESM2, CNRM-ESM2-1, EC-Earth3, EC-Earth3-Veg, EC-Earth3-Veg-LR, FGOALS-g3, GFDL-ESM4, INM-CM4-8, INM-CM5-0, IPSL-CM6A-LR, KIOST-ESM, MIROC6, MPI-ESM1-2-HR, MPI-ESM1-2-LR, MRI-ESM2-0, NESM3, NorESM2-LM, NorESM2-MM, TaiESM1, UKESM1-0-LL, CNRM-CM6-1 *(pr only — has tasmax/tasmin too)*, KACE-1-0-G *(pr only in some directories)*

**Recommended 5-model ensemble**: ACCESS-CM2, BCC-CSM2-MR, EC-Earth3, MIROC6, MRI-ESM2-0

### Scenarios

| Code | CMIP6 Name | Period | Radiative Forcing | Description |
|------|-----------|--------|-------------------|-------------|
| `r1` | Historical | 1961-2014 | Observed | Reference baseline |
| `126` | SSP1-2.6 | 2015-2099 | 2.6 W/m² | Sustainability (Paris-aligned) |
| `245` | SSP2-4.5 | 2015-2099 | 4.5 W/m² | Middle of the road |
| `585` | SSP5-8.5 | 2015-2099 | 8.5 W/m² | Fossil-fuel intensive |

---

## Critical Domain Knowledge

### Why Delta Change Method?

VIC needs 7 forcing variables (temp, prec, pres, srad, lrad, wind, shum), but CMIP6 only provides 3 (pr, tasmax, tasmin). The delta-change method preserves all 7 baseline variables while incorporating projected climate change:

- **Temperature**: Additive delta → `T_future = T_baseline + delta_T`
- **Precipitation**: Multiplicative ratio → `P_future = P_baseline × ratio_P`
- **Other variables**: Unchanged from baseline (wind, pressure, radiation, humidity change less and are not available from CMIP6)

### Key Assumptions

1. **Stationarity of sub-daily patterns**: The diurnal cycle and weather sequences from the baseline period are assumed to persist under future climate. Only monthly means change.
2. **Limited to China**: The bias-corrected dataset covers mainland China only.
3. **Baseline period matters**: The CMFD/MSWX forcing used as baseline determines the sub-daily variability. A longer baseline (e.g., 10+ years) is more robust.
4. **Calibration recommended**: Uncalibrated VIC amplifies projection errors. Relative changes (%) are more robust than absolute values.

---

## Tools Reference

| Stage | Tool ID | Script Path | Purpose |
|-------|---------|-------------|---------|
| S1 | extract_cmip6_basin | `tools/s1_extract_cmip/extract_cmip6_basin.py` | Extract CMIP6 data for basin cells |
| S2 | compute_climate_deltas | `tools/s2_compute_deltas/compute_climate_deltas.py` | Monthly delta computation |
| S3 | apply_deltas_forcing | `tools/s3_apply_deltas/apply_deltas_forcing.py` | Apply deltas to baseline forcing |
| S4 | *(uses VIC + routing tools)* | *(from vic-auto-run and routing-run skills)* | Run model and analyse results |

---

## Error Handling

When an error occurs, look up the symptom in `diagnostics/triplets.yaml`. Key triplets:

| ID | Severity | Summary |
|----|----------|---------|
| dt_cc_001 | fatal | Basin outside China — no CMIP6 coverage |
| dt_cc_002 | fatal | Model name mismatch — file not found |
| dt_cc_003 | silent | Wrong column matching — bad coordinate precision |
| dt_cc_004 | silent | Deltas are zero — historical/future files confused |
| dt_cc_005 | degraded | Extreme precipitation ratio in dry months |
| dt_cc_006 | fatal | VIC time range doesn't match projected forcing |
| dt_cc_007 | silent | Pass-through variables (wind, pres) missing in output |
| dt_cc_008 | degraded | Uncalibrated parameters amplify projection errors |
| dt_cc_009 | fatal | Memory error reading large CMIP6 files |

---

## Output Directory Structure

```
outputs/{basin}/climate_projection/
├── cmip6_extracted/          # S1: Raw CMIP6 data per model/scenario/variable
│   ├── ACCESS-CM2_r1_pr_{basin}.nc
│   ├── ACCESS-CM2_245_pr_{basin}.nc
│   └── ...
├── deltas/                   # S2: Monthly change factors
│   ├── ACCESS-CM2_245_deltas_{basin}_2041-2070.nc
│   └── ...
├── forcing_{MODEL}_{SSP}/    # S3: Projected forcing (forcing_1d format)
│   ├── temp_cmfd_2041.nc
│   └── ...
├── forcing_final_{MODEL}_{SSP}/  # S3b: VIC ASCII forcing
│   ├── {prefix}_31.1250_115.6250
│   └── ...
├── vic_result_{MODEL}_{SSP}/ # S4: VIC output
├── routing_{MODEL}_{SSP}/    # S4: Routing output
└── ensemble_comparison.png   # S4: Multi-model comparison plot
```

---

*This knowledge infrastructure was built using the Knowledge Dissection Toolkit (Zhang et al., Nature, under review).*
*3 validated tools | 4 skill documents | 9 diagnostic triplets | 4 pipeline stages*
