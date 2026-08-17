# Stage 2: Topographic Wetness Index (TWI) Generation

## Purpose

Generate the `subcat.dat` file containing the TWI (ln(a/tanB)) distribution
and channel routing information required by TOPMODEL. The TWI distribution
is the core spatial characterization that allows TOPMODEL to represent the
variable contributing area concept.

## Inputs

| Input | Description |
|-------|-------------|
| DEM | Raster elevation data (GeoTIFF), ≤90m resolution recommended |
| Basin shapefile | Polygon boundary to clip DEM |
| Basin area (km²) | From Stage 0, for verification |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| subcat.dat | TOPMODEL text | TWI histogram + channel info |

## Procedure

1. **Prepare DEM**:
   - Clip DEM to basin boundary with buffer
   - Fill sinks/depressions (hydrological conditioning)
   - Resolution: 50m or better recommended (Beven, 1995)
   - For China: use `KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif`

2. **Compute flow routing**:
   - Flow direction: D8 algorithm (or D-infinity for better accuracy)
   - Flow accumulation: count upslope contributing cells
   - Specific catchment area: a = flow_acc × cell_area / contour_length

3. **Compute slope**:
   - Use 3×3 window (Horn or Zevenbergen-Thorne method)
   - Minimum slope = 0.001 (avoid log(0) in TWI)

4. **Compute TWI**:
   ```
   TWI = ln(a / tan(slope))
   ```
   - Typical range: 2–15
   - High TWI = valley bottoms, likely to saturate
   - Low TWI = ridgetops, rarely saturate

5. **Create histogram**:
   - Bin TWI values into 10–30 classes
   - Compute area fraction for each class
   - Sort from HIGH TWI to LOW TWI (TOPMODEL convention!)
   - First entry (highest TWI) should have near-zero area fraction

6. **Channel network**:
   - Extract main channel from flow accumulation
   - Compute distance from each channel segment to outlet
   - Typical: 3 segments (outlet, midpoint, headwater)
   - Cumulative area distribution: 0.0, 0.5, 1.0
   - Distances in METERS (not km!)

7. **Write subcat.dat**:
   ```
   1  1  0
   Basin Name
   30  1
   {area_frac}  {twi_value}  × 30 rows
   3
   0.0  {d1}  0.5  {d2}  1.0  {d3}
   $mapfile.dat
   ```

## Verification

- [ ] TWI values ordered high to low
- [ ] Area fractions sum to ~1.0
- [ ] TWI range is 2–15 (typical for moderate terrain)
- [ ] First area fraction is near zero
- [ ] Channel distances are in meters
- [ ] Channel distances increase monotonically
- [ ] Number of TWI classes is 10–30

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| TWI not ordered high→low | Saturated area calc wrong | Sort descending |
| Area fractions don't sum to 1 | Water balance error | Normalize |
| Flat DEM (slope~0) | TWI→infinity | Set minimum slope=0.001 |
| Channel distance in km | Wrong routing delay | Multiply by 1000 |
| Unfilled DEM sinks | Missing flow paths | Fill DEM before TWI calc |
| Too few TWI classes (<10) | Poor representation | Use 20–30 classes |

## Example

```bash
python tools/generate_twi_subcat.py \
  --dem KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif \
  --shapefile KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
  --basin-name "Bengbu Basin" --basin-area-km2 121330 \
  --n-classes 30 --n-channels 3 --output data/subcat.dat
```
