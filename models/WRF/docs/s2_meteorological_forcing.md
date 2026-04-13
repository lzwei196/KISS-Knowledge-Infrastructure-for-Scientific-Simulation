# Stage 2: Meteorological Forcing (ungrib + metgrid)

## Purpose
Extract meteorological fields from global reanalysis or forecast GRIB files and horizontally interpolate them onto the WRF grid. This two-step process (ungrib then metgrid) produces the `met_em.d0N.*.nc` files consumed by real.exe.

## Inputs
| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| GRIB files | GRIB1 or GRIB2 | GFS/ERA5/FNL | Global meteorological analysis/forecast |
| `Vtable` | Text | WPS/ungrib/ | Variable table mapping GRIB codes to WPS names |
| `namelist.wps` | Fortran namelist | Stage 0 | Time/domain configuration |
| `geo_em.d0N.nc` | NetCDF | Stage 1 | Target grid definition |

### Common Data Sources
| Source | Resolution | Frequency | Vtable | Notes |
|--------|-----------|-----------|--------|-------|
| GFS | 0.25 deg | 6h (3h avail) | Vtable.GFS | Free, near-real-time |
| ERA5 | 0.25 deg | 1h | Vtable.ERA-interim.pl | Best for research; CDS API |
| NCEP FNL | 1.0 deg | 6h | Vtable.GFS | Common for case studies |
| NARR | 32 km | 3h | Vtable.NARR | North America only |

## Outputs
| Output | Format | Description |
|--------|--------|-------------|
| `FILE:YYYY-MM-DD_HH` | WPS intermediate | Ungribbed fields (one per time) |
| `met_em.d01.YYYY-MM-DD_HH:MM:SS.nc` | NetCDF | Horizontally interpolated met fields |
| `met_em.d02.YYYY-MM-DD_HH:MM:SS.nc` | NetCDF | Nested domain met fields |

### Key Variables in met_em
| Variable | Description | Units | Notes |
|----------|-------------|-------|-------|
| `TT` | Temperature | K | On pressure levels |
| `UU` | U-wind | m s-1 | Earth-relative |
| `VV` | V-wind | m s-1 | Earth-relative |
| `GHT` | Geopotential height | m | On pressure levels |
| `RH` | Relative humidity | % | |
| `PMSL` | Mean sea-level pressure | Pa | |
| `PSFC` | Surface pressure | Pa | |
| `SKINTEMP` | Skin temperature | K | |
| `SST` | Sea surface temperature | K | |
| `LANDSEA` | Land/sea flag | 0/1 | |
| `SM000010` | Soil moisture 0-10 cm | m3 m-3 | Volumetric |
| `ST000010` | Soil temperature 0-10 cm | K | |

## Procedure

### 1. Link GRIB files and Vtable
```bash
cd /path/to/WPS/
./link_grib.csh /path/to/grib_data/gfs.*
ln -sf ungrib/Variable_Tables/Vtable.GFS Vtable
```

### 2. Run ungrib
```bash
./ungrib.exe >& ungrib.log
# Produces FILE:YYYY-MM-DD_HH files
ls FILE:* | head -5
```

### 3. Run metgrid
```bash
./metgrid.exe >& metgrid.log
# Produces met_em.d0N.YYYY-MM-DD_HH:MM:SS.nc files
ls met_em.d01.* | wc -l
```

### 4. Verify temporal coverage
```bash
# Count met_em files -- should match expected hourly/6-hourly count
nfiles=$(ls met_em.d01.* | wc -l)
echo "met_em files: $nfiles"
# For 3-day simulation with 6h data: expect 13 files (day0_00h through day3_00h)
```

## Verification
- [ ] Number of met_em files matches expected time steps
- [ ] Temperature values are physically plausible (200-320 K)
- [ ] Pressure values are plausible (500-1050 hPa at surface)
- [ ] No NaN or extreme values in key fields
- [ ] SST present over ocean points

## Traps
| Trap | Severity | Description |
|------|----------|-------------|
| Wrong Vtable | CRITICAL | Using GFS Vtable for ERA5 data (or vice versa) silently maps wrong fields |
| Pressure units | CRITICAL | ERA5 geopotential is in m2/s2, must be divided by 9.81 for height |
| Missing soil fields | HIGH | If soil moisture/temperature not in GRIB, real.exe uses defaults (wrong) |
| Time gap | HIGH | Missing time step in GRIB data causes metgrid to skip; real.exe then crashes |
| GRIB edition mismatch | MEDIUM | Vtable must match GRIB1 vs GRIB2 edition |
| SST not extracted | MEDIUM | If SST missing from GRIB, WRF uses SKINTEMP over water (inaccurate) |

## Example
Verify met_em content:
```python
import netCDF4 as nc
ds = nc.Dataset("met_em.d01.2020-06-15_00:00:00.nc")
tt = ds.variables["TT"][0,:,50,50]  # Temperature profile at a point
print(f"T profile (K): {tt}")        # Should be ~290K at sfc, ~210K at tropopause
psfc = ds.variables["PSFC"][0,50,50]
print(f"Sfc pressure: {psfc:.0f} Pa ({psfc/100:.0f} hPa)")  # ~101325 Pa
ds.close()
```
