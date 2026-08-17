# ki_tools_common

Shared utility library for the knowledge-dissection-toolkit. Consolidates duplicated code found across 435+ `ki/tools/` scripts in 97 models.

## Installation

```bash
cd auto_dissect/ki_tools_common
pip install -e .          # minimal (numpy only)
pip install -e ".[all]"   # with xarray, netCDF4, geopandas
pip install -e ".[dev]"   # with pytest
```

## Modules

| Module | Purpose | Replaces duplication in |
|---|---|---|
| `units` | Unit conversions (temperature, precipitation, pressure, radiation, wind, soil, carbon, length) | 78+ files |
| `humidity` | Tetens saturation vapour pressure, RH/q conversions, VPD, dewpoint | 17 files |
| `netcdf_utils` | Coordinate detection, bounding-box subsetting, basin masking, CMFD/MSWX loaders | 50+ files |
| `validation` | Physical range checks with unit-trap hints, discharge validation, fill-value detection | 30+ files |
| `metrics` | NSE, KGE, PBIAS, RMSE, Pearson r with NaN handling, monthly aggregation | 42 files |
| `io_helpers` | Standard JSON result dict, flexible date parsing, Bengbu obs reader, FLUXNET reader | 326 files |
| `forcing_sources` | CMFD/MSWX/ERA5/FLUXNET variable metadata and conversion factor lookup | 68 files |

## Usage

```python
from ki_tools_common import units, metrics, humidity, validation

# Convert CMFD precipitation to mm/day
precip_mmday = units.kgm2s_to_mmday(precip_kgm2s)

# Or use the universal dispatcher
temp_k = units.convert(25.0, 'C', 'K', 'temperature')

# Compute all performance metrics at once
m = metrics.all_metrics(obs, sim)
print(f"NSE={m['NSE']:.3f}  KGE={m['KGE']:.3f}")

# Check forcing data for unit traps
warnings = validation.validate_forcing_ranges({
    'temperature': temp_array,
    'precipitation': precip_array,
})

# Humidity: one canonical Tetens implementation
es = humidity.saturation_vapor_pressure(temp_c=20.0)  # 23.39 hPa
rh = humidity.specific_humidity_to_rh(q=0.01, temp_k=293.15, pres_pa=101325.0)

# Forcing source metadata
from ki_tools_common.forcing_sources import get_conversion_factor
factor = get_conversion_factor('CMFD', 'prec', 'mm/day')  # 86400.0
```

## Running tests

```bash
cd auto_dissect/ki_tools_common
pytest tests/ -v
```
