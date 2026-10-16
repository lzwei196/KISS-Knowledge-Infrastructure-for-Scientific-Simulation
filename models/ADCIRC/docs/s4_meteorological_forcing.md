# S4: Meteorological Forcing (fort.22)

## Purpose

Prepare wind and atmospheric pressure forcing for ADCIRC storm surge and wind-driven circulation simulations. The meteorological forcing is the primary driver of storm surge and must be properly formatted with correct units. ADCIRC supports 30+ meteorological formats via the NWS parameter.

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| Wind velocity | GFS, ERA5, HRRR, HWRF | GRIB2/netCDF | 10m wind u,v components |
| Atmospheric pressure | GFS, ERA5 | GRIB2/netCDF | Sea-level pressure |
| Hurricane track | NHC best-track, ATCF | CSV/text | For parametric wind models |

## Outputs

| Output | File | Format | Description |
|--------|------|--------|-------------|
| Control file | `fort.22` | ASCII | NWS-specific control/header |
| Pressure field | `fort.221` | OWI ASCII | Gridded pressure (mb) |
| Wind field | `fort.222` | OWI ASCII | Gridded wind u,v (m/s) |

## Procedure

### NWS Format Selection

| NWS | Format | Input | Best For |
|-----|--------|-------|----------|
| 0 | None | — | Tidal-only runs |
| 8 | Holland parametric | Hurricane track params | Quick hurricane estimates |
| 12 | OWI gridded | fort.221 + fort.222 | Real-time forecasting |
| 13 | OWI netCDF | fort.221.nc + fort.222.nc | Large hindcast studies |
| 14 | GRIB2 direct | GRIB2 files | Direct NWP model coupling |

### OWI Format Details (NWS=12)

The OWI format is the most commonly used for operational forecasting.

**fort.22 (control file)**:
```
1             ! NWSET: one grid overlay (fort.221 and fort.222)
0             ! NWBS: no blank wind/pressure snapshots
1.0           ! DWM: unit wind multiplier
```

**fort.221 (pressure) header per timestep**:
```
iLat=  29iLong=  41DX=0.2500DY=0.2500SWLat= 24.0000SWLon=-98.0000DT=200508250000
```

**Critical fields**:
- `iLat`, `iLong`: Grid dimensions (number of points)
- `DX`, `DY`: Grid spacing in degrees
- `SWLat`, `SWLon`: Southwest corner coordinates
- `DT`: Datetime string (YYYYMMDDHHmm)

**Data values**: eight fixed-width 10.4f values per line (last line may be shorter). One header per time in each file; wind has a complete U block followed by V without a second header. File start/end dates occupy columns 56–65 and 71–80. Snapshot coordinates follow native fixed columns; unrepresentable coordinates are rejected. Numeric rounding is at most 0.00005 in output units.


### Strict converter contract (2026-10 repair)

Supported inputs are CSV (`time,lat,lon,u10,v10,pressure`) and ERA5 NetCDF
(`u10,v10,msl` with recognized units). ERA5 `sp` is not a substitute for `msl`.
CSV pressure semantics remain the caller's responsibility: use sea-level pressure
for coastal applications; do not relabel land surface pressure as sea-level pressure.
CSV defaults are m/s and mb; set `--wind_unit` and `--pressure_unit` for other
supported units. No magnitude-based conversion, clipping, or gap filling occurs.

Start/end arguments are inclusive UTC instants (a date means midnight);
`--step_seconds` defaults to 3600. Every requested snapshot must include every
cell of the complete uniform grid, including the declared SW/NE endpoints.
`--resolution` must match both source axes; resampling must be explicit upstream.
All input validation and staged output validation precede publishing files.
Existing forcing files are refused. `forcing_provenance.json` records source
SHA256s, units, cadence and zero locally filled values.

