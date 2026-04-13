# Stage 2: Hypsometry Construction

## Purpose

Build the elevation-area hypsometric curve required by HydroTrend
(`{PREFIX}0.HYPS`). The hypsometry defines the basin's elevation distribution,
which controls snow/ice accumulation zones, lapse-rate temperature corrections,
and sediment transport calculations.

## Inputs

| Source | Format | Resolution |
|--------|--------|------------|
| SRTM DEM | GeoTIFF | 30m / 90m |
| ASTER GDEM | GeoTIFF | 30m |
| HydroSHEDS | GeoTIFF | 3–30 arc-seconds |
| Manual data | CSV | — |

Additional requirement: Basin boundary (shapefile or polygon) for clipping DEM.

## Outputs

`{PREFIX}0.HYPS` file:
```
-------------------------------------------------
HYDROTREND hypsometry input file.
First line: number of hypsometric bins
Other lines: altitude (m) and area (km^2) data
-------------------------------------------------
46
1       0
51      43.73
101     143.35
...
2251    9440.46
```

## Procedure

1. **Obtain DEM**: Download SRTM or equivalent DEM covering the basin
2. **Clip to basin**: Use basin boundary to clip DEM to watershed extent
3. **Compute hypsometry**:
   - Define elevation bins (typically 50m intervals)
   - For each bin, count pixels at or below that elevation
   - Convert pixel count to area: `area_km2 = n_pixels × pixel_area_km2`
4. **Format output**:
   - First bin: lowest elevation, area = 0 (no area below basin outlet)
   - Subsequent bins: cumulative area below each elevation
   - Last bin: highest elevation, total basin area
5. **Write HYPS file** using `build_hypsometry.py`

## Verification

- [ ] Elevations are in **meters** (not feet, not km)
- [ ] Areas are in **km²** (not m², not hectares)
- [ ] First bin area is 0 (basin bottom/outlet)
- [ ] Both elevation and area columns are monotonically increasing
- [ ] Total area (last bin) matches known basin area
- [ ] Relief (max_elev − min_elev) is physically reasonable
- [ ] Number of bins typically 20–100 (too few = coarse; too many = slow)

## Traps

### CRITICAL: Area units (km² vs m²)
HydroTrend uses area in km² directly in the sediment formulas (BQART, ART).
If you provide m², the area will be 10⁶ times too large, causing astronomically
high sediment loads.

**Detection**: Qs values many orders of magnitude above published values.
**Formula effect**: In BQART, Qsbar ∝ A^0.5, so m² → km² error gives ~1000× Qs.

### CRITICAL: Monotonicity
Both elevation and area must be strictly increasing. Non-monotonic data
(e.g., from poorly processed DEMs) causes the model to miscompute basin
relief and area-weighted temperature.

### Hypsometry bin count
The number of bins affects temperature interpolation accuracy. Too few bins
(< 5) cause poor lapse-rate corrections. Too many bins (> 200) slow
computation without improving accuracy.

### Coordinate system
If DEM is in geographic coordinates (degrees), pixel area varies with
latitude. Use proper area calculation: `area = pixel_width_deg × cos(lat) ×
111.32 km × pixel_height_deg × 110.574 km`.

### Missing nodata handling
DEMs often have nodata values (e.g., -9999) for ocean or void-fill areas.
Always mask nodata before computing hypsometry, or false low-elevation bins
will appear.

## Example

```bash
# From DEM
python build_hypsometry.py \
    --dem basin_dem.tif \
    --output HYDRO0.HYPS \
    --bin-size 50

# Manual synthetic curve
python build_hypsometry.py \
    --manual \
    --min-elev 1 --max-elev 2251 \
    --total-area 9440 \
    --n-bins 46 \
    --output HYDRO0.HYPS
```
