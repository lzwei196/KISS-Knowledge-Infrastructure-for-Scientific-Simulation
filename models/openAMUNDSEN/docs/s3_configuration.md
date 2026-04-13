# Skill: YAML Configuration

## Purpose

Create a valid openAMUNDSEN configuration file (YAML format) that specifies the domain,
time period, input/output paths, meteorological processing, snow model, and optional
modules (canopy, evapotranspiration, glaciers).

## Inputs

| Input | Type | Example |
|-------|------|---------|
| Domain name | String | "stubai" |
| Start/end dates | Datetime | 2020-10-01, 2021-09-30 |
| Spatial resolution | Integer (m) | 50 |
| CRS | EPSG string | "epsg:32632" |
| Timezone | Integer (UTC offset) | 1 |
| Grid directory | Path | "./input/grid" |
| Meteo directory | Path | "./input/meteo" |
| Results directory | Path | "./output" |

## Outputs

| Output | Format |
|--------|--------|
| Configuration file | YAML (.yml) |

## Procedure

### Step 1: Define Domain and Time Period

```yaml
domain: stubai
start_date: 2020-10-01
end_date: 2021-09-30
resolution: 50
timestep: 3h
crs: "epsg:32632"
timezone: 1
results_dir: ./output
```

**CRITICAL** (dt_010): `resolution` is in meters. Using 0.05 (km) creates a 2-cell grid.

**CRITICAL** (dt_015): `timestep` uses pandas frequency strings: `h` (hourly), `3h` (3-hourly),
`D` (daily). Using "3600" (seconds) or "60" (minutes) causes parse errors.

### Step 2: Configure Input Data

```yaml
input_data:
  grids:
    dir: ./input/grid
    format: ascii
  meteo:
    dir: ./input/meteo
    format: csv          # or netcdf
    crs: "epsg:4326"     # CRS of station coordinates
    bounds: grid
```

### Step 3: Configure Meteorological Processing

```yaml
meteo:
  interpolation:
    temperature:
      trend_method: fixed      # or regression
      lapse_rate:              # monthly values in K/m (NOT K/km!)
        - 0.0026   # Jan
        - 0.0035   # Feb
        - 0.0047   # Mar
        - 0.0056   # Apr
        - 0.0060   # May
        - 0.0064   # Jun
        - 0.0065   # Jul
        - 0.0062   # Aug
        - 0.0054   # Sep
        - 0.0041   # Oct
        - 0.0032   # Nov
        - 0.0025   # Dec
    precipitation:
      trend_method: fixed
      lapse_rate:
        - 0.0004   # typical: 0.3-0.5 mm/(m·month)
        - 0.0004
        - 0.0004
        - 0.0004
        - 0.0004
        - 0.0004
        - 0.0004
        - 0.0004
        - 0.0004
        - 0.0004
        - 0.0004
        - 0.0004

  precipitation_phase:
    method: wet_bulb_temp     # or temp
    threshold_temp: 273.65    # 50% snow at this temperature (K)
    temp_range: 1.0           # mixed precip over ±0.5 K range

  precipitation_correction: []  # or WMO/Kochendorfer corrections

  radiation:
    snow_emissivity: 0.99
    atmospheric_visibility: 25000  # m
```

**CRITICAL** (dt_013): Lapse rates are in K/m. Standard atmospheric lapse rate is
0.0065 K/m (= 6.5 K/km). If you enter `6.5`, that means 6500 K/km — temperatures
at 3000m will be ~19500 K colder than the valley. The model won't crash, but
results will be nonsense.

### Step 4: Configure Snow Model

```yaml
snow:
  model: multilayer          # or cryolayers
  melt:
    method: energy_balance   # or temperature_index, enhanced_temperature_index

  # Multilayer specific
  min_thickness:
    - 0.1   # minimum layer thickness (m)
    - 0.2
    - 0.4

  thermal_conductivity: 0.24  # W m⁻¹ K⁻¹

  albedo:
    min: 0.55
    max: 0.85
    cold_snow_decay_timescale: 480    # hours
    melting_snow_decay_timescale: 200  # hours
    refresh_snowfall: 0.5             # kg m⁻² h⁻¹
```

### Step 5: Configure Output

```yaml
output_data:
  timeseries:
    format: netcdf
    write_freq: ME           # monthly
    add_default_variables: true
    points:
      - x: 682500           # in model CRS coordinates
        y: 5215000
        name: summit_station

  grids:
    format: netcdf
    variables:
      - var: snow.swe
        name: swe_monthly
        freq: ME
        agg: mean
```

### Step 6: Optional Modules

```yaml
# Soil (defaults usually sufficient)
soil:
  thickness: [0.1, 0.2, 0.4, 0.8]
  sand_fraction: 0.6
  clay_fraction: 0.3
  albedo: 0.15

# Forest canopy (requires land cover grid)
canopy:
  enabled: false

# Evapotranspiration
evapotranspiration:
  enabled: false
```

## Verification

1. Run preflight check: `python run_openamundsen.py --config config.yml --dry-run`
2. Verify DEM file exists at expected path with correct name
3. Verify meteo directory contains data files
4. Check lapse rate values are O(0.001–0.01), not O(1–10)
5. Check resolution matches DEM cellsize
6. Check CRS matches DEM projection

## Traps

| Trap | Symptom | Fix | Diagnostic |
|------|---------|-----|------------|
| Resolution in km | ~1 grid cell | Use meters | dt_010 |
| Lapse rate in K/km | Extreme interpolated temps | Divide by 1000 | dt_013 |
| Invalid timestep | Parse error at startup | Use pandas freq string | dt_015 |
| Soil thickness in cm | Soil heat flux 100x wrong | Divide by 100 | dt_011 |
| Wrong CRS string | Coordinate transform fails | Use "epsg:XXXXX" format | — |

## Example

Complete minimal configuration for a 3-hourly run in the Stubai Alps:

```yaml
domain: stubai
start_date: 2020-10-01
end_date: 2021-09-30
resolution: 50
timestep: 3h
crs: "epsg:32632"
timezone: 1
results_dir: ./output

input_data:
  grids:
    dir: ./input/grid
  meteo:
    dir: ./input/meteo
    format: csv
    crs: "epsg:4326"

snow:
  model: multilayer
  melt:
    method: energy_balance

output_data:
  timeseries:
    format: netcdf
    add_default_variables: true
    points:
      - x: 682500
        y: 5215000
        name: test_point
```
