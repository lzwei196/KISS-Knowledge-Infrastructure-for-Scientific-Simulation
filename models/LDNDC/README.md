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

---

# LandscapeDNDC (LDNDC) — Knowledge Infrastructure

> **Model**: LandscapeDNDC v1.37 (KIT/IMK-IFU)
> **Domain**: Terrestrial biogeochemistry — C/N cycling, GHG emissions (N2O, CO2, CH4), nutrient leaching, crop yield
> **Pipeline stages**: 10 | **Tools**: 19 | **Skill documents**: 10 | **Diagnostic triplets**: 22
> **Binary**: `model/ldndc/ldndc-1.37.linux64/bin/ldndc` (pre-built, Linux 64-bit)
> **Status**: Validated on Bengbu wheat-maize (2000-2005) — N2O=4.9 kgN/ha/yr matches field measurements

## Overview

LandscapeDNDC is a modular, CLI-native C++ biogeochemistry framework for simulating biosphere-atmosphere-hydrosphere exchange processes. It replaces the GUI-bound DNDC model with a scalable, XML-configured system suitable for site and regional-scale simulations.

## Validated Results — Bengbu Wheat-Maize (Default Parameters)

| Metric | LDNDC (default) | Published Range | Source |
|--------|:---:|:---:|--------|
| N2O emission | 4.9 kgN/ha/yr | 1.9-6.7 kgN/ha/yr | Sichuan field 3yr |
| N2O EF | 1.4% | 1-2% | IPCC Tier 1 |
| NO3 leaching (yr1) | 41.4 kgN/ha | 38-60 kgN/ha | NCP field measurements |
| SOC change | +463 kgC/ha/yr | +113-350 kgC/ha/yr | National avg to straw return |
| Total GHG | 12,234 kgCO2eq/ha/yr | — | — |

**Key finding**: Default LDNDC parameters with HWSD soil + VIC climate produce publication-quality GHG estimates without calibration.

## LDNDC vs DNDC

Same biogeochemistry science, different architecture:
- **DNDC**: Windows GUI, Delphi, single-site, manual setup — cannot be automated
- **LDNDC**: Linux CLI, C++11, XML config, MPI parallel, modular — fully agentic

## Working Pipeline Tool

`tools/run_ldndc_bengbu_ghg.py` (1,032 lines) — complete end-to-end:
```bash
python run_ldndc_bengbu_ghg.py --lat 32.94 --lon 117.35 \
  --forcing_file outputs/bengbu_.../forcing_final/bengbu_0.25deg_32.8750_117.3750
```
Steps: VIC forcing → climate.txt, HWSD → site.xml, management XML, setup XML, airchemistry, project → run LDNDC → parse JSON results.

## Critical Species Names (verified)

| Crop | LDNDC Name | DSSAT Name | SWAT+ Name |
|------|-----------|-----------|------------|
| Maize | **CORN** | MZCER | agrl |
| Winter wheat | **WIWH** | WHCER | wwht |
| Rice | **RICE** | RICER | rice |
| Spring wheat | **SWHE** | WHCER | swht |
| Soybean | **SOYB** | SBGRO | soyb |
| Rapeseed | **RAPE** | — | canp |

## Critical Unit Conversions (verified)

| Variable | HWSD/VIC Unit | LDNDC Unit | Conversion |
|----------|:---:|:---:|:---:|
| corg (SOC) | % | fraction | ÷ 100 |
| sks (Ksat) | mm/hr | cm/min | ÷ 600 |
| clay | % | fraction | ÷ 100 |
| temperature | °C (VIC) | °C | none |
| radiation | W/m² (VIC) | W/m² | none |
| precipitation | mm/3hr (VIC) | mm/day | sum 8 steps |

Key capabilities:
- **Greenhouse gas emissions**: N2O, CO2, CH4 from soils (denitrification, nitrification, decomposition, methanogenesis)
- **Nutrient leaching**: NO3, NH4, dissolved organic N leaching to groundwater
- **Soil carbon dynamics**: Organic matter decomposition, humification, C pool changes
- **Crop/vegetation growth**: GPP, NPP, yield, LAI, biomass allocation via PlaMox or PSIM modules
- **Water cycle**: Infiltration, percolation, ET partitioning, runoff, snow dynamics
- **Management effects**: Tillage, fertilization, irrigation, crop rotation impacts on biogeochemistry

## Installation

