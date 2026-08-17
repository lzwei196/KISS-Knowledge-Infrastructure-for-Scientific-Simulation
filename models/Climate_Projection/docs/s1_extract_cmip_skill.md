# CMIP6 Data Extraction — Skill Document

> **Stage ID**: s1_extract_cmip
> **Pipeline order**: 1 of 4
> **Depends on**: VIC model setup (basin grid must exist)

## Purpose

Extract bias-corrected CMIP6 daily climate data (precipitation, tasmax, tasmin) for the basin's VIC grid cells from the China-wide text files. This transforms the 4,163-cell China grid into basin-specific NetCDF files that downstream tools can process efficiently.

## Prerequisites

Before starting this stage, verify:

- [ ] VIC basin grid file exists at `outputs/{basin}/vic_temp/grid/basin_grid.nc`
- [ ] CMIP6 data is accessible at `KISSPATH_DATA/CMIP_China/Cmip6BaisCorrect_for_China/`
- [ ] Python environment activated: `source KISSPATH_PYTHON_ENV/bin/activate`
- [ ] Basin is within China (73.75-135.25E, 15.25-53.75N) — CMIP6 data covers China only

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| CMIP6_ROOT | directory | External drive | `KISSPATH_DATA/CMIP_China/Cmip6BaisCorrect_for_China/` |
| GRID_NC | file | VIC grid step | `outputs/{basin}/vic_temp/grid/basin_grid.nc` |
| MODEL_NAME | string | User choice | One of 26 CMIP6 models (see model list below) |
| SCENARIO | string | User choice | `r1` (historical) or `126`/`245`/`585` (SSP future) |

### Available CMIP6 Models (26 with all 3 variables)

ACCESS-CM2, ACCESS-ESM1-5, BCC-CSM2-MR, CanESM5, CESM2, CMCC-ESM2, CNRM-CM6-1, CNRM-ESM2-1, EC-Earth3, EC-Earth3-Veg, EC-Earth3-Veg-LR, FGOALS-g3, GFDL-ESM4, INM-CM4-8, INM-CM5-0, IPSL-CM6A-LR, KACE-1-0-G, KIOST-ESM, MIROC6, MPI-ESM1-2-HR, MPI-ESM1-2-LR, MRI-ESM2-0, NESM3, NorESM2-LM, NorESM2-MM, TaiESM1, UKESM1-0-LL

### Scenarios

| Scenario code | CMIP6 name | Period | Description |
|---------------|-----------|--------|-------------|
| `r1` | Historical | 1961-2014 | Historical reference run |
| `126` | SSP1-2.6 | 2015-2099 | Low emissions (sustainable path) |
| `245` | SSP2-4.5 | 2015-2099 | Intermediate emissions |
| `585` | SSP5-8.5 | 2015-2099 | High emissions (fossil fuel intensive) |

## Procedure

### Step 1: Select model(s) and scenario(s)

If the user does not specify, recommend a **5-model ensemble** for robustness:
- ACCESS-CM2, BCC-CSM2-MR, EC-Earth3, MIROC6, MRI-ESM2-0

For scenarios, always extract **r1 (historical)** plus the user's chosen SSP(s). If unspecified, use SSP2-4.5 (245) as default.

### Step 2: Create output directory

```bash
mkdir -p outputs/{basin}/climate_projection/cmip6_extracted
```

### Step 3: Run extraction for historical + each scenario

```bash
source KISSPATH_PYTHON_ENV/bin/activate

# Extract historical (required for delta computation)
python skills/climate-projection/tools/s1_extract_cmip/extract_cmip6_basin.py \
  KISSPATH_DATA/CMIP_China/Cmip6BaisCorrect_for_China \
  outputs/{basin}/vic_temp/grid/basin_grid.nc \
  {MODEL_NAME} r1 \
  outputs/{basin}/climate_projection/cmip6_extracted \
  {basin}

# Extract future scenario
python skills/climate-projection/tools/s1_extract_cmip/extract_cmip6_basin.py \
  KISSPATH_DATA/CMIP_China/Cmip6BaisCorrect_for_China \
  outputs/{basin}/vic_temp/grid/basin_grid.nc \
  {MODEL_NAME} {SCENARIO} \
  outputs/{basin}/climate_projection/cmip6_extracted \
  {basin}
```

**Expected result**: 3 NetCDF files per model × scenario in `cmip6_extracted/`:
- `{MODEL}_r1_pr_{basin}.nc`
- `{MODEL}_r1_tasmax_{basin}.nc`
- `{MODEL}_r1_tasmin_{basin}.nc`
- `{MODEL}_{scenario}_pr_{basin}.nc` (etc.)

**Runtime**: ~2-5 minutes per model per scenario (reading 650 MB text files).

**If this fails**: See diagnostic triplet dt_cc_001 (basin outside China) or dt_cc_002 (model file not found).

### Step 4: Verify extracted data

```bash
# Check file sizes (should be > 100 KB)
ls -lh outputs/{basin}/climate_projection/cmip6_extracted/*.nc

# Quick sanity check with ncdump
ncdump -h outputs/{basin}/climate_projection/cmip6_extracted/{MODEL}_r1_pr_{basin}.nc | head -20
```

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Historical pr | `cmip6_extracted/{MODEL}_r1_pr_{basin}.nc` | File > 100 KB, time dim = 19723 days (1961-2014) |
| Historical tasmax | `cmip6_extracted/{MODEL}_r1_tasmax_{basin}.nc` | Same structure, values 0-50°C |
| Future pr | `cmip6_extracted/{MODEL}_{ssp}_pr_{basin}.nc` | time dim = 31046 days (2015-2099) |

## Validation Checks

1. **Cell count**: Number of cells in output should match VIC grid cells
   - Command: `ncdump -h {file} | grep "cell ="`
   - If fewer cells: basin extends outside China CMIP6 coverage

2. **Value ranges**: pr should be >= 0 mm/day, temperature should be -40 to 55°C
   - If all zeros: wrong column matching (see dt_cc_003)

## Common Pitfalls

> **PITFALL**: Basin extends outside China boundary
> CMIP6 bias-corrected data covers only China (73.75-135.25E, 15.25-53.75N).
> Grid cells outside this boundary will have no matching CMIP6 cell.
> **Do this instead**: Use only the cells within China, or use global CMIP6 raw data for cells outside.
> See diagnostic triplet dt_cc_001.

> **PITFALL**: Mixing up scenario codes
> The folder names are `r1`, `126`, `245`, `585` — NOT `ssp126`, `ssp245`, `ssp585`.
> **Do this instead**: Use the short codes exactly as listed in the folder names.

---

*This skill document is part of the climate-projection knowledge infrastructure.*
*Stage 1 of 4 | Tools used: extract_cmip6_basin | Related triplets: dt_cc_001, dt_cc_002, dt_cc_003*
