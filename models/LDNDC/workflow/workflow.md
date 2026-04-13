# LandscapeDNDC Workflow

## Pipeline Overview

LandscapeDNDC simulates terrestrial biogeochemistry (C/N cycling, GHG emissions, nutrient leaching) at site to regional scales. The pipeline prepares XML/text input files, runs the C++ model binary, and parses CSV output.

**Total stages**: 10 (S1-S10)
**Dependencies**: S2-S7 depend on S1; S8 depends on S2-S7; S9 depends on S8; S10 is independent (coupling stage)

## Stage Flow

```
S1 Project Setup
  |
  +---> S2 Site Config (site.xml)
  |       |
  +---> S3 Module Config (setup.xml)
  |       |
  +---> S4 Climate Prep (climate.txt)
  |       |
  +---> S5 Airchemistry (airchem.txt)
  |       |
  +---> S6 Management (mana.xml)
  |       |
  |       +---> S7 Species Params
  |               |
  +---------------+---> S8 Model Execution (ldndc binary)
                          |
                          +---> S9 Output Parsing & Analysis

S10 VIC-LDNDC Coupling (feeds into S2 + S4)
```

## Stage Details

### S1: Project Structure Setup
- **Purpose**: Create directory tree and master project.xml
- **Tools**: `create_project_structure`, `generate_project_xml`
- **Milestone**: project.xml exists with valid schedule and source paths
- **Key decision**: Simulation period, coordinates, output prefix
- **Typical time**: < 5 seconds

### S2: Site Configuration (site.xml)
- **Purpose**: Define soil physical and chemical properties for biogeochemistry
- **Tools**: `generate_site_xml`, `hwsd_to_ldndc_soil`
- **Milestone**: site.xml has soil profile with corg, bd, clay, sand, pH per layer
- **Key decision**: Number of soil layers, depth of profile, organic layer presence
- **Data source**: HWSD global raster + MDB (shared with VIC/DSSAT)
- **Typical time**: 10-30 seconds (HWSD lookup)

### S3: Module Configuration (setup.xml)
- **Purpose**: Select process modules and configure output variables
- **Tools**: `generate_setup_xml`
- **Milestone**: setup.xml has compatible module set for target ecosystem
- **Key decision**: Ecosystem type determines module selection:
  - Cropland: CanopyECM + WatercycleDNDC + MeTrx + PlaMox
  - Forest: CanopyECM + WatercycleDNDC + SoilchemistryDNDC + PSIM
  - Grassland: CanopyECM + WatercycleDNDC + MeTrx + GrasslandDNDC
  - Wetland: CanopyECM + WatercycleDNDC + MeTrx (+ CH4 module)
- **Typical time**: < 5 seconds

### S4: Climate Data Preparation
- **Purpose**: Provide daily meteorological forcing to LDNDC
- **Tools**: `convert_forcing_to_ldndc_climate`, `validate_climate_file`
- **Milestone**: climate.txt has header + daily rows covering simulation period
- **Data sources**: CMFD (China), MSWX (global), ERA5, VIC forcing, NASA POWER
- **Key unit conversions**: K->C (temperature), W/m2 (radiation), mm (precip), m/s (wind), % (RH)
- **Typical time**: 2-30 minutes (depends on forcing source)

### S5: Air Chemistry Data Preparation
- **Purpose**: Provide atmospheric CO2 and N deposition boundary conditions
- **Tools**: `generate_airchemistry_file`
- **Milestone**: airchem.txt with CO2 ppm and NH4/NO3 deposition rates
- **Key decision**: Use constant values or time-varying historical/scenario data
- **Default values**: CO2=400 ppm, NH4_dep=5.0 kgN/ha/yr, NO3_dep=3.0 kgN/ha/yr
- **Typical time**: < 5 seconds

### S6: Management Events Configuration (mana.xml)
- **Purpose**: Define agricultural operations that drive biogeochemistry
- **Tools**: `generate_management_xml`
- **Milestone**: mana.xml with events matching simulation years
- **Key events**: sowing (species, date), fertilization (type, kgN/ha, date), tillage (depth, date), harvest (date, residue%), irrigation
- **Typical time**: < 10 seconds

### S7: Species Parameters
- **Purpose**: Ensure crop parameters match management events
- **Tools**: `validate_species_params`
- **Milestone**: All species in mana.xml defined in parameters_species.xml
- **Key decision**: Use LDNDC defaults or calibrate from literature/DSSAT
- **Typical time**: < 5 seconds

### S8: Model Execution
- **Purpose**: Run LDNDC binary
- **Tools**: `run_ldndc`
- **Command**: `ldndc project.xml` or `ldndc -c config.conf project.xml`
- **Milestone**: Exit code 0, output files in output/ directory
- **Typical time**: 1-30 minutes per site (depends on period length and output detail)
- **Common failures**: XML parse error, missing input file, segfault from corrupt soil data

### S9: Output Parsing and Analysis
- **Purpose**: Extract scientific results from LDNDC output CSV files
- **Tools**: `parse_soilchemistry_output`, `parse_watercycle_output`, `parse_physiology_output`, `aggregate_annual_budget`
- **Milestone**: GHG timeseries extracted; annual C/N budgets close within 5%
- **Key outputs**:
  - GHG: N2O (kgN/ha), CO2 (kgC/ha), CH4 (kgC/ha)
  - Leaching: NO3 (kgN/ha), DON (kgN/ha), NH4 (kgN/ha)
  - Water: ET (mm), drainage (mm), runoff (mm)
  - Crop: yield (kgC/ha), GPP (kgC/ha), NPP (kgC/ha), LAI
- **Typical time**: < 1 minute

### S10: Multi-Model Coupling (VIC/CaMa-Flood/DSSAT)
- **Purpose**: Bridge HydroCraft model outputs to LDNDC inputs; cross-validate with DSSAT
- **Skill document**: `docs/s9_coupling_skill.md`
- **Tools**: `vic_to_ldndc_climate`, `vic_to_ldndc_soilwater`, `vic_soil_to_ldndc_site`
- **Coupling pathways**:
  - **VIC -> LDNDC**: Climate forcing (K->C, sub-daily->daily), soil params (BD kg/m3->g/cm3), soil moisture
  - **CaMa-Flood -> LDNDC**: Water table depth for anaerobic zone (CH4/N2O), flood inundation (conceptual)
  - **DSSAT <-> LDNDC**: Yield cross-validation (kgC/ha vs. kg DM/ha), N leaching for water quality
- **Milestone**: Consistent climate and soil data between VIC and LDNDC
- **When to use**: After VIC simulation completes (Step 7 of HydroCraft workflow)
- **Typical time**: 1-5 minutes

## Coverage Summary

| Stage | Tools | Skill Doc | Triplets |
|-------|-------|-----------|----------|
| S1 | 2 | Yes | dt_001 |
| S2 | 2 | Yes | dt_002, dt_003 |
| S3 | 1 | Yes | dt_004 |
| S4 | 2 | Yes | dt_005, dt_006 |
| S5 | 1 | Yes | dt_007 |
| S6 | 1 | Yes | dt_008, dt_009 |
| S7 | 1 | Yes | - |
| S8 | 1 | Yes | dt_010, dt_011 |
| S9 | 4 | Yes | dt_012, dt_013 |
| S10 | 3 | Yes | dt_014, dt_015 |

---
*Generated from LandscapeDNDC knowledge infrastructure v1.0.0*
