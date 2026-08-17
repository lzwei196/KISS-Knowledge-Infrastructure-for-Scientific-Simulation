# Stage 4: Meteorological Forcing Preparation

## Purpose

Convert global reanalysis or gridded meteorological data (CMFD, MSWX, ERA5, NASA POWER)
to Noah-MP HRLDAS LDASIN NetCDF format with correct variable names, units, and file
naming conventions.

## Inputs

| Input | Source | Variables | Native Units |
|-------|--------|-----------|-------------|
| CMFD | China Meteorological Forcing Dataset | temp, shum, wind, pres, srad, lrad, prec | °C, kg/kg, m/s, Pa, W/m², W/m², mm/hr |
| ERA5 | ECMWF Reanalysis v5 | t2m, d2m, u10, v10, sp, ssrd, strd, tp | K, K, m/s, m/s, Pa, J/m², J/m², m |
| MSWX | Multi-Source Weather | Temp, Humidity, Wind, ... | °C, varies |
| NASA POWER | NASA Prediction of Energy | T2M, QV2M, WS2M, PS, ... | °C, kg/kg, m/s, kPa |
| FLUXNET2015 | Eddy-covariance tower FULLSET | TA_F, SW_IN_F, LW_IN_F, VPD_F, PA_F, WS_F, P_F | °C, W/m², W/m², hPa, **kPa**, m/s, mm/interval |

## Outputs

| Output | Format | Naming | Description |
|--------|--------|--------|-------------|
| LDASIN files | NetCDF | `YYYYMMDDHH.LDASIN_DOMAIN1` | One file per forcing timestep |

## Procedure

### 1. Critical unit conversions

These conversions are **mandatory** and failure to apply them causes silent model failure:

| Variable | Noah-MP Unit | CMFD → Noah-MP | ERA5 → Noah-MP |
|----------|-------------|----------------|----------------|
| T2D | **K** | T_C + 273.15 | Already K |
| Q2D | **kg/kg** | Already kg/kg | Compute from T2M, D2M |
| U2D | **m/s** | Already m/s | Already m/s |
| V2D | **m/s** | Already m/s | Already m/s |
| PSFC | **Pa** | Already Pa | Already Pa |
| SWDOWN | **W/m²** | Already W/m² | J/m² ÷ 3600 → W/m² |
| LWDOWN | **W/m²** | Already W/m² | J/m² ÷ 3600 → W/m² |
| RAINRATE | **mm/s** | mm/hr ÷ 3600 | m/hr × 1000 ÷ 3600 |

FLUXNET2015 → Noah-MP (`--source fluxnet`): `TA_F + 273.15`; `PA_F × 1000`
(**kPa**, not hPa — `convert_pressure()` now tests the kPa branch first, it used
to be dead code and turned 100 kPa into 10 kPa); `P_F ÷ interval_seconds`;
`Q2D` from `VPD_F`/`TA_F`/`PA_F` via
`RH = 100·(1 − VPD/e_s(TA))` then `ki_tools_common.humidity.rh_to_specific_humidity`;
`U2D = WS_F`, `V2D = 0` (Noah-MP only uses `sqrt(u²+v²)`).

### 2. Humidity conversion (ERA5 specific)

ERA5 provides dewpoint temperature (D2M) instead of specific humidity:

```python
# Step 1: Vapor pressure from dewpoint
e = 611.2 * exp(17.67 * (D2M - 273.15) / (D2M - 273.15 + 243.5))  # Pa

# Step 2: Specific humidity from vapor pressure
Q2D = 0.622 * e / (PSFC - 0.378 * e)  # kg/kg
```

### 3. Shortwave radiation clipping

After temporal interpolation, SWDOWN can become slightly negative at night.
**Always clip to zero**: `SWDOWN = max(0, SWDOWN)`.

### 4. Wind speed decomposition

CMFD provides scalar wind speed only. Decompose equally:
```python
U2D = WIND / sqrt(2)
V2D = WIND / sqrt(2)
```

### 5. LDASIN file structure

Each LDASIN file is a NetCDF with dimensions `(Time=1, south_north, west_east)`:

```
netcdf 2010010100.LDASIN_DOMAIN1 {
  dimensions:
    Time = 1 ;
    south_north = NY ;
    west_east = NX ;
  variables:
    float T2D(Time, south_north, west_east) ;
    float Q2D(Time, south_north, west_east) ;
    float U2D(Time, south_north, west_east) ;
    float V2D(Time, south_north, west_east) ;
    float PSFC(Time, south_north, west_east) ;
    float SWDOWN(Time, south_north, west_east) ;
    float LWDOWN(Time, south_north, west_east) ;
    float RAINRATE(Time, south_north, west_east) ;
}
```

