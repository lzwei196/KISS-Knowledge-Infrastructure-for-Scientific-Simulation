# Stage 01 — Site preparation

## Purpose
Create the `<run>.SIT` file that tells EPIC where and on what slope the
simulated field sits.

## Inputs
- Latitude, longitude (WGS84)
- Elevation (m, from SRTM or HWSD DEM)
- Slope (m/m, 0.001 to 0.2)
- Atmospheric CO2 (ppm; use 410 for 2020-era runs)

## Outputs
`<workspace>/<run>.SIT`, with:
- Line 1: free-form run title
- Line 2: filename echo
- Line 4: lat, lon, elev, slope, CO2 (5 x F8.2)
- Lines 5-7: watershed area, subarea, channel characteristics (from template)

## Procedure
1. Copy `templates/umstead.SIT` as `<run>.SIT`.
2. Load the text (CRLF-safe).
3. Overwrite lines 0, 1, 3 with user values.
4. Leave remaining lines untouched.

## Verification
- Line count equals the template.
- Line 4 parses as 5 floats.
- `.OUT` echoes the site title — cross-check.

## Traps
- **CRLF line endings**: EPIC is a Windows EXE; write CRLF.
- **Column alignment**: F8.2. Always use `f"{v:>8.2f}"`, never `str(v)`.
- **Negative longitude**: West-negative (-78.74 for Raleigh NC).

## Example
```bash
python tools/build_site_file.py --name raleigh --lat 35.86 --lon -78.74 \
    --elev 94.0 --slope 0.01 --co2 410.0 --workspace /tmp/epic_run
```
