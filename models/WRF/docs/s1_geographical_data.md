# Stage 1: Geographical Data (geogrid)

## Purpose
Interpolate static terrestrial datasets (terrain elevation, land use, soil type, vegetation fraction, albedo, etc.) onto the WRF model grid. Produces `geo_em.d0N.nc` files used by metgrid and real.exe.

## Inputs
| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| `namelist.wps` | Fortran namelist | Stage 0 | Domain configuration |
| WPS_GEOG | Binary tiles | NCAR download | Static geographical data at multiple resolutions |

### WPS_GEOG Data Categories
| Dataset | Resolution Options | Description |
|---------|-------------------|-------------|
| `topo_30s` | 30s, 2m, 5m, 10m | USGS GMTED2010 terrain elevation |
| `landuse_30s` | 30s, 2m, 5m, 10m | MODIS 21-cat or USGS 24-cat land use |
| `soiltype_top_30s` | 30s, 2m, 5m | STATSGO/FAO 16-cat USDA soil type |
| `soiltype_bot_30s` | 30s, 2m, 5m | Bottom-layer soil type |
| `albedo_ncep` | varies | Monthly surface albedo |
| `greenfrac` | varies | Monthly green vegetation fraction |
| `maxsnowalb` | varies | Maximum snow albedo |
| `lai_modis_30s` | 30s | Leaf area index |

## Outputs
| Output | Format | Description |
|--------|--------|-------------|
| `geo_em.d01.nc` | NetCDF | Domain 1 static fields |
| `geo_em.d02.nc` | NetCDF | Domain 2 static fields (if nesting) |

### Key Variables in geo_em
| Variable | Description | Units |
|----------|-------------|-------|
| `HGT_M` | Terrain height | m |
| `LU_INDEX` | Dominant land-use category | integer |
| `SCT_DOM` | Dominant soil category (top) | integer |
| `SCB_DOM` | Dominant soil category (bottom) | integer |
| `GREENFRAC` | Monthly green fraction | fraction (0-1) |
| `ALBEDO12M` | Monthly albedo | fraction |
| `SNOALB` | Max snow albedo | fraction |
| `XLAT_M` | Latitude | degrees_north |
| `XLONG_M` | Longitude | degrees_east |
| `MAPFAC_M` | Map scale factor | dimensionless |

## Procedure

### 1. Download WPS_GEOG
```bash
# Mandatory minimum (~3 GB)
wget https://www2.mmm.ucar.edu/wrf/src/wps_files/geog_minimum.tar.bz2
tar xjf geog_minimum.tar.bz2

# Full resolution (~50 GB)
wget https://www2.mmm.ucar.edu/wrf/src/wps_files/geog_complete.tar.bz2
```

### 2. Configure geog_data_path in namelist.wps
```
&geogrid
 geog_data_path = '/path/to/WPS_GEOG/',
 geog_data_res  = 'default', 'default',
/
```

### 3. Run geogrid
```bash
cd /path/to/WPS/
./geogrid.exe >& geogrid.log
```

### 4. Verify output
```bash
ncdump -h geo_em.d01.nc | grep -E "HGT_M|LU_INDEX|SCT_DOM"
# Check terrain range
ncks -v HGT_M geo_em.d01.nc | ncdump -v HGT_M | tail -5
```

## Verification
- [ ] `geo_em.d0N.nc` exists for each domain
- [ ] Terrain elevation range is physically plausible
- [ ] Land-use categories match expected land cover
- [ ] No fill/missing values over land areas
- [ ] Coastlines appear reasonable (check LANDMASK)

## Traps
| Trap | Severity | Description |
|------|----------|-------------|
| Missing geog_data_path | CRITICAL | geogrid silently uses low-resolution defaults if path wrong |
| Wrong land-use table | HIGH | MODIS (21-cat) vs USGS (24-cat) mismatch breaks surface physics |
| Urban category missing | MEDIUM | Noah/Noah-MP need urban fraction; missing = wrong surface fluxes |
| Soil type over water = 14 | MEDIUM | Category 14 must map to water; wrong mapping corrupts soil |

## Example
Verify geo_em output after geogrid:
```python
import netCDF4 as nc
ds = nc.Dataset("geo_em.d01.nc")
hgt = ds.variables["HGT_M"][0,:,:]
print(f"Terrain: min={hgt.min():.1f} m, max={hgt.max():.1f} m")
lu = ds.variables["LU_INDEX"][0,:,:]
print(f"Land-use categories present: {sorted(set(lu.flatten()))}")
ds.close()
```
