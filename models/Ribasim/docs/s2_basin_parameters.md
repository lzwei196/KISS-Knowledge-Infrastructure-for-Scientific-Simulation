# Stage 2: Basin Parameters and Forcing

## Purpose

Define basin physical properties (area-level-storage profiles) and time-varying
forcing data (precipitation, evaporation, drainage, infiltration). This stage
populates the Basin tables in the GeoPackage database.

## Inputs

| Input | Format | Source | Required |
|-------|--------|--------|----------|
| Basin area-level profile | CSV/table | Survey, DEM, or literature | Yes |
| Initial water level | Scalar per basin | Observation or estimate | Yes |
| Precipitation time series | CSV with timestamps | ERA5, CMFD, gauge | Optional |
| Evaporation time series | CSV with timestamps | ERA5, Penman-Monteith | Optional |
| Drainage/infiltration | CSV or constant | Groundwater model | Optional |

## Outputs

| Output | Format | Path |
|--------|--------|------|
| Basin / profile | GeoPackage table | `input/database.gpkg` |
| Basin / state | GeoPackage table | `input/database.gpkg` |
| Basin / static | GeoPackage table | `input/database.gpkg` |
| Basin / time | GeoPackage or NetCDF | `input/database.gpkg` or `input/basin/time.nc` |

## Procedure

### Step 1: Build area-level profile

Each basin requires a profile defining the relationship between water level (m),
surface area (m²), and storage (m³). This is the **most critical input**.

Requirements:
- At least 2 level-area pairs
- Levels must be **monotonically increasing**
- First area should be > 0 (represents bottom area)
- Storage is computed automatically by trapezoidal integration

```python
ribasim.Basin.Profile(
    area=[100.0, 1000.0, 5000.0, 20000.0],  # m²
    level=[0.0, 2.0, 5.0, 10.0],             # m
)
```

**UNIT TRAP**: Area must be in **m²**. If you have km², multiply by 1e6.
If you have hectares, multiply by 1e4. Wrong area units cause the basin
to drain instantly (too small) or never respond to inflows (too large).

### Step 2: Set initial water level

```python
ribasim.Basin.State(level=[5.0])  # Initial level in meters
```

The initial level must fall within the profile's level range. Levels below
the profile minimum or above maximum cause initialization errors.

### Step 3: Add meteorological forcing

Ribasim expects vertical fluxes in **meters per second (m/s)**.

**CRITICAL UNIT CONVERSION TABLE**:

| Source Unit | → m/s Factor | Example: 5 mm/day |
|-------------|-------------|-------------------|
| mm/day | ÷ 86,400,000 | 5.787e-8 m/s |
| mm/hr | ÷ 3,600,000 | — |
| mm/3hr | ÷ 10,800,000 | — |
| m/day | ÷ 86,400 | — |
| inch/day | × 0.0254 ÷ 86,400 | — |

```python
# Constant forcing (Basin / static)
ribasim.Basin.Static(
    precipitation=[5.787e-8],  # 5 mm/day in m/s
    evaporation=[2.315e-8],    # 2 mm/day in m/s
    drainage=[0.0],            # m³/s
    infiltration=[0.0],        # m³/s
)

# Time-varying forcing (Basin / time)
ribasim.Basin.Time(
    time=["2020-01-01", "2020-02-01", ...],
    precipitation=[5.787e-8, 3.472e-8, ...],  # m/s
    evaporation=[1.157e-8, 2.315e-8, ...],     # m/s
)
```

### Step 4: Validate forcing magnitudes

After conversion, check that values are physically plausible:

| Variable | Typical Range (m/s) | Equivalent mm/day |
|----------|-------------------|-------------------|
| Precipitation | 0 – 5.8e-6 | 0 – 500 |
| Evaporation | 0 – 1.2e-7 | 0 – 10 |
| Drainage | 0 – 1.0 m³/s | Site-dependent |
| Infiltration | 0 – 1.0 m³/s | Site-dependent |

**Red flags**:
- Precipitation > 1e-5 m/s → almost certainly wrong units
- Precipitation > 1.0 → mm/day passed as m/s (catastrophic)
- Evaporation > precipitation (annual mean) → unrealistic for most climates

## Verification

1. Profile levels are monotonically increasing
2. Profile areas are non-negative
3. Initial level is within profile range
4. Forcing values are in m/s range (< 1e-5)
5. Time series covers full simulation period
6. No NaN values in forcing data

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| Precip in mm/day | **SILENT** | Basin floods immediately. Max level in first timestep. No error message. |
| Area in km² | **SILENT** | Basin drains in seconds. Level drops to minimum instantly. |
| Negative evaporation | **SILENT** | Treated as condensation — adds water to basin. |
| Missing profile | Fatal | Ribasim refuses to start without Basin / profile table. |
| Non-monotonic levels | Fatal | Profile levels must strictly increase. |
| Forcing gaps | **SILENT** | Missing timesteps interpolated as zero — dry spell artifact. |

## Example

```python
# Convert ERA5 daily precipitation (mm/day) to Ribasim
import pandas as pd

era5 = pd.read_csv("era5_daily.csv", parse_dates=["time"])
era5["precipitation_ms"] = era5["precipitation_mm_day"] / 86_400_000  # mm/day → m/s
era5["evaporation_ms"] = era5["evaporation_mm_day"] / 86_400_000

# Validate
assert (era5["precipitation_ms"] < 1e-5).all(), "Precip values too large — check units!"
assert (era5["precipitation_ms"] >= 0).all(), "Negative precipitation!"
```