See `docs/s1_installation_skill.md` for compilation from source and dependency setup. For HydroCraft, the pre-built binary is at `KISSPATH_HOME/LDNDC/bin/ldndc`. The LDNDC Docker image is available at `codebase.helmholtz.cloud/landscapedndc/ldndc-docker` for containerized deployment.

## Environment Setup

```bash
# LDNDC binary location
LDNDC_BIN="KISSPATH_HOME/LDNDC/bin/ldndc"

# Run LDNDC
$LDNDC_BIN project.xml
# or with config file:
$LDNDC_BIN -c ldndc.conf project.xml

# Python tools require the HydroCraft venv
source KISSPATH_PYTHON_ENV/bin/activate
```

## Pipeline

| Stage | Name | Skill Document | Tools |
|-------|------|----------------|-------|
| S1 | Project Structure Setup | `docs/s1_project_setup_skill.md` | `create_project_structure`, `generate_project_xml` |
| S2 | Site Configuration (site.xml) | `docs/s2_site_config_skill.md` | `generate_site_xml`, `hwsd_to_ldndc_soil` |
| S3 | Module Configuration (setup.xml) | `docs/s3_setup_modules_skill.md` | `generate_setup_xml` |
| S4 | Climate Data Preparation | `docs/s4_climate_prep_skill.md` | `convert_forcing_to_ldndc_climate`, `validate_climate_file` |
| S5 | Air Chemistry Preparation | `docs/s5_airchemistry_prep_skill.md` | `generate_airchemistry_file` |
| S6 | Management Events (mana.xml) | `docs/s6_management_config_skill.md` | `generate_management_xml` |
| S7 | Species Parameters | `docs/s7_species_params_skill.md` | `validate_species_params` |
| S8 | Model Execution | `docs/s8_execution_skill.md` | `run_ldndc` |
| S9 | Output Parsing and Analysis | `docs/s9_output_parsing_skill.md` | `parse_soilchemistry_output`, `parse_watercycle_output`, `parse_physiology_output`, `aggregate_annual_budget` |
| S10 | Multi-Model Coupling | `docs/s9_coupling_skill.md` | `vic_to_ldndc_climate`, `vic_to_ldndc_soilwater`, `vic_soil_to_ldndc_site` |

## Tools Reference

| Tool ID | Script Path | Purpose |
|---------|------------|---------|
| `create_project_structure` | `tools/s1_project_setup/create_project_structure.py` | Create project directory with input/output subdirs |
| `generate_project_xml` | `tools/s1_project_setup/generate_project_xml.py` | Generate master project.xml with schedule and paths |
| `generate_site_xml` | `tools/s2_site_config/generate_site_xml.py` | Generate site.xml with soil profile and canopy |
| `hwsd_to_ldndc_soil` | `tools/s2_site_config/hwsd_to_ldndc_soil.py` | Convert HWSD global soil data to LDNDC format |
| `generate_setup_xml` | `tools/s3_setup_modules/generate_setup_xml.py` | Generate module selection config |
| `convert_forcing_to_ldndc_climate` | `tools/s4_climate_prep/convert_forcing_to_ldndc_climate.py` | Convert CMFD/MSWX/VIC forcing to climate.txt |
| `validate_climate_file` | `tools/s4_climate_prep/validate_climate_file.py` | Validate climate.txt ranges and completeness |
| `generate_airchemistry_file` | `tools/s5_airchemistry_prep/generate_airchemistry_file.py` | Generate CO2 + N deposition input |
| `generate_management_xml` | `tools/s6_management_config/generate_management_xml.py` | Generate sowing/fertilizer/harvest events |
| `validate_species_params` | `tools/s7_species_params/validate_species_params.py` | Cross-validate species params against management |
| `run_ldndc` | `tools/s8_execution/run_ldndc.py` | Execute LDNDC binary with error handling |
| `parse_soilchemistry_output` | `tools/s9_output_parsing/parse_soilchemistry_output.py` | Extract GHG fluxes and nutrient leaching |
| `parse_watercycle_output` | `tools/s9_output_parsing/parse_watercycle_output.py` | Extract ET, drainage, runoff, soil moisture |
| `parse_physiology_output` | `tools/s9_output_parsing/parse_physiology_output.py` | Extract GPP, NPP, yield, LAI, biomass |
| `aggregate_annual_budget` | `tools/s9_output_parsing/aggregate_annual_budget.py` | Compute annual C/N budgets with mass balance |
| `vic_to_ldndc_climate` | `tools/s10_vic_coupling/vic_to_ldndc_climate.py` | Convert VIC forcing to LDNDC climate format |
| `vic_to_ldndc_soilwater` | `tools/s10_vic_coupling/vic_to_ldndc_soilwater.py` | Map VIC soil moisture to LDNDC layers |
| `vic_soil_to_ldndc_site` | `tools/s10_vic_coupling/vic_soil_to_ldndc_site.py` | Convert VIC soil params to LDNDC site.xml |

