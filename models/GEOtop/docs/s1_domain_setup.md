# s1: Domain / Grid Setup

## Purpose

Prepare the topographic input files that define the spatial domain for a GEOtop simulation.
For **point simulations** (PointSim=1), a minimal DEM and parameter set in `geotop.inpts`
suffices. For **distributed simulations** (PointSim=0), a full set of raster maps is required.

## Inputs

| Input               | Source                  | Format           | Units               |
|---------------------|-------------------------|------------------|---------------------|
| DEM raster          | SRTM, MERIT, local LiDAR | ESRI ASCII Grid | meters (elevation)  |
| Basin boundary      | Shapefile or GeoJSON    | Vector           | Geographic/projected|
| Resolution          | User decision           | Scalar           | meters              |

## Outputs

| Output              | File                    | Format           | Notes               |
|---------------------|-------------------------|------------------|---------------------|
| dem.txt             | sim_dir/dem.txt         | ESRI ASCII Grid  | Clipped DEM         |
| slope.txt           | sim_dir/slope.txt       | ESRI ASCII Grid  | Degrees (0-90)      |
| aspect.txt          | sim_dir/aspect.txt      | ESRI ASCII Grid  | Degrees from N (0-360)|
| sky.txt             | sim_dir/sky.txt         | ESRI ASCII Grid  | Sky view factor (0-1)|
| curvature.txt       | sim_dir/curvature.txt   | ESRI ASCII Grid  | Plan/profile curvature|
| horizonXXXX.txt     | sim_dir/horizonXXXX.txt | CSV              | Horizon angles      |

## Procedure

### Point Simulation (Recommended for initial testing)

1. Set `PointSim = 1` in `geotop.inpts`
2. Specify point coordinates and topography directly:
   ```
   CoordinatePointX    = 620815
   CoordinatePointY    = 5171506
   PointElevation      = 1480
   PointSlope          = 15
   PointAspect         = 225
   PointSkyViewFactor  = 0.95
   ```
3. No DEM or map files needed for point mode
4. Generate horizon file if `FlagSkyViewFactor = 1` is set

### Distributed Simulation

1. **Obtain DEM**: Download SRTM 90m or MERIT 90m DEM covering the basin
2. **Clip to basin**: Use GDAL to clip DEM to basin boundary with buffer
   ```bash
   gdalwarp -cutline basin.shp -crop_to_cutline -tr 90 90 srtm.tif dem_clipped.tif
   ```
3. **Convert to ESRI ASCII**:
   ```bash
   gdal_translate -of AAIGrid dem_clipped.tif dem.txt
   ```
4. **Derive slope and aspect**:
   ```bash
   gdaldem slope dem_clipped.tif slope.tif -of GTiff
   gdaldem aspect dem_clipped.tif aspect.tif -of GTiff -zero_for_flat
   gdal_translate -of AAIGrid slope.tif slope.txt
   gdal_translate -of AAIGrid aspect.tif aspect.txt
   ```
5. **Compute sky view factor**: Use GEOtop's built-in computation or external tools
6. **Generate horizon files**: One per meteorological station, containing azimuth vs horizon angle

## Verification

- [ ] DEM has no nodata cells inside the basin boundary
- [ ] Slope values are in degrees (0-90), not percent
- [ ] Aspect values are degrees from north clockwise (0-360), not radians
- [ ] Sky view factor is 0-1 range (flat terrain ~ 1.0, deep valleys < 0.5)
- [ ] All maps have identical ncols, nrows, cellsize, xllcorner, yllcorner
- [ ] NODATA_value is consistent across all maps (typically -9999)
- [ ] Horizon file azimuths cover 0-360 degrees

## Traps

| Trap ID | Description                                                  |
|---------|--------------------------------------------------------------|
| dt_011  | Slope in percent instead of degrees (90% slope != 90 degrees)|
| dt_012  | Aspect in radians instead of degrees                         |
| dt_013  | Map grid mismatch (different resolution or origin)           |

## Example

Matsch Valley Station B2 point simulation:
```
PointSim            = 1
CoordinatePointX    = 620815
CoordinatePointY    = 5171506
PointElevation      = 1480
PointSlope          = 15
PointAspect         = 225
```
This represents a south-west facing 15-degree slope at 1480 m elevation in the Alps.
