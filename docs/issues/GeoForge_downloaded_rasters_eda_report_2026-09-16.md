# GeoForge downloaded rasters — content and grid inspection

Generated: 2026-09-16, Asia/Shanghai. Read-only analysis using rasterio 1.5.0,
NumPy 2.4.2 and pyproj, following the exploratory-data-analysis workflow.

## Summary

**8246 bytes is plausible for these three small static rasters. It is not a
complete simulation dataset, and not a weather time series.** The requested box
is approximately one 0.1-degree CMFD weather-grid cell in area, but contains many
higher-resolution DEM and soil pixels. No CMFD or crop-calendar files have been
accepted locally in this test.

File integrity, readability, nonempty values and approximate geographic placement
are confirmed. Source-pixel equality has not been verified. In particular, the
two delivered HWSD projections disagree sufficiently that they must not be
declared interchangeable or scientifically validated.

## Files and format

Project root:
`/Users/leo/kiss/projects/describe-ui-20260915/2026-09-15-This-is-a-real-GeoForge-Database-data-acquisitio--5c4bfebf34bc`

Paths below are relative to that root:

- `inputs/geoforge_subsets/8a9b630af37142f08dd7a8ea3797beaa/china_dem_90m__crop.tif`
- `inputs/geoforge_subsets/4b8c7373325a4856b741f4c451708b16/hwsd_china__HWSD_China_Geo.tif`
- `inputs/geoforge_subsets/4b8c7373325a4856b741f4c451708b16/hwsd_china__HWSD_China_Albers.tif`

These are single-band GeoTIFFs: TIFF image arrays plus CRS and spatial-transform
metadata. They were inspected with a geospatial reader, not inferred from the
filename or preview. The rasters are static and contain no time dimension.

| File | Rows × columns | Cells | Type | Raw value bytes | Compression | TIFF bytes |
| --- | --- | ---: | --- | ---: | --- | ---: |
| DEM | 124 × 124 | 15376 | int16 | 30752 | LZW | 6636 |
| HWSD geographic | 12 × 12 | 144 | uint16 | 288 | None | 734 |
| HWSD Albers | 12 × 10 | 120 | uint16 | 240 | None | 876 |

The DEM compresses well because these local integer values span a narrow range.
The soil rasters need only two bytes per cell; their TIFF metadata are larger
than the raw arrays. The earlier description of all three files as compressed
was too broad: **only the DEM is compressed**.

## Geographic scope and resolution

Approved bbox: `[115.0,37.0,115.1,37.1]` (longitude, latitude).
Using WGS84 geodesic calculations, this is about **8.895 km east–west by
11.098 km north–south**, or **98.719 km²**. It is a small test patch, not the whole
North China Plain, a delineated catchment, or a complete model domain.

| Raster | Native resolution | WGS84 extent (west, south, east, north) |
| --- | --- | --- |
| DEM | 0.000808483756°; about 71.9 m east–west × 89.7 m north–south here | 114.999537896, 37.000259080, 115.099789881, 37.100511066 |
| HWSD geographic | 0.008333333333° (30 arcsec); about 741 m × 925 m here | 114.999999996, 37.000000003, 115.099999996, 37.100000003 |
| HWSD Albers | 1000 m × 1000 m | transformed envelope 114.978151593, 37.001572290, 115.105968724, 37.116113954 |

DEM edges differ from the requested decimal bbox by less than one native pixel;
this is a grid-aligned crop, not an exact polygon clip. Its east/south outer edges
do not fully enclose the exact requested rectangle. The geographic soil extent
matches the request to floating-point tolerance. The Albers raster has a rotated
geographic footprint and a different native grid; its WGS84 envelope is not proof
of exact coverage of every requested boundary point. Centre sampling confirmed
that the study location is inside all three rasters.

## Integrity and values

- All three actual file sizes and independently computed SHA-256 hashes match
  their recorded manifests.
- All three files open normally; actual bounds agree with their manifest bounds
  to 1e-5 in native units.
- DEM has 15376 finite unmasked cells, values 26–40, mean 33.494 and standard
  deviation 1.382. Its nodata marker is 32767 and none of these cells has that
  marker. Fifteen distinct integer values are present; it is not a constant or
  blank tile. At 115.05°E, 37.05°N the value is 33.
- The catalogue names the DEM variable `elevation_m`, but the delivered TIFF's
  band-unit and description tags are empty. The numbers are not independently
  ground-truthed elevations; a catalogue label does not establish source parity.
- HWSD geographic has 144 finite unmasked cells and 7 IDs:
  11476 (28 cells), 11477 (8), 11481 (1), 11509 (57), 11510 (2), 11520 (1),
  11525 (47).
- HWSD Albers has 120 finite unmasked cells and 36 distinct IDs in the range
  11476–11525. Both HWSD files have `nodata=None` and no band units. Absence of a
  nodata marker is not independently a completeness guarantee.
- HWSD values are categorical mapping-unit identifiers, not physical soil
  properties. Averaging these IDs has no scientific meaning. A soil-property
  lookup table and model-specific preparation remain necessary.

## Independent cross-projection HWSD check

A second read-only check transformed coordinates using each file's actual CRS
and compared containing/nearest cells at common valid cell centres within the
requested study box:

| Sampling direction | Matching IDs |
| --- | ---: |
| Geographic cell centres → Albers | 56/133 (42.1%) |
| Albers cell centres → geographic | 45/93 (48.4%) |

At the same geographic point, **115.05°E, 37.05°N**, the geographic raster gives
**11509**, whereas Albers gives **11497**. In the overlap, 36/93 Albers samples
carry 26 IDs absent from the entire delivered geographic crop.

Different source grids and boundary locations can create some disagreement.
These comparisons **do not prove bilinear resampling or identify where the
discrepancy was introduced**. They do establish that this download test has not
validated the two members as equivalent categorical products.

## What is and is not verified

| Check | Result |
| --- | --- |
| Delivery byte integrity | Passed for all three files |
| Openable native rasters | Passed with the independent local reader |
| Nonempty, nonconstant, finite values | Confirmed in these crops |
| Approximate requested location | Confirmed; native-grid edge caveats above |
| Compiled app raster-content reader | Missing; app correctly reports pending |
| Exact equality to authoritative server source pixels | Not tested |
| HWSD projections interchangeable | Not established; observed disagreement |
| Ready for scientific model input | Not established |

## Follow-up recommendations

1. Backend should compare each delivered crop against the corresponding source
   window, including transform, CRS, nodata mask and pixel values; report the
   source version and exact window. No generic checksum proves scientific parity.
2. Audit the provenance/resampling of the two HWSD source projections and use
   the authoritative categorical product for the intended model. Do not infer
   correctness from the `nearest` label on this crop operation alone.
3. Bundle the raster reader in the desktop build so raster structure checks do
   not require a separate local Python installation.
4. Keep the current scientific-validation status pending. Resolve the separate
   CMFD date-slicing defect and crop-calendar delivery failures before claiming
   an end-to-end model-ready dataset.

Related acquisition results:
[Compiled-app download test](GEOFORGE-DOWNLOAD-GUI-TEST-2026-09-16.md).
