# Skill: Forcing Data Preparation

## Purpose

Convert global meteorological reanalysis data (ERA5, CMFD, MSWX, or local CSV)
into the 3-column daily climate array required by every MARRMoT model:
**[Precipitation, Potential Evapotranspiration, Temperature]** in units
**[mm/d, mm/d, deg C]**.

This is the most error-prone stage in the entire pipeline because MARRMoT
performs **no internal unit conversion or validation**. Wrong units produce
plausible-looking but entirely wrong results.

## Inputs

| Input                  | Source          | Format          | Unit           |
|------------------------|-----------------|-----------------|----------------|
| Precipitation          | ERA5 / CMFD     | NetCDF / CSV    | kg/m2/s or m/d |
| 2m Temperature         | ERA5 / CMFD     | NetCDF / CSV    | K or deg C     |
| PET (or Tmin/Tmax)     | Pre-computed    | NetCDF / CSV    | mm/d or W/m2   |
| Latitude / Longitude   | Site metadata   | Scalar          | degrees        |
| Date range             | User choice     | YYYY-MM-DD      | -              |

## Outputs

| Output               | Format   | Unit   | Columns                        |
|----------------------|----------|--------|--------------------------------|
| `forcing.csv`        | CSV      | mixed  | date, P_mm_d, Ep_mm_d, T_degC |

The CSV has a 4-line header (comments starting with `#`) followed by a
column-name row, then daily values.

## Procedure

1. **Load source data** from NetCDF (gridded) or CSV (point).
   For gridded data, extract the nearest grid cell to (lat, lon).

2. **Convert precipitation to mm/d**:
   - ERA5 `tp`: usually m/d → multiply by 1000
   - ERA5 accumulation: kg/m2/s → multiply by 86400
   - CMFD: mm/3h → sum 8 sub-daily values per day
   - Already mm/d → no conversion

3. **Convert temperature to deg C**:
   - ERA5 `t2m`: Kelvin → subtract 273.15
   - Already deg C → no conversion

4. **Obtain PET in mm/d**:
   - If PET variable exists: convert from m/d (multiply by 1000) or
     take absolute value (ERA5 PET is negative by convention)
   - If only radiation available: **do NOT pass radiation directly**.
     Use Penman-Monteith or Hargreaves equation.
   - If only Tmin/Tmax: use Hargreaves: `PET = 0.0023 * Ra * sqrt(Tmax-Tmin) * (Tmean+17.8)`
   - Monthly PET: divide by days in month

5. **Assemble array** in column order `[P, Ep, T]`.
   **Not** `[P, T, Ep]` — this is silent and catastrophic (dt_011).

6. **Write CSV** with header comments documenting units and period.

## Verification

After conversion, check these sanity bounds:

| Variable | Typical range     | Red flag                        | Trap  |
|----------|-------------------|---------------------------------|-------|
| P mean   | 0.5 - 15 mm/d    | > 50 mm/d → likely wrong unit   | dt_001 |
| P mean   | 0.5 - 15 mm/d    | < 0.01 mm/d → likely m/d        | dt_003 |
| Ep mean  | 0.5 - 8 mm/d     | > 20 mm/d → likely W/m2         | dt_004 |
| Ep       | always >= 0       | < 0 → sign convention error     | dt_004 |
| T mean   | -10 to 35 deg C   | > 100 → Kelvin not converted    | dt_006 |
| T mean   | -10 to 35 deg C   | > 50 → Fahrenheit not converted | dt_007 |

## Traps

- **dt_001**: CMFD precipitation is mm/3h. Passing raw values as mm/d
  gives 8x too much rain (3-hourly data has 8 steps/day).
- **dt_002**: ERA5 precipitation in kg/m2/s. Must multiply by 86400.
  Forgetting this gives ~0.00005 mm/d instead of ~4 mm/d.
- **dt_003**: Some GCM outputs use m/d. Must multiply by 1000.
- **dt_004**: Radiation (W/m2 or MJ/m2/d) is NOT PET. Must convert via
  Penman-Monteith. Passing radiation directly gives PET ~200 mm/d.
- **dt_005**: Monthly PET must be divided by days_in_month.
  Forgetting gives ~30x too much PET in January.
- **dt_006**: ERA5 temperature is in Kelvin (~290 K). If passed directly,
  snow/rain threshold models interpret it as 290 deg C, producing zero snow.
- **dt_011**: Column swap [P, T, Ep] instead of [P, Ep, T] causes temperature
  to be used as PET and vice versa. Model runs without error.

## Example

```bash
python tools/convert_forcing.py \
  --input /data/era5_daily_2000_2010.nc \
  --format era5 \
  --lat 35.29 --lon -85.97 \
  --start 2000-01-01 --end 2010-12-31 \
  --output forcing.csv
```

Expected output (first 3 data lines):
```
date,P_mm_d,Ep_mm_d,T_degC
2000-01-01,2.3400,0.8100,3.2000
2000-01-02,0.0000,0.7500,1.8000
2000-01-03,5.6700,0.6900,-0.5000
```