### 6. File naming convention

Files are named by their valid time: `YYYYMMDDHH.LDASIN_DOMAIN1`
- For 3-hourly: `2010010100`, `2010010103`, `2010010106`, ...
- For hourly: `2010010100`, `2010010101`, `2010010102`, ...
- **No minutes** in filename (HH only, no MM)

**This is a hard limit, not a style note.** The driver rebuilds the input path
from the model clock as `olddate(1:4)//(6:7)//(9:10)//(12:13)` — 10 characters,
minutes discarded (`module_NoahMP_hrldas_driver.F`). Forcing finer than hourly is
therefore unreachable in this build: `forcing_timestep < 3600` makes two model
times resolve to the same filename. `validate_inputs` rejects sub-hourly
timesteps, and `--source fluxnet` aggregates half-hourly (`*_HH`) sites to hourly
first (precip summed, states/fluxes averaged).

### 6b. Timestamps are UTC — site networks are not (dt_019)

HRLDAS computes the solar hour angle from the LDASIN timestamp as
`TLOCTIM = hour + longitude/15` (`CALC_DECLIN`), i.e. it treats the stamp as UTC.
FLUXNET (and most site networks) report LOCAL STANDARD TIME. Converting a site
record without shifting it puts COSZ out of phase with the observed SWDOWN by the
site's UTC offset — the energy balance is then solved for the wrong time of day
with no error message. `--source fluxnet` therefore REQUIRES `--utc_offset`.

Check after conversion: the LDASIN file carrying the daily maximum SWDOWN must
lie within ~1 h of `(12 − longitude/15) mod 24` UTC.

### 7. Using the tool

```bash
python ki/tools/convert_forcing_to_noahmp.py \
  --input_dir KISSPATH_FORCING/cmfd/ \
  --output_dir ./forcing/ \
  --lat 33.0 --lon 117.0 \
  --start_date 2010-01-01 --end_date 2010-12-31 \
  --timestep 3600
```

## Verification

- [ ] T2D values are in range [200, 340] K — not Celsius!
- [ ] Q2D values are in range [0, 0.04] kg/kg — not g/kg or %RH!
- [ ] PSFC values are in range [50000, 110000] Pa — not hPa!
- [ ] RAINRATE values are in range [0, 0.1] mm/s — not mm/hr!
- [ ] SWDOWN >= 0 everywhere (no negative values)
- [ ] LWDOWN in range [50, 500] W/m²
- [ ] Number of files matches expected: `period_hours / forcing_timestep_hours`
- [ ] File naming follows `YYYYMMDDHH.LDASIN_DOMAIN1` convention
- [ ] Run the universal preflight on the OUTPUT directory:
      `python auto_dissect_multi_agent/validators/preflight_forcing.py <ldasin_dir>`
      — it now auto-detects the `noahmp_ldasin` profile and samples up to 200
      timesteps across the period (LDASIN files are not `*.nc`, so before this
      the check returned "unable to detect data source" and silently did nothing)
- [ ] For site forcing: SWDOWN daily peak sits at the expected UTC solar noon

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dt_001 | NaN/crash in saturation VP | T2D in Celsius instead of Kelvin (+273.15) |
| dt_002 | Extreme runoff, soil flooded | RAINRATE in mm/hr not mm/s (÷3600) |
| dt_003 | Extreme latent heat | Q2D is RH% not kg/kg (recompute) |
| dt_004 | Energy balance error | Negative SWDOWN from interpolation (clip to 0) |
| dt_005 | Wrong flux magnitudes | PSFC in hPa not Pa (×100) |
| dt_013 | Gaps in output timeseries | Missing LDASIN files in sequence |

## Example

Converting one hour of CMFD data at Bengbu (32.94°N, 117.39°E):

```
Input:  temp=25.3°C, shum=0.015 kg/kg, wind=2.5 m/s,
        pres=101200 Pa, srad=450 W/m², lrad=340 W/m², prec=1.2 mm/hr

Output: T2D=298.45 K, Q2D=0.015 kg/kg, U2D=1.77 m/s, V2D=1.77 m/s,
        PSFC=101200 Pa, SWDOWN=450 W/m², LWDOWN=340 W/m²,
        RAINRATE=0.000333 mm/s
```
