# S1: Domain Setup

## Purpose

Define the computational domain for a TELEMAC simulation, including geographic
extent, coordinate reference system, and the relationship between the physical
domain and the numerical mesh. This stage establishes the spatial framework
that all subsequent stages depend on.

## Inputs

| Input               | Format     | Description                                 |
|---------------------|------------|---------------------------------------------|
| Study area boundary | Shapefile / KML / manual coordinates | Geographic extent     |
| Coordinate system   | EPSG code  | Target CRS (must be metric: UTM, Lambert)   |
| Bathymetry source   | XYZ / GeoTIFF / nautical chart | Depth or elevation data |
| Resolution targets  | Numeric    | Desired element size (m) in key zones       |

## Outputs

| Output              | Format     | Description                                 |
|---------------------|------------|---------------------------------------------|
| Domain boundary     | Polygon    | Closed polygon defining computation limits  |
| Resolution map      | Text       | Spatial distribution of target element sizes|
| CRS definition      | EPSG code  | Confirmed metric coordinate system          |

## Procedure

1. **Select geographic extent**: Define the study area covering all regions of
   interest plus a buffer zone for boundary conditions.

2. **Choose coordinate system**: TELEMAC requires metric coordinates. Select an
   appropriate projected CRS:
   - Rivers / small domains: UTM zone matching the study area
   - Large coastal domains: Lambert Conformal Conic or similar
   - NEVER use WGS84 (EPSG:4326) geographic coordinates directly

3. **Define resolution requirements**:
   - Channels / narrow passages: element size = channel width / 5-10
   - Open water: coarser elements (100-1000 m)
   - Near structures: fine resolution (1-10 m)
   - Transition ratio between zones: max 1:3 growth rate

4. **Identify boundary types**:
   - Open sea boundaries: tidal elevation or radiation conditions
   - River inflows: prescribed discharge
   - Solid walls: no-slip or slip conditions
   - Internal boundaries: coupling interfaces

## Verification

- [ ] All coordinates are in metric units (not degrees)
- [ ] Domain extends beyond the area of interest to avoid boundary effects
- [ ] Resolution transitions are gradual (no abrupt size changes)
- [ ] Boundary types are identified for all open edges

## Traps

- **dt_006**: Using WGS84 degree coordinates produces a ~1m domain with
  catastrophic CFL violations. Always project to metric CRS first.
- **dt_007**: Confusing depth (positive downward) with elevation (positive
  upward) inverts the entire bathymetry.

## Example

```bash
# Convert shapefile boundary from WGS84 to UTM Zone 30N
ogr2ogr -t_srs EPSG:32630 domain_utm.shp domain_wgs84.shp

# Verify coordinates are in meters
ogrinfo domain_utm.shp -al | grep EXTENT
# Expected: EXTENT: (300000, 5400000) - (400000, 5500000)
# NOT:      EXTENT: (-2.5, 48.5) - (-1.5, 49.5)
```
