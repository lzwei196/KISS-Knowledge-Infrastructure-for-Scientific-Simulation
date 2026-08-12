# Stage 0: Configuration

## Purpose

Define the simulation setup for a TOPMODEL run: select the target basin,
simulation period, forcing data source, and output options.

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| Basin shapefile | Yes | Polygon defining catchment boundary |
| Basin area (km²) | Yes | Total drainage area |
| Simulation period | Yes | Start/end dates |
| Forcing source | Yes | CMFD, MSWX, or custom |
| Time step | Yes | Typically 1 hour |
| Observed discharge | No | For calibration/validation |

## Outputs

- Configuration dictionary with all parameters needed by downstream stages.
- topmod.run file (or parameters to generate it).

## Procedure

1. **Select basin**: Identify the catchment boundary shapefile. For HydroCraft basins,
   use the provided shapefiles under `/mnt/disk1/Hydrocraft_server/data/shp/`.

2. **Set period**: Choose simulation start/end dates.
   - Allow 1 year spinup (e.g., start 1 year before validation period).
   - Verify forcing data covers the full period.

3. **Choose forcing**: Select CMFD (China) or MSWX (global).
   - CMFD daily 0.25°: `/media/server/hc_ssd/forcing/huai/Data_forcing_01dy_025deg/`
   - MSWX 3-hourly: `/mnt/disk3/msxw/`

4. **Set time step**: TOPMODEL uses hours. Typically dt=1 for hourly, dt=24 for daily.
   All forcing must match this time step.

5. **Locate observations**: Find the gauge station file for validation.

## Verification

- [ ] Basin shapefile exists and covers the study area
- [ ] Forcing data covers the full simulation period
- [ ] Observation data overlaps with the simulation period
- [ ] Time step is consistent across all inputs

## Traps

| Trap | Consequence | Prevention |
|------|-------------|------------|
| Period extends beyond forcing coverage | NaN values in inputs.dat | Check forcing file year range |
| Wrong basin shapefile CRS | TWI computation fails | Reproject to match DEM CRS |
| Forgetting spinup year | Poor initial conditions | Always add 1 year before validation start |

## Example

```python
config = {
    'basin_name': 'Bengbu',
    'basin_area_km2': 121330,
    'shapefile': '/mnt/disk1/Hydrocraft_server/data/shp/bengbu_shp/bengbu_clip.shp',
    'start_date': '1980-01-01',
    'end_date': '1990-12-31',
    'spinup_years': 1,
    'dt_hours': 24,
    'forcing_source': 'CMFD',
    'forcing_dir': '/media/server/hc_ssd/forcing/huai/Data_forcing_01dy_025deg/',
    'obs_file': '/mnt/disk1/Hydrocraft_server/data/obs/BB/51080_bengbu.txt',
    'obs_station': '51080',
}
```
