# S0: Management Data Acquisition & S6.5: Management Events Write

## Purpose
Retrieve crop management parameters from five global geospatial datasets and write them into RZWQM2's `RZWQM.dat` management sections. This closes the gap where management events (planting dates, fertilizer amounts, harvest dates, irrigation mode) were previously inherited verbatim from template scenarios, enabling truly data-driven mass project generation.

## Prerequisites
- Python packages: `xarray`, `h5py`, `netCDF4`, `numpy`, `pandas`, `rasterio`, `pyproj`
- Datasets extracted at `/home/server/Crop_model_dataset/`:
  - `22491997/CROPGRIDSv1.08_NC_maps.zip` (crop area, 0.05 deg)
  - `24616050/NPKGRIDSv1.08_NC.zip` (fertilizer rates, 0.05 deg)
  - `ALL_CROPS_netCDF_0.5deg_filled/` (crop calendar, 0.5 deg)
  - `8313530/` (China phenology GeoTIFFs, 1km)
  - `dataverse_files/Global_CSV/` (SPAM 2020, ~10km)
- A valid `RZWQM.dat` file in the scenario directory (from template)

## Inputs
| Input | Source | Description |
|---|---|---|
| `lat`, `lon` | Sites CSV | Decimal degrees, WGS-84 |
| `crop_name` | Sites CSV or `crop_area_lookup` | Harmonized via `crop_name_harmonizer.py` |
| `year` | Sites CSV `start_date` | Reference year for China Phenology |
| `simulation_years` | Derived from `start_date`/`end_date` | List of years for annual planting events |

## Procedure

### Step 1: Harmonize Crop Name
```python
from crop_name_harmonizer import harmonize
crop = harmonize(crop_name)  # Returns HarmonizedCrop with all dataset-specific IDs
```

### Step 2: Look Up Planting/Harvest Dates (crop_calendar_lookup)
- Primary: Global Crop Calendar (Sacks) at 0.5 deg — sample `plant` and `harvest` DOY
- Override: For China sites (lat 18-54, lon 73-135) with Maize/Rice/Wheat, use 1km China Phenology GeoTIFFs via CRS transform (WGS-84 -> ESRI:102025)
- Fallback: If China pixel is nodata, falls back to global calendar

### Step 3: Look Up Fertilizer Rates (fertilizer_rate_lookup)
- Sample NPKGRIDS at nearest 0.05 deg pixel for the harmonized crop
- Split total N into application events via `split_strategy`:
  - `two_split` (default): 1/3 NH4 preplant, 2/3 urea postemergence
  - `single`: all NO3 preplant
  - `three_split`: 1/4 + 1/2 + 1/4
- P mass applied with first application only

### Step 4: Determine Irrigation Type (irrigation_type_lookup)
- Read SPAM 2020 H_TI (irrigated) and H_TA (total) harvested area CSVs
- Compute irrigated_fraction at nearest pixel
- Classify as irrigated if fraction >= 0.5 (configurable threshold)

### Step 5: Assemble management_config JSON
```python
management_config = {
    "planting": {
        "planting_doy": calendar_result["planting_doy"],
        "harvest_doy": calendar_result["harvest_doy"],
        "row_spacing_cm": crop.default_row_spacing_cm,
        "density_seeds_per_ha": crop.default_density_seeds_ha,
        "depth_layer_index": crop.default_planting_depth_layer,
    },
    "fertilizer": {
        "applications": fert_result["applications"]
    },
    "irrigation": {
        "is_irrigated": irrig_result["is_irrigated"]
    }
}
```

### Step 6: Write to RZWQM.dat (write_management_events)
- Locates management sections by header/end delimiter strings
- Replaces data lines between delimiters
- Writes planting (3 lines per year), fertilizer (1 line per application), and irrigation (control line + per-year operations)

## Expected Outputs
- Modified `RZWQM.dat` with populated management sections
- JSON result: `{sections_written: ["planting", "fertilizer", "irrigation"], num_plantings: N, num_fert_apps: M}`

## Validation Checks
1. `planting_doy` in [1, 366] — invalid DOY indicates missing data
2. `n_rate_kg_ha` in [0, 500] — rates > 500 are suspicious
3. `irrigated_fraction` in [0, 1]
4. Written RZWQM.dat parses without error — round-trip test
5. Cross-year seasons handled (harvest DOY < planting DOY for winter crops)

## Common Pitfalls
- **CRS mismatch for China Phenology**: The GeoTIFFs use ESRI:102025 (projected). Must transform lat/lon via pyproj before sampling. Fallback to global calendar if pyproj unavailable.
- **Sparse China Phenology coverage**: Only 0.8-2.2% of pixels have data. Sites in non-cropping areas of China will fall back to global calendar.
- **SPAM CSV size**: H_TA.csv has ~800K rows. First load is slow; cache DataFrames for repeated queries.
- **Section identifier exact match**: RZWQM.dat section headers must match identifier strings exactly (including whitespace). Different RZWQM2 versions may vary.
- **Fertilizer timing codes**: 1=preplant (offset = days BEFORE planting), 3=postemergence (offset = days AFTER emergence). Don't confuse with specified-date timing (code 5).
- **NPKGRIDS zip structure**: Files are in zip root, NOT in a subdirectory (unlike CROPGRIDS which has `CROPGRIDSv1.08_NC_maps/` subdirectory).

## Dataset Cross-Reference
| Dataset | Resolution | CRS | Format | Crops |
|---|---|---|---|---|
| CROPGRIDS | 0.05 deg | WGS-84 | NetCDF (in zip) | 173 |
| NPKGRIDS | 0.05 deg | WGS-84 | NetCDF (in zip) | 173 |
| Crop Calendar | 0.5 deg | WGS-84 | NetCDF (gzipped) | 25 |
| China Phenology | 1 km | ESRI:102025 | GeoTIFF | 4 |
| SPAM 2020 | ~10 km | WGS-84 | CSV (in zip) | 46 |
