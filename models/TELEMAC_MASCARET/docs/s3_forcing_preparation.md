# S3: Forcing Preparation

## Purpose

Convert external forcing data (meteorological, tidal, river discharge) into
formats accepted by TELEMAC. Apply necessary unit conversions and temporal
interpolation to ensure the forcing is physically consistent with the model.

## Inputs

| Input               | Format        | Source                                    |
|---------------------|---------------|-------------------------------------------|
| Wind velocity       | CSV / NetCDF  | ERA5, GFS, weather station                |
| Atmospheric pressure| CSV / NetCDF  | ERA5, GFS, weather station                |
| Tidal constituents  | CSV / TPXO    | Tidal harmonic databases                  |
| River discharge     | CSV           | Gauging stations, hydrological models     |
| Rain / evaporation  | CSV / NetCDF  | ERA5, satellite products                  |

## Outputs

| Output               | Format      | Description                              |
|----------------------|-------------|------------------------------------------|
| Met forcing file     | .slf or .txt| Wind + pressure on mesh or as time series|
| Liquid boundary file | ASCII       | Prescribed elevations/discharges vs time |
| Tidal harmonic file  | .txt        | Harmonic constituents for boundary nodes |

## Procedure

1. **Collect source data** for the simulation period plus spin-up.

2. **Check and convert units**:
   | Variable    | TELEMAC expects | Common source    | Conversion          |
   |-------------|-----------------|------------------|---------------------|
   | Wind speed  | m/s             | knots            | x 0.5144            |
   | Pressure    | Pa              | hPa / mbar       | x 100               |
   | Rain        | mm/s            | mm/hr            | / 3600              |
   | Discharge   | m^3/s           | L/s              | x 0.001             |
   | Temperature | degrees C       | degrees F        | (F-32) x 5/9        |

3. **Convert forcing data**:
   ```bash
   python convert_forcing.py --input met_data.csv --output forcing.txt \
       --variables wind_x,wind_y,pressure \
       --wind-unit knots --pressure-unit hPa
   ```

4. **Set up liquid boundaries** in the steering file:
   ```
   LIQUID BOUNDARIES FILE = 'boundaries.txt'
   PRESCRIBED FLOWRATES   = 0.;150.0     / boundary 1 = sea; boundary 2 = river
   PRESCRIBED ELEVATIONS  = 2.5;0.       / tidal elevation at boundary 1
   ```

5. **Time interpolation**: TELEMAC linearly interpolates between forcing
   time steps. Ensure forcing frequency is adequate:
   - Tidal boundaries: at least hourly
   - Wind: hourly or 3-hourly
   - River discharge: daily minimum

## Verification

- [ ] All units match TELEMAC expectations (m/s, Pa, m^3/s)
- [ ] Time stamps cover the simulation period
- [ ] No gaps or NaN values in the forcing data
- [ ] Forcing values are physically reasonable (wind < 50 m/s, pressure 900-1100 hPa)
- [ ] Boundary numbering matches the .cli file

## Traps

- **dt_003**: Wind in knots instead of m/s produces ~2x overestimation.
- **dt_004**: Pressure in hPa instead of Pa produces 100x underestimation,
  making pressure gradient forces negligible.
- **dt_008**: Discharge in L/s instead of m^3/s produces 1000x underflow.
- **dt_010**: Tidal amplitudes in cm instead of m: 100x error in water levels.
- **dt_011**: Rain in mm/hr instead of mm/s: 3600x overestimation.

## Example

```bash
# Convert ERA5 CSV forcing to TELEMAC format
python convert_forcing.py \
    --input era5_extracted.csv \
    --output met_forcing.txt \
    --variables u10,v10,msl,tp \
    --pressure-unit hPa \
    --rain-unit mmhr \
    --format liquid_boundary

# Verify output
head -5 met_forcing.txt
# Expected: T(s) u10(m/s) v10(m/s) msl(Pa) tp(mm/s)
```
