# Stage 3: Wind Forcing Preparation

## Purpose

Prepare wind forcing fields for SWAN from reanalysis or forecast data. SWAN can operate with or without wind input; when wind generation is enabled (GEN3 command), spatially and temporally varying wind fields drive local wave growth. When wind is disabled (OFF WINDG), only boundary-prescribed waves propagate through the domain.

## Inputs

| Input | Format | Source | Units |
|-------|--------|--------|-------|
| Wind speed (U10) | NetCDF, ASCII grid | ERA5, CFSR, GFS, or RSS CCMP V3.1 via `tools/fetch_gridded_wind.py` | m/s at 10m elevation |
| Wind direction | NetCDF, ASCII grid | Same as speed | degrees (meteorological) |
| Time series | CSV | Station data | m/s, degrees |

### Key Variables

| Variable | Unit | Range | Description |
|----------|------|-------|-------------|
| Wind speed U10 | m/s | 0 - 60 | 10-meter wind speed |
| Wind direction | degrees | 0 - 360 | Direction FROM which wind blows (met convention) |
| Wind U-component | m/s | -60 to 60 | Eastward component |
| Wind V-component | m/s | -60 to 60 | Northward component |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Wind field files | ASCII grid per timestep | U, V or speed+direction on SWAN grid |

### SWN Commands

Uniform wind (simplest):
```
WIND [vel] [dir]
WIND 10.0 270.0    $ 10 m/s from west
```

Spatially varying wind:
```
INPGRID WIND [xpinp] [ypinp] [alpinp] [mxinp] [myinp] [dxinp] [dyinp] &
        NONSTATionary [tbeginp] [deltinp] [tendinp]
READINP WIND [fac] 'wind_file' [idla] [nhedf] FREE
```

## Procedure

1. **Determine wind input method**
   - `WIND vel dir`: uniform, constant wind (simplest test)
   - `INPGRID WIND`: spatially varying from gridded files
   - `OFF WINDG`: disable wind generation entirely

2. **Convert wind units**
   ```python
   # Knots to m/s
   wind_ms = wind_knots * 0.5144

   # km/h to m/s
   wind_ms = wind_kmh / 3.6

   # U,V components to speed and direction (meteorological)
   speed = np.sqrt(u**2 + v**2)
   direction_met = (270 - np.degrees(np.arctan2(v, u))) % 360
   ```

3. **Check wind direction convention**
   - Meteorological: direction FROM which wind blows (same as SWAN nautical)
   - Oceanographic: direction TO which wind blows (opposite)
   - If SET NAUTICAL in .swn, wind direction is nautical (FROM, CW from N)
   - If SET CARTESIAN in .swn, wind direction is Cartesian (TO, CCW from E)

4. **Write wind field files**
   - For uniform: just add `WIND vel dir` to .swn
   - For gridded: write one ASCII grid per timestep, reference via INPGRID WIND

5. **Verify**
   - Check wind speed range (should be 0-40 m/s for most applications)
   - Check direction matches expected meteorological convention
   - Compare with original source data

## Verification

- [ ] Wind speed in m/s (not knots, km/h, or mph)
- [ ] Direction convention matches SET command in .swn
- [ ] Temporal coverage matches COMPUTE command period
- [ ] Spatial coverage matches or exceeds CGRID extent

```python
# Quick check for uniform wind
import numpy as np
wind_speed = 10.0  # m/s
wind_dir = 270.0   # from west
assert 0 <= wind_speed <= 60, f"Wind speed {wind_speed} out of range"
assert 0 <= wind_dir < 360, f"Direction {wind_dir} out of range"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| **Knots vs m/s** | Wave heights ~2x too large | 1 knot = 0.5144 m/s; divide by 1.944 |
| **Direction convention** | Waves grow opposite to expected | Met = FROM, ocean = TO; add 180° if using ocean convention |
| **Missing wind** | Zero wave growth in deep water | Check that GEN3 is enabled and OFF WINDG is not present |
| **Wind at wrong height** | Under/overestimate wave growth | SWAN expects 10m wind; adjust with log profile if at different height |
| **U10 = 0 everywhere** | No wave generation | Check that wind file is correctly read (READINP format) |
| **NaN in wind field** | SWAN crash or zero growth | Replace NaN with 0 or interpolate from neighbors |

## Example

Simple uniform wind for a 1D flume test:
```
$ In .swn file:
SET NAUTICAL
GEN3               $ Enable 3rd generation wind-wave physics
WIND 10.0 270.0    $ 10 m/s from west (270° nautical)
```

Disable wind (boundary-driven only):
```
GEN3
OFF WINDG           $ No local wind generation
OFF QUAD            $ Disable quadruplet interactions (saves computation)
```

This is the configuration used in the PySWaN test cases — waves are prescribed at the boundary and propagate through the domain without wind growth.


## Choosing the wind source (added after the NDBC 46050 real case)

ERA5/CFSR/GFS are named above, but none of them is in
`/mnt/disk1/Hydrocraft_server/data_ki/dataset_index.yaml` - every
`forcing.reanalysis` entry there is China CMFD, which has no marine coverage.
On this server the working gridded route is `tools/fetch_gridded_wind.py`
(NOAA CoastWatch ERDDAP griddap, no credentials):

| dataset id | product | grid | cadence | record |
|---|---|---|---|---|
| `ccmp_31_LonPM180` | RSS CCMP V3.1 L4 | 0.25 deg | 6 h | 1993-01-02..2024-01-31 |
| `pifscCcmpDailyV21NRT_LonPM180` | CCMP V2.1 NRT | 0.25 deg | 6 h | 2016-present |
| `erdNavgem05D10mWind_LonPM180` | NAVGEM 10 m | 0.5 deg | 3 h | 2013-present |

**Never force the model with the anemometer of the buoy you are scoring.** The
wind field is the dominant control on HSIGN in deep/open water, so a run whose
wind comes from the validation instrument measures the buoy against itself. If
no independent gridded field can be obtained for the period, say so and report
the run as wind-circular rather than reporting its NSE as SWAN skill.

CCMP is 6-hourly while a SWAN NONSTATIONARY wind grid carries a single `[dt]`.
Interpolate the U and V COMPONENTS to the SWAN times - never speed and
direction, which rotates through the wrong quadrant when the direction crosses
360 deg.