## Critical Domain Knowledge

### LDNDC Input File Structure

```
project_dir/
  project.xml          # Master config: schedule, source paths, output paths
  input/
    site.xml           # Soil profile, canopy, initial conditions
    setup.xml          # Module selection and output configuration
    climate.txt        # Tab-separated meteorological forcing
    airchem.txt        # CO2 concentration and N deposition
    mana.xml           # Management events (sowing, fertilizer, harvest)
    parameters_species.xml   # Crop/vegetation parameters
    parameters_site.xml      # Site-level parameters (optional)
  output/
    soilchemistry-daily.txt  # Daily GHG fluxes, leaching
    watercycle-daily.txt     # Daily water balance
    physiology-daily.txt     # Daily vegetation variables
    *.txt                    # Additional configured outputs
```

### project.xml Structure

```xml
<ldndcproject id="0" lat="33.5" lon="117.2">
  <schedule time="2000-01-01/24 -> 2010-12-31"/>
  <input>
    <sources sourceprefix="input/">
      <site source="site.xml"/>
      <event source="mana.xml"/>
      <setup source="setup.xml"/>
      <climate source="climate.txt"/>
      <airchemistry source="airchem.txt"/>
      <speciesparameters source="parameters_species.xml"/>
      <siteparameters source="parameters_site.xml"/>
    </sources>
    <attributes use="0">
      <airchemistry endless="yes"/>
    </attributes>
  </input>
  <output>
    <sinks sinkprefix="output/"/>
  </output>
</ldndcproject>
```

### climate.txt Format

Tab-separated with header row. Required columns:
- `tavg` [C] or `tmin` + `tmax` [C] -- average/min/max temperature
- `prec` [mm] -- precipitation (rain + snow)
- `wind` [m/s] -- wind speed
- `rh` [%] -- relative humidity (0-100)
- `glob` [W/m2] -- global (shortwave) radiation (optional, can be synthesized)
- `lrad` [W/m2] -- incoming longwave radiation (optional)

Example:
```
#       tavg    tmin    tmax    prec    wind    rh      glob
2000-01-01      -2.3    -5.1    0.8     0.0     2.1     78.5    85.2
2000-01-02      -1.5    -4.2    1.2     3.2     1.8     82.1    72.4
```

### Silent Error Modes (Most Dangerous)

1. **Soil organic carbon in wrong units**: LDNDC expects `corg` as mass fraction (e.g., 0.015 = 1.5%). If provided as percentage (1.5), soil C pools will be 100x too large, producing massively inflated CO2 emissions. The model runs without error.

2. **Temperature in Kelvin instead of Celsius**: LDNDC expects Celsius. Kelvin input causes no parse error but makes all temperature-dependent biogeochemistry wrong (decomposition rates, nitrification, denitrification).

3. **Mismatched crop species name**: If the species name in mana.xml does not exactly match parameters_species.xml, LDNDC may use default parameters or skip the crop entirely. No error is raised.

4. **N deposition units**: LDNDC expects kgN/ha/yr for deposition rates. Providing g/m2/yr (factor of 10 different) silently corrupts the N budget.

5. **Incompatible module combination**: Selecting a forest physiology module with cropland management events produces no error but generates nonsensical output.

## Coupling Points with HydroCraft Models

### VIC -> LDNDC
- **Climate forcing**: VIC forcing files (7-col ASCII) converted to LDNDC climate.txt via `vic_to_ldndc_climate`. Unit conversions: K->C (temperature), specific humidity->RH%, sub-daily->daily aggregation.
- **Soil parameters**: VIC soil param file (texture, Ksat, porosity, bulk density) mapped to LDNDC site.xml soil horizons via `vic_soil_to_ldndc_site`. VIC 3-layer to LDNDC multi-layer interpolation.
- **Soil moisture**: VIC simulated soil moisture used for LDNDC initial conditions via `vic_to_ldndc_soilwater`.

### CaMa-Flood -> LDNDC
- **Water table depth**: CaMa-Flood simulated water table depth can inform LDNDC groundwater boundary conditions, affecting anaerobic zone extent and CH4/N2O production.
- **Flood inundation**: CaMa-Flood flood fraction and depth can drive LDNDC wetland/paddy rice methane modules.

