# Stage 2: Meteorology Forcing Preparation

## Purpose

Convert global reanalysis or station data into the format required by the
TopoFlow meteorology component (`tf_meteorology`).  This is the single most
error-prone stage due to unit conversion traps that produce silent failures.

## Inputs

| Data Source | Variables                              | Native Units                  |
|-------------|----------------------------------------|-------------------------------|
| ERA5        | tp, t2m, d2m, u10, v10, sp, ssrd      | kg/m²/s, K, Pa, J/m², m/s    |
| CMFD        | prec, temp, shum, wind, pres, srad     | mm/3hr, °C, g/kg, m/s, Pa    |
| MSWX        | P, T, RH, Wind, Rad                   | mm/day, °C, %, m/s, W/m²     |
| GLDAS       | Rainf, Tair, Qair, Wind, SWdown       | kg/m²/s, K, kg/kg, m/s, W/m² |
| Station     | Various                                | Varies                        |

## Outputs

| File                    | Units         | TopoFlow Variable | Notes                          |
|-------------------------|---------------|--------------------|--------------------------------|
| `*_rain_rates.txt`      | **mm/hr**     | P_rain             | CRITICAL: must be mm/hr        |
| `*_T_air.txt`           | **°C**        | T_air              | CRITICAL: not Kelvin           |
| `*_RH.txt`              | **0–1 frac**  | RH                 | CRITICAL: not percentage       |
| `*_wind.txt`            | m/s           | uz                 | At measurement height z        |
| `*_p_atm.txt`           | mbar          | p0                 | 1 atm ≈ 1013.25 mbar          |
| `*_Qsw.txt`             | W/m²          | Qn_SW              | Shortwave radiation            |

## Procedure

### Step 1: Download forcing data

For ERA5, use the CDS API:

```python
import cdsapi
c = cdsapi.Client()
c.retrieve('reanalysis-era5-single-levels', {
    'product_type': 'reanalysis',
    'variable': ['2m_temperature', '2m_dewpoint_temperature',
                 'total_precipitation', 'surface_pressure',
                 '10m_u_component_of_wind', '10m_v_component_of_wind',
                 'surface_solar_radiation_downwards'],
    'year': '2020', 'month': '07', 'day': list(range(1, 32)),
    'time': [f'{h:02d}:00' for h in range(24)],
    'area': [42, -96, 41, -95],
    'format': 'netcdf',
}, 'era5_forcing.nc')
```

### Step 2: Extract point data and convert units

Use `tools/convert_forcing.py`:

```bash
python ki/tools/convert_forcing.py \
  --source era5 \
  --input_dir ./era5_data/ \
  --lat 41.17 --lon -95.62 \
  --start 1967-06-20 --end 1967-06-21 \
  --output_dir ./met_input/ \
  --site_prefix Treynor
```

### Step 3: Manual unit conversion reference

| Source → Target             | Formula                                | Trap if skipped                       |
|-----------------------------|----------------------------------------|---------------------------------------|
| ERA5 precip (kg/m²/s) → mm/hr | × 3600                              | Near-zero rain, no runoff             |
| CMFD precip (mm/3hr) → mm/hr  | ÷ 3                                 | 3× overestimate of rainfall           |
| MSWX precip (mm/day) → mm/hr  | ÷ 24                                | 24× overestimate of rainfall          |
| ERA5 temp (K) → °C            | − 273.15                             | All snow/freeze logic fails silently  |
| ERA5 pressure (Pa) → mbar     | × 0.01                               | Vapor pressure calcs wildly wrong     |
| Specific humidity → RH        | Tetens formula + p conversion        | Wrong ET estimation                   |
| Wind speed (u, v) → speed     | √(u² + v²)                          | Wind = 0 if only one component used   |

### Step 4: Configure meteorology .cfg

In the meteorology configuration file:

```
P_rain_type        | Time_Series   | string  | precip input type
P_rain             | [site_prefix]_rain_rates.txt | string | precip file

T_air_type         | Time_Series   | string  | temperature input type
T_air              | [site_prefix]_T_air.txt | string | temperature file
```

**Variable types allowed:** `Scalar`, `Grid`, `Time_Series`, `Grid_Sequence`

- Use `Scalar` for uniform constant values (e.g., pressure = 1013.25)
- Use `Time_Series` for point-scale temporal data
- Use `Grid` for spatially distributed but time-constant data
- Use `Grid_Sequence` for fully spatiotemporal forcing

## Verification

1. **Precipitation range:** Typical rainfall rates are 0–150 mm/hr for convective
   storms, 0–20 mm/hr for stratiform.  If max > 500 mm/hr, likely wrong units.
2. **Temperature range:** Should be physically reasonable for the location and
   season.  Values > 100 suggest Kelvin not °C.
3. **RH range:** Must be 0–1 (fraction).  If values > 1, data is in percentage.
4. **Plot the data:** Always plot forcing time series before running the model.

```python
import numpy as np
rain = np.loadtxt('Treynor_rain_rates.txt')
assert rain.max() < 500, f"Max rain {rain.max()} mm/hr seems too high"
assert rain.min() >= 0, "Negative rainfall"

t_air = np.loadtxt('Treynor_T_air.txt')
assert t_air.max() < 60, f"Max temp {t_air.max()} °C — still in Kelvin?"
```

## Traps

| Trap                              | Symptom                              | Fix                                   |
|-----------------------------------|--------------------------------------|---------------------------------------|
| Precip in m/s instead of mm/hr    | Model auto-converts again → ~zero    | Provide mm/hr; model converts to m/s  |
| Precip in mm/day instead of mm/hr | 24× too much rain → instant flooding | Divide by 24                          |
| Temperature in K not °C           | Extreme ET, no snowmelt trigger      | Subtract 273.15                       |
| RH as percentage (0–100)          | VP calculation fails or saturates    | Divide by 100                         |
| Wind measurement height wrong     | Incorrect turbulent transfer         | Adjust to match z in .cfg             |
| Missing radiation data            | Use estimated values, not zero       | Zero Qsw → no ET → all runoff        |

## Example

ERA5 hourly forcing for Treynor, Iowa (June 20, 1967):
- Precipitation: convective storm, peak ~175 mm/hr over 30 minutes
- Temperature: 20–25 °C
- RH: 0.6–0.95
- Wind: 2–5 m/s
