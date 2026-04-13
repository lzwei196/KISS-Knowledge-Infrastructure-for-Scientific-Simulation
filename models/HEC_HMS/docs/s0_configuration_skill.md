# S0: Configuration Skill

## Purpose

Set up the HEC-HMS simulation environment: define the basin, simulation period,
temporal resolution, file paths, and unit system. This stage produces no model
output but establishes the framework for all subsequent stages.

## Inputs

| Input | Format | Example |
|-------|--------|---------|
| Basin shapefile | .shp (EPSG:4326) | `bengbu_clip.shp` |
| DEM | GeoTIFF | `china_dem_90m.tif` |
| Simulation period | YYYY-MM-DD | 1980-01-01 to 1990-12-31 |
| Timestep | hours | 24 (daily) |
| Unit system | string | "metric" |
| Forcing directory | path | `/path/to/cmfd/` |
| Observation file | path | `51080_bengbu.txt` |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Project config JSON | `.json` | All paths, dates, parameters |
| Basin info JSON | `.json` | Area (km²), bounds, centroid |

## Procedure

1. **Define project directory**: Create working directory structure:
   ```
   project/
   ├── forcing/       # Converted forcing data
   ├── params/        # Soil and land cover parameters
   ├── output/        # Model simulation output
   └── validation/    # Comparison with observations
   ```

2. **Read basin shapefile**: Load with geopandas, reproject to EPSG:4326 for
   forcing extraction, compute area in km² using equal-area projection (EPSG:6933).

3. **Set simulation period**: Define start/end dates. Include at least 1 year
   of spinup before the validation period. For Bengbu 1981-1990 validation,
   start the simulation at 1980-01-01.

4. **Choose timestep**: Daily (24 hr) for continuous simulation. Sub-daily
   (1-6 hr) for event-based flood analysis. Ensure forcing data resolution
   matches or exceeds the model timestep.

5. **Set unit system**: HEC-HMS supports Metric and US Customary. Use Metric
   for all HydroCraft integrations. Key units: precipitation (mm), temperature
   (°C), area (km²), discharge (m³/s).

6. **Verify data availability**: Check that forcing, soil, landcover, and
   observation files exist and cover the simulation period.

## Verification

- [ ] Basin area is reasonable (Bengbu: ~121,330 km²)
- [ ] Simulation period is within forcing data coverage
- [ ] All input file paths resolve to existing files
- [ ] Output directories are created and writable

## Traps

- **dt_108**: Basin area units. Shapefile `.area` returns m² — divide by 1e6 for km².
  Using projected CRS (EPSG:6933) for area computation, not geographic (EPSG:4326).
- **dt_115**: Simulation period must be within forcing data coverage. CMFD Huai River
  subset covers 1960-2020.
- Spinup: First year of simulation should be discarded. Baseflow and soil moisture
  need time to equilibrate from initial conditions.

## Example

```python
config = {
    "basin_shp": "/mnt/disk1/.../bengbu_clip.shp",
    "forcing_dir": "/mnt/disk1/.../Data_forcing_01dy_025deg/",
    "obs_file": "/mnt/disk1/.../51080_bengbu.txt",
    "start_date": "1980-01-01",
    "end_date": "1990-12-31",
    "spinup_years": 1,
    "validation_start": "1981-01-01",
    "timestep_hr": 24,
    "unit_system": "metric",
    "basin_area_km2": 121330,
}
```
