# S2: Forcing Data Preparation

## Purpose
Convert global reanalysis atmospheric data and tidal constituents into ROMS-compatible NetCDF forcing files with correct units, grid interpolation, and time reference. This is the stage where most **silent unit-conversion errors** occur.

## Inputs
| Input               | Format       | Source              | Key Variables                           |
|---------------------|-------------|---------------------|-----------------------------------------|
| Atmospheric data    | GRIB/NetCDF | ERA5, GFS, NARR     | Wind, Tair, Pair, humidity, precip, rad |
| Tidal constituents  | NetCDF      | TPXO, FES2014       | Amplitude, phase for M2, S2, K1, O1...  |
| ROMS grid file      | NetCDF      | Stage s1 output     | lon_rho, lat_rho for interpolation      |
| River discharge     | CSV/NetCDF  | USGS, GRDC          | Q (m³/s), temperature, salinity          |

## Outputs
| Output              | Format  | Key Variables                                     | Time    |
|---------------------|---------|----------------------------------------------------|---------|
| Atmospheric forcing | NetCDF  | Uwind, Vwind, Tair, Pair, Qair, rain, swrad, lwrad| frc_time|
| Tidal forcing       | NetCDF  | tide_Eamp, tide_Ephase, tide_Cangle, tide_Cphase  | periodic|
| River forcing       | NetCDF  | river_transport, river_temp, river_salt            | riv_time|

## Procedure

1. **Download reanalysis data** covering the simulation period plus 1 day buffer on each end for time interpolation.

2. **Run atmospheric converter**:
   ```bash
   python3 ki/tools/convert_forcing.py \
     --source /data/era5/ --source-format era5 \
     --grid Sandy_roms_grid.nc --output forcing_era5.nc \
     --type atmospheric --time-ref "days since 2012-10-01"
   ```

3. **Run tidal converter** (if open boundaries):
   ```bash
   python3 ki/tools/convert_forcing.py \
     --source /data/tpxo9/ --source-format tpxo \
     --grid Sandy_roms_grid.nc --output tides.nc \
     --type tidal
   ```

4. **Validate output ranges** (see Verification below).

## Verification

### Critical Range Checks
| Variable | Expected Range         | If Outside                          | Triplet |
|----------|------------------------|-------------------------------------|---------|
| Tair     | -60 to +50 °C         | Likely still in Kelvin (subtract 273.15) | dt_001 |
| Pair     | 850 to 1100 mb        | Likely in Pa (divide by 100)        | —       |
| Uwind    | -50 to +50 m/s        | OK if met-standard                  | —       |
| Qair     | 0 to 0.04 kg/kg       | If > 1: still in % RH (convert)    | dt_015  |
| rain     | 0 to 0.01 kg/m²/s     | If > 1: mm/day not m/s             | dt_008  |
| swrad    | 0 to 1400 W/m²        | Should never be negative            | —       |
| lwrad    | -400 to +500 W/m²     | Can be net (positive or negative)   | —       |

### Time Reference Check
Open the forcing file and verify `frc_time` values make sense:
```python
import netCDF4 as nc
ds = nc.Dataset("forcing_era5.nc")
t = ds.variables["frc_time"]
print(f"Time range: {nc.num2date(t[0], t.units)} to {nc.num2date(t[-1], t.units)}")
# Should span your simulation period
```

## Traps

**dt_001: Temperature in Kelvin instead of Celsius.**
ERA5, GFS, and most reanalysis products provide temperature in **Kelvin**. ROMS expects **Celsius**. If not converted, the model will compute unrealistic densities and SST will be ~300°C. The `convert_forcing.py` tool applies this conversion automatically. **Always check Tair range after conversion.**

**dt_003: Time reference mismatch.**
ROMS interpolates forcing in time using `ocean_time` vs `frc_time`. If these use different reference dates (e.g., forcing uses "days since 1900-01-01" but ocean.in TIME_REF is "20120101"), the model will use data from the wrong time or extrapolate to NaN. **Always ensure TIME_REF in ocean.in matches forcing file time units.**

**dt_006: BULK_FLUXES flag mismatch.**
If `BULK_FLUXES` is defined in the application header (`.h` file), ROMS computes surface fluxes internally from atmospheric variables (Uwind, Tair, etc.). If `BULK_FLUXES` is NOT defined, ROMS expects pre-computed fluxes (sustr, svstr, shflux, etc.). Providing atmospheric variables without BULK_FLUXES means they are **ignored** — the model runs with zero forcing.

**dt_008: Precipitation units.**
ERA5 provides total precipitation as **m/step** (accumulated). GFS provides as **kg/m²/s** (rate). ROMS expects **kg/m²/s**. Converting from mm/day to m/s without the density factor creates a 1000× error in freshwater flux.

**dt_015: Humidity units.**
ERA5 provides dewpoint temperature (K), which must be converted to specific humidity (kg/kg) via Clausius-Clapeyron. Some datasets provide relative humidity (%). ROMS with BULK_FLUXES expects specific humidity (kg/kg). A value of "80" (meaning 80% RH) interpreted as kg/kg is 80× too large.

## Example
```bash
# Full ERA5 forcing conversion for Sandy simulation
python3 ki/tools/convert_forcing.py \
  --source /data/era5/2012/ --source-format era5 \
  --grid Sandy_roms_grid.nc --output forcing_sandy.nc \
  --type atmospheric --time-ref "days since 2012-10-01" \
  --overwrite

# Verify temperature range
python3 -c "
import netCDF4 as nc
ds = nc.Dataset('forcing_sandy.nc')
t = ds.variables['Tair'][:]
print(f'Tair: min={t.min():.1f}, max={t.max():.1f} C')
# Expected: ~5 to 30 C for US East Coast October
"
```
