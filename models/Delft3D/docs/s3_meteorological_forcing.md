# Stage 3: Meteorological Forcing

## Purpose

Prepare atmospheric forcing data (wind, pressure, heat fluxes) for the Delft3D
simulation. Meteorological forcing drives wind-driven currents, storm surge,
wave generation, and heat exchange at the water surface.

## Inputs

| Input | Format | Source | Typical Resolution |
|-------|--------|--------|--------------------|
| ERA5 reanalysis | NetCDF | Copernicus CDS | 0.25° / hourly |
| CMFD | NetCDF | CAS / TPDC | 0.1° / 3-hourly |
| Station data | CSV | Weather stations | Point / hourly |
| VIC forcing | CSV | VIC model | Grid / daily |

## Outputs

| Output | Format | Variables |
|--------|--------|-----------|
| Wind file | .wnd | Time, speed (m/s), direction (deg FROM N) |
| Pressure file | .amp | Time, atmospheric pressure (Pa) |
| Air temp file | .amt | Time, air temperature (°C) |
| Humidity file | .amr | Time, relative humidity (%) |
| Cloud cover file | .amc | Time, cloud fraction (0-1) |

## Procedure

1. **Download ERA5** data for domain + time period (or use existing CMFD/VIC)
2. **Extract variables**: u10, v10, msl/sp, t2m, d2m, tcc, ssrd, strd, tp
3. **Apply unit conversions** (see table below)
4. **Compute derived variables**: wind speed/direction from u10/v10, RH from T/Td
5. **Spatially aggregate** (uniform) or regrid (spatially varying)
6. **Write Delft3D-format files**

```bash
python ki/tools/convert_forcing_to_delft3d.py \
  --era5_file era5_hourly_2020.nc \
  --domain_bounds "1.0 51.0 4.0 53.0" \
  --start_date 2020-01-01 --end_date 2020-02-01 \
  --output_dir forcing/
```

## Unit Conversion Table

| Variable | ERA5 / CMFD | Delft3D expects | Conversion |
|----------|-------------|-----------------|------------|
| Temperature | K | °C | T_C = T_K - 273.15 |
| Pressure (sp) | Pa | Pa | None |
| Pressure (msl) | Pa (sometimes hPa) | Pa | ×100 if hPa |
| Wind speed | m/s (u10, v10) | m/s (speed + direction) | sqrt(u²+v²), atan2 |
| Wind direction | — | Degrees FROM N (nautical) | (270 - atan2(v,u)) mod 360 |
| Rel. humidity | — (compute from T,Td) | % (0-100) | Magnus formula |
| Cloud cover | Fraction (0-1) | Fraction (0-1) | None (but some give %) |
| Shortwave radiation | J/m² (accumulated) | W/m² (instantaneous) | Divide by timestep (s) |
| Precipitation | m (accumulated) | mm/hr | ×1000 / dt_hours |

## Verification

- Wind speed: 0-40 m/s typical, > 60 extreme
- Pressure: 95,000-107,000 Pa (sea level)
- Temperature: -40 to +50 °C
- Relative humidity: 20-100% (coastal typically > 60%)
- Shortwave: 0-1200 W/m² (0 at night)
- Wind direction: 0-360° (check seasonal patterns match expectation)

```python
import numpy as np
data = np.loadtxt("forcing/wind.wnd", comments="#")
times, speeds, dirs = data[:, 0], data[:, 1], data[:, 2]
print(f"Wind speed: mean={speeds.mean():.1f}, max={speeds.max():.1f} m/s")
print(f"Direction range: [{dirs.min():.0f}, {dirs.max():.0f}] deg")
```

## Traps

1. **Pressure in hPa instead of Pa (dt_002)**: ERA5 surface pressure is Pa, but
   many datasets and GUIs show hPa. If you pass 1013.25 instead of 101325, the
   inverse barometer effect is 100× too small. This is a **silent error** — the
   model will run fine but water levels will be systematically wrong by ~10 cm.

2. **Wind direction FROM vs TO (dt_003)**: Delft3D uses nautical convention
   (direction wind comes FROM). Some datasets use mathematical convention
   (direction wind goes TO). A 180° error reverses storm surge direction.
   Check: during a known storm, does the wind direction make physical sense?

3. **Shortwave radiation negative (dt_006)**: After temporal interpolation,
   night-time SW can go slightly negative. Always clip to max(0, SW).

4. **Relative humidity as fraction (dt_004)**: If RH is 0-1 instead of 0-100,
   the heat flux model computes wrong evaporation and sensible heat. Check
   `max(RH)` — if < 1.5, it's fraction and needs ×100.

5. **Accumulated vs instantaneous**: ERA5 radiation/precipitation are often
   accumulated over the forecast step. You must divide by the timestep (3600s
   for hourly) to get instantaneous fluxes.

## Example

```python
# Verify ERA5 wind conversion
import numpy as np

u10 = np.array([3.0, -2.0, 0.0, 5.0])  # m/s eastward
v10 = np.array([4.0, 0.0, -3.0, 0.0])  # m/s northward

speed = np.sqrt(u10**2 + v10**2)
# Nautical direction: FROM where wind blows
direction = (270 - np.degrees(np.arctan2(v10, u10))) % 360

for i in range(len(u10)):
    print(f"u={u10[i]:+.1f}, v={v10[i]:+.1f} → "
          f"speed={speed[i]:.1f} m/s, dir={direction[i]:.0f}° (FROM)")
# Expected: NE wind (from 233°), E wind (from 270°), S wind (from 180°), W wind (from 90°)
```
