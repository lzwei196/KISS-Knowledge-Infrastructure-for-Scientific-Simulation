# Stage 1: Landscape Data Preparation

## Purpose

Prepare terrain, fuel model, and canopy structure GeoTIFFs from raw data sources (LANDFIRE, SRTM, LiDAR) in the exact format, units, and coordinate system that ELMFIRE expects. This is the most error-prone stage because unit and CRS mismatches produce silent failures.

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| Digital Elevation Model | SRTM, ASTER, NED, LiDAR | GeoTIFF | meters above sea level |
| Fuel Model (FBFM40) | LANDFIRE | GeoTIFF Int16 | Code (0–303) |
| Canopy Cover | LANDFIRE | GeoTIFF | percent (0–100) |
| Canopy Height | LANDFIRE | GeoTIFF | meters |
| Canopy Base Height | LANDFIRE | GeoTIFF | meters |
| Canopy Bulk Density | LANDFIRE | GeoTIFF | kg/m³ |

## Outputs

All outputs are GeoTIFFs in the target UTM projection, at the specified cell size:

| Output file | Variable | Type | Units | NODATA |
|-------------|----------|------|-------|--------|
| `dem.tif` | Elevation | Float32 | meters | -9999 |
| `slp.tif` | Slope | Float32 | degrees (0–90) | -9999 |
| `asp.tif` | Aspect | Float32 | degrees (0=N, 90=E) | -9999 |
| `fbfm40.tif` | Fuel model code | Int16 | FBFM40 code | -9999 |
| `cc.tif` | Canopy cover | Int16 | percent (0–100) | -9999 |
| `ch.tif` | Canopy height | Int16 | meters × 10 | -9999 |
| `cbh.tif` | Canopy base height | Int16 | meters × 10 | -9999 |
| `cbd.tif` | Canopy bulk density | Int16 | kg/m³ × 100 | -9999 |
| `adj.tif` | Spread rate adjustment | Float32 | dimensionless (1.0) | -9999 |
| `phi.tif` | Initial level set | Float32 | dimensionless (1.0) | -9999 |

## Procedure

### Step 1: Determine UTM zone

```python
import math
utm_zone = int((lon + 180) / 6) + 1
epsg = 32600 + utm_zone  # Northern hemisphere
# Southern hemisphere: epsg = 32700 + utm_zone
```

### Step 2: Reproject DEM to UTM

```bash
gdalwarp -t_srs EPSG:32610 -tr 30 30 -dstnodata -9999 \
    -ot Float32 -r bilinear raw_dem.tif inputs/dem.tif
```

### Step 3: Derive slope and aspect

```bash
gdaldem slope dem.tif slp.tif -compute_edges  # degrees
gdaldem aspect dem.tif asp.tif -compute_edges -zero_for_flat  # degrees, 0=N
```

### Step 4: Reproject and convert fuel model

```bash
gdalwarp -t_srs EPSG:32610 -tr 30 30 -dstnodata -9999 \
    -ot Int16 -r nearest landfire_fbfm40.tif inputs/fbfm40.tif
```

### Step 5: Process canopy rasters with integer multipliers

```bash
# Canopy cover — already in percent, just reproject
gdalwarp -t_srs EPSG:32610 -tr 30 30 -ot Int16 cc_raw.tif inputs/cc.tif

# Canopy height — multiply by 10 for integer storage
gdal_calc.py -A ch_raw.tif --outfile=inputs/ch.tif --calc="A*10" --type=Int16

# Canopy base height — multiply by 10
gdal_calc.py -A cbh_raw.tif --outfile=inputs/cbh.tif --calc="A*10" --type=Int16

# Canopy bulk density — multiply by 100
gdal_calc.py -A cbd_raw.tif --outfile=inputs/cbd.tif --calc="A*100" --type=Int16
```

### Step 6: Create default adjustment and phi rasters

```bash
gdal_calc.py -A dem.tif --outfile=adj.tif --calc="A*0+1.0" --type=Float32
gdal_calc.py -A dem.tif --outfile=phi.tif --calc="A*0+1.0" --type=Float32
```

### Step 7: Run tool

```bash
python convert_landscape_to_elmfire.py \
    --dem /data/srtm/dem.tif \
    --fuel /data/landfire/fbfm40.tif \
    --cc /data/landfire/cc.tif \
    --ch /data/landfire/ch.tif \
    --cbh /data/landfire/cbh.tif \
    --cbd /data/landfire/cbd.tif \
    --cellsize 30 --epsg 32610 \
    --out ./inputs
```

## Verification

1. **CRS check**: `gdalinfo dem.tif | grep "EPSG"` — must show target UTM zone
2. **Resolution check**: All rasters must show identical pixel size (e.g., 30×30 m)
3. **Extent check**: All rasters must cover the computational domain
4. **Slope range**: `gdalinfo -stats slp.tif` — max should be 0–60° for typical terrain
5. **Fuel codes**: Verify FBFM40 codes exist in `fuel_models.csv`
6. **Canopy multipliers**: CH max ≈ 300–500 (representing 30–50 m), CBH max ≈ 100–300, CBD max ≈ 10–30

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Slope in percent rise | Extreme spread rates | `degrees = atan(pct/100) × 180/π` |
| CRS mismatch | Tiny/huge domain | Reproject all to same UTM |
| CBD not ×100 | No crown fire | Multiply by 100 or set CBD_TIMES_100=.FALSE. |
| CBH not ×10 | Wrong crown fire threshold | Multiply by 10 or set CBH_TIMES_10=.FALSE. |
| NODATA gaps | Fire stops at tile edges | `gdal_fillnodata.py` or merge tiles |
| Aspect in math convention | Wrong solar exposure | Use GDAL (already geographic convention) |

## Example

Preparing landscape for a fire near Lake Tahoe, California:

```bash
python convert_landscape_to_elmfire.py \
    --dem /data/ned/n39w120.tif \
    --fuel /data/landfire/US_200FBFM40.tif \
    --cc /data/landfire/US_200CC.tif \
    --ch /data/landfire/US_200CH.tif \
    --cbh /data/landfire/US_200CBH.tif \
    --cbd /data/landfire/US_200CBD.tif \
    --cellsize 30 --epsg 32610 \
    --out ./tahoe_inputs
```
