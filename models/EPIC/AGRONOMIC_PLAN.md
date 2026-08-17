# EPIC Agronomic Capability Extension Plan

## Current State (v1)
- 16 tools, basic pipeline works
- Wine EPIC 1102 confirmed running at Bengbu
- Corn yield: 7.0 t/ha (uncalibrated, Umstead soil template)
- Copy-first workspace approach proven

## Agronomic Data Sources on Server

| Data | Path | What it provides |
|------|------|-----------------|
| **GGCMI Crop Calendar** | `KISSPATH_HOME/Crop_model_dataset/GGCMI_phase3_crop_calendar/` | Global planting/harvest dates by crop (0.5°) |
| **China Crop Phenology** | `KISSPATH_HOME/Crop_model_dataset/8313530/` | Chinese heading/maturity dates (GeoTIFF, 2000-2019) |
| **NPKGRIDS v1.08** | `KISSPATH_HOME/Crop_model_dataset/24616050/` | Global N/P/K application rates per crop |
| **SPAM 2020** | `KISSPATH_HOME/Crop_model_dataset/dataverse_files/` | Gridded crop yields, areas, production |
| **SoilGrids 250m** | `KISSPATH_HOME/Crop_model_dataset/SoilGrids_Bengbu/` | High-res soil properties (clay/sand/silt/SOC/BD) |
| **HWSD** | `data/soil/HWSD_RASTER/hwsd.bil` | Global soil texture + hydraulics |

## How DSSAT and RZWQM2 Handle Agronomic Data

### DSSAT approach (reference)
- `s4_genotype_config/` — Chinese cultivar library (42 varieties: wheat, maize, rice, soy)
- `s7_management_spec/` — planting date, fertilizer, irrigation from GGCMI + local calendars
- `dssat_workdir_setup.py` — one function handles all 6 Fortran pitfalls + cultivar + management
- Crop data source: built-in `CROPCOM.DAT` + China `.CUL` files

### RZWQM2 approach (reference)
- `s0_management_data/` — reads GGCMI for planting dates, NPKGRIDS for fertilizer rates
- `s6_management_write/` — generates RZWQM2 management schedule from data
- `s4_soil_setup/` — reads HWSD + SoilGrids, builds multi-layer soil profile
- Data-driven: agent doesn't need to know planting dates — tools look them up

## Planned EPIC Extensions (v2)

### Tool 1: `lookup_crop_calendar.py`
```python
def get_planting_harvest(lat, lon, crop='maize', source='ggcmi'):
    """Look up planting/harvest dates from GGCMI or China phenology.
    Returns: {'plant_month': 6, 'plant_day': 10, 'harvest_month': 10, 'harvest_day': 15}
    """
```
Sources: GGCMI (global), China phenology (China high-res), DSSAT calendar (regional defaults)

### Tool 2: `lookup_fertilizer.py`
```python
def get_nfertilizer(lat, lon, crop='maize', source='npkgrids'):
    """Look up N/P/K application rates from NPKGRIDS.
    Returns: {'n_kgha': 150, 'p_kgha': 30, 'k_kgha': 60}
    """
```
Source: NPKGRIDS v1.08

### Tool 3: `build_epic_opc.py` (enhanced from current)
```python
def build_opc(lat, lon, crop, calendar=None, fertilizer=None):
    """Build EPIC OPC from data-driven calendar + fertilizer.
    Uses lookup_crop_calendar + lookup_fertilizer if not provided.
    References CROPCOM.DAT for crop IDs.
    """
```

### Tool 4: `build_epic_soil.py` (enhanced)
```python
def build_soil(lat, lon, source='soilgrids'):
    """Build EPIC .SOL from SoilGrids 250m or HWSD.
    Uses rosetta_vgn() for van Genuchten if needed.
    Copies umstead.SOL template, replaces layer values.
    """
```

### Tool 5: `lookup_crop_yield_obs.py`
```python
def get_observed_yield(lat, lon, crop='maize', source='spam2020'):
    """Look up observed yield for validation.
    Returns: {'yield_kgha': 5500, 'source': 'SPAM2020', 'year': 2020}
    """
```

### Tool 6: `quickstart_epic.py` — One-command run
```python
def quickstart(lat, lon, crop, start_year, end_year, output_dir):
    """Complete EPIC run in one call:
    1. Copy workspace template
    2. Look up planting/harvest from GGCMI
    3. Look up fertilizer from NPKGRIDS
    4. Build OPC from calendar + fertilizer
    5. Convert forcing from CMFD/NASA POWER
    6. Build soil from HWSD/SoilGrids
    7. Update site (lat/lon/elev)
    8. Run EPIC via Wine
    9. Parse yield output
    10. Compare against SPAM2020
    """
```

## Shared Agronomic Libraries (ki_tools_common candidates)

These tools could be shared across EPIC, APEX, DSSAT, WOFOST, AquaCrop, RZWQM2:

| Function | Currently in | Should be in |
|----------|-------------|-------------|
| GGCMI crop calendar lookup | DSSAT s7, RZWQM2 s0 | `ki_tools_common.crop_calendar` |
| NPKGRIDS fertilizer lookup | RZWQM2 s0 | `ki_tools_common.fertilizer` |
| SPAM2020 yield lookup | validation scripts | `ki_tools_common.crop_obs` |
| SoilGrids query | RZWQM2 s4 | `ki_tools_common.soil_utils` (extend) |

## Priority Order
1. `quickstart_epic.py` — immediate usability
2. `build_epic_soil.py` — replace Umstead soil with real Bengbu soil
3. `lookup_crop_calendar.py` — data-driven planting dates
4. `lookup_fertilizer.py` — data-driven N rates
5. Shared libraries → ki_tools_common