**Start-time alignment (required).** ADCIRC does not use the `DT=` stamps to place
snapshots in time. It reads snapshots one after another: the first snapshot is
applied at the run time origin and each next one `WTIMINC` seconds later
(`src/wind.F`: `WTIME1 = STATIM*86400` for `NWS=+12`; `WTIME1 = TimeLoc` for
`NWS=-12`). For `NWS=+12` the origin is the cold-start time, also on a hot start
(ADCIRC fast-forwards from the cold start). For `NWS=-12` the origin is the
hot-start time. The converter writes `NWBS=0` (line 2 of fort.22), so set
`--start_date` to that origin. Example: forcing that starts on August 25 for a
cold start on August 26 covers the run but applies every weather snapshot one day
late. If the file must start earlier, set line 2 of fort.22 to `-N`, where
`N = (origin - first snapshot) / WTIMINC` is a whole number; ADCIRC then skips
the first `N` snapshots (`src/owiwind.F`, `numSkipSnaps`). A positive `NWBS`
instead inserts `N` blank snapshots (zero wind, background pressure) before the
data. See the [official NWS12 documentation](https://wiki.adcirc.org/NWS12).

Set native `WTIMINC` to the converter cadence. Cover the entire native run plus
the next interpolation snapshot; ADCIRC can silently use blank forcing after
EOF. The weather grid must enclose every mesh node, with strictly greater
maximum latitude/longitude on its N/E edges. The converter does not read fort.14
or fort.15, so verify these requirements (start alignment, coverage, enclosure)
before execution.

Native format reference: [official ADCIRC NWS12 documentation](https://wiki.adcirc.org/NWS12),
and `src/owiwind.F` fixed-column reads (not a free-format whitespace parser).
The regression test is `python -m unittest discover -s tests -p test_owi_contract.py -v`.

### Unit Conversions

| Variable | Source Unit | ADCIRC (OWI) Unit | Conversion |
|----------|-----------|-------------------|------------|
| Pressure | Pa | mb (hPa) | ÷ 100 |
| Wind speed | knots | m/s | × 0.5144 |
| Wind speed | km/h | m/s | ÷ 3.6 |

**WARNING**: ADCIRC internally converts the absolute pressure from mb to a pressure
head in meters of water (`src/owiwind.F`, `NWS12GET`: `PRN = 100 × P_actual / (RHOWAT0 × G)`).
This is the absolute pressure head, not a deficit from a standard pressure; blank
or uncovered nodes get the background pressure the same way (`PRN = 100 × PRBCKGRND / (RHOWAT0 × G)`).
Getting the input units wrong (e.g., Pa instead of mb) produces extreme or zero surge (dt_003).

### Wind Drag

ADCIRC uses the Garratt (1977) drag law by default:
```
Cd = 0.001 × (0.75 + 0.067 × W10)
```
Capped at Cd = 0.003 for W10 > 33.6 m/s (dt_004).

For major hurricanes (Category 3+), consider alternative drag laws:
- Powell et al. (2003): Drag reduction at high winds
- Donelan et al. (2004): Cap at lower value

## Verification

Run the converter's native-format validator; malformed records and missing values
raise an error instead of being skipped:

```bash
python -c 'from tools.convert_forcing_to_adcirc import validate_outputs; validate_outputs("/path/to/forcing")'
```

Also verify mesh coverage, simulation duration and `WTIMINC` as described above.
A plausible value range alone does not establish correct units or complete data.

## Traps

| Trap | ID | Symptom |
|------|----|---------|
| Pressure in Pa not mb | dt_003 | Extreme surge or zero surge |
| Wind in knots not m/s | dt_010 | Surge ~50% of expected (knots) or 3.6x (km/h) |
| OWI header off-by-one | dt_007 | Wind applied at wrong locations |
| Grid mismatch with mesh domain | — | Zero forcing over mesh area |
| WTIMINC mismatch with data interval | — | Temporal interpolation errors |

## Example

```bash
# Convert ERA5 to OWI format
python ki/tools/convert_forcing_to_adcirc.py \
    --input_dir /data/era5/katrina/ \
    --format era5_nc \
    --domain_sw 24.0,-98.0 --domain_ne 31.0,-88.0 \
    --resolution 0.25 \
    --start_date 2005-08-25 --end_date 2005-09-01 \
    --output_dir ./

# Verify output
ls -la fort.22 fort.221 fort.222
head -3 fort.221
```
