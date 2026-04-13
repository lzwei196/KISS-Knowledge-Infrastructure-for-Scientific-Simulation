# S1: Input Data Preparation

## Purpose

Prepare geological survey data (borehole logs, field measurements, digital
elevation models) into GemPy-compatible CSV format with correct units and
column conventions.

## Inputs

| Input               | Format    | Description                              |
|---------------------|-----------|------------------------------------------|
| Raw surface points  | CSV/Excel | Borehole or mapped contact locations     |
| Raw orientations    | CSV/Excel | Structural measurements (strike/dip)     |
| Coordinate metadata | —         | CRS, unit (meters/km/feet), datum        |

### Surface Points Required Columns

| Column     | Type    | Unit           | Notes                              |
|------------|---------|----------------|------------------------------------|
| X          | float   | meters         | Easting in project CRS             |
| Y          | float   | meters         | Northing in project CRS            |
| Z          | float   | meters         | Elevation (positive up typically)   |
| formation  | string  | —              | Name of geological surface/unit    |

### Orientations Required Columns (Gradient Format)

| Column | Type  | Range      | Notes                                |
|--------|-------|------------|--------------------------------------|
| X      | float | meters     | Location of measurement              |
| Y      | float | meters     | Location of measurement              |
| Z      | float | meters     | Location of measurement              |
| G_x    | float | -1 to 1   | Gradient X component (unit vector)   |
| G_y    | float | -1 to 1   | Gradient Y component (unit vector)   |
| G_z    | float | -1 to 1   | Gradient Z component (unit vector)   |

### Orientations Alternative (Azimuth/Dip Format)

| Column    | Type  | Range    | Notes                               |
|-----------|-------|----------|-------------------------------------|
| azimuth   | float | 0–360    | Degrees clockwise from North        |
| dip       | float | 0–90     | Degrees from horizontal             |
| polarity  | int   | +1 / -1  | Normal direction indicator          |

## Outputs

| Output             | Format | Location                      |
|--------------------|--------|-------------------------------|
| surface_points.csv | CSV    | gempy_input/surface_points.csv|
| orientations.csv   | CSV    | gempy_input/orientations.csv  |

## Procedure

1. **Identify source data format** — determine column names, coordinate units,
   orientation convention (azimuth/dip vs. gradient vectors).

2. **Run the converter tool**:
   ```bash
   python ki/tools/convert_geological_data.py \
       --surface-points raw_points.csv \
       --orientations raw_orientations.csv \
       --coord-unit meters \
       --orientation-format azimuth_dip \
       --output-dir gempy_input/
   ```

3. **Remap columns** if source uses non-standard names:
   ```bash
   python ki/tools/convert_geological_data.py \
       --surface-points boreholes.csv \
       --col-x Easting --col-y Northing --col-z Depth \
       --col-formation Layer \
       --output-dir gempy_input/
   ```

4. **Review output JSON** — check `n_surface_points`, `formations` list,
   coordinate extent, and any warnings.

## Verification

- [ ] Output CSV has correct headers: X, Y, Z, formation (surface points)
- [ ] Output CSV has correct headers: X, Y, Z, G_x, G_y, G_z (orientations)
- [ ] All coordinates in meters (not km, not feet)
- [ ] Gradient vectors are unit vectors (|G| = 1 +/- 0.01)
- [ ] Each formation in surface points matches the structural config
- [ ] No NaN or empty values in coordinate columns
- [ ] Z values make geological sense (formations at expected depths)

## Traps

| Trap    | Description                                          | Severity |
|---------|------------------------------------------------------|----------|
| dt_001  | Coordinates in km not meters — model 1000x too small | silent   |
| dt_002  | Azimuth in radians not degrees — wrong orientations  | silent   |
| dt_003  | Dip from vertical not horizontal — inverted surfaces | silent   |
| dt_004  | Polarity sign flipped — reversed layer order         | silent   |
| dt_006  | Gradient not unit vector — interpolation bias        | degraded |
| dt_009  | Mixed CRS (WGS84 + UTM) — distorted geometry        | silent   |

## Example

Convert borehole data from a geological survey with coordinates in kilometers
and orientations as azimuth/dip:

```bash
python ki/tools/convert_geological_data.py \
    --surface-points survey_contacts.csv \
    --orientations survey_orientations.csv \
    --coord-unit km \
    --orientation-format azimuth_dip \
    --col-x East_km --col-y North_km --col-z Elev_km \
    --col-formation Unit \
    --output-dir gempy_input/
```

Expected output:
```json
{
  "status": "success",
  "n_surface_points": 45,
  "formations": ["Basement", "Sandstone", "Shale", "Siltstone"],
  "sp_extent": {
    "x": [500.0, 2500.0],
    "y": [1000.0, 3000.0],
    "z": [-800.0, 50.0]
  }
}
```