### LDNDC -> DSSAT (comparison)
- LDNDC crop yield can be compared with DSSAT yield for validation.
- LDNDC N leaching can inform DSSAT water quality assessment.

## Error Handling

See `diagnostics/triplets.yaml` for 15 diagnostic triplets covering:
- Path resolution errors (dt_001)
- XML format errors (dt_002, dt_004, dt_008)
- Silent unit conversion errors (dt_005, dt_012, dt_014)
- Silent biogeochemistry errors (dt_003, dt_007, dt_009, dt_013)
- Runtime crashes (dt_010, dt_011)
- Cross-model coupling mismatches (dt_015)

---

*This knowledge infrastructure was built using the Knowledge Dissection Toolkit v1.0 (Zhang et al., Nature, under review).*
*Part of the HydroCraft multi-model simulation platform by the Jianyun Zhang Research Group, Hohai University.*

---

## Rice (Paddy) Configuration — Critical (Validated 2026-03-20)

LDNDC rice simulation requires THREE separate fixes that are NOT documented in the standard user guide:

### 1. Species Name: Use PADR, NOT RICE
```xml
<!-- WRONG — RICE is abstract base class, produces zero output silently -->
<plant type="RICE" />

<!-- CORRECT — PADR = paddy rice (flooded) -->
<plant type="PADR" />

<!-- Also valid: UPLR = upland rice (rainfed) -->
```

### 2. Module Stack: Use paddy-specific modules
Standard dryland setup.xml (MeTrX) crashes immediately for paddies. Rice needs anaerobic soil chemistry and ponded water handling.

### 3. Management Events: Explicit flood/drain required
```xml
<event type="flood" doy="135" depth_mm="80"/>   <!-- transplanting flood -->
<event type="drain" doy="195"/>                   <!-- mid-season drain -->
<event type="flood" doy="205" depth_mm="50"/>    <!-- re-flood -->
<event type="drain" doy="250"/>                   <!-- pre-harvest drain -->
```

Without all three fixes, rice either crashes (fix 2 missing) or runs silently with zero output (fix 1 or 3 missing).

### HWSD Water Body Cells
If HWSD ISSOIL=0 for a cell (water body), use nearest-neighbor soil donor (0.25° search). 4 cells in Harbin basin required this fix.

---

## Current Limitations & Future Work (Assessed 2026-03-21)

### N₂O Underestimate — Root Cause Identified

LDNDC N₂O emissions for Harbin maize are **0.3-0.8 kgN/ha/yr** vs literature **1-3 kgN/ha/yr**. Three coupling approaches were tested:

| Approach | N₂O Result | Why it didn't work |
|----------|-----------|-------------------|
| DSSAT residue via `<event type="residue">` | 0.34 (no change) | Event type silently ignored by LDNDC |
| High `initialbiomass` + `remains=0.85` | 0.15 (worse) | More crop N uptake → less mineral N |
| Increased fertilizer 180→500 kgN/ha | 0.33→0.81 (improves) | Still below literature even at extreme |

**Root cause**: plamox phenology — DVS only reaches 0.4-0.65 in ~50% of years (crop doesn't mature). This means:
- No consistent root exudates → less rhizosphere denitrification
- Variable residue → depleted soil organic C in bad years
- Different moisture regime → fewer anaerobic microsites

**Correct fix (future work)**: Calibrate plamox GDD parameters for NE China short-season maize. Reduce thermal time from ~1560 to ~1100-1200 GDD in `parameters_species.xml`.

### What IS Usable

| Output | Usable? | Note |
|--------|---------|------|
| N₂O **relative change** (future/baseline ratio) | **Yes** | Direction of change is valid |
| CO₂ heterotrophic respiration | **Yes** | 1,537 kgC/ha/yr is reasonable |
| CH₄ from rice paddies | **Partial** | High variance, needs paddy module calibration |
| **Absolute N₂O values** | **No** | 5-10x too low, needs plamox calibration |
| Crop yields | **No** | Use DSSAT instead |

### LDNDC Execution — Critical Flag

Always run with `--conf`:
```bash
ldndc --conf /path/to/ldndc.conf ldndc_project.xml
```
Without `--conf`, LDNDC crashes with "premature termination" — no log file, no error message. The `.conf` must specify `resources_path` pointing to the LDNDC installation directory.
