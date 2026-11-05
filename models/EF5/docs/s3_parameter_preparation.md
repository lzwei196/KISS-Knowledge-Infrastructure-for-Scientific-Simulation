# Stage 3: Parameter Preparation

## Purpose

Derive distributed soil and land surface parameter grids for the chosen water balance model (CREST or SAC-SMA), and set routing parameters. Parameters can be specified as uniform scalars, gridded fields, or multiplicative combinations (scalar × grid).

## Input integrity (2026-10-03)

`convert_params_to_ef5.py` requires georeferenced sand/clay rasters; optional
silt must align exactly, or is derived as the explicit compositional remainder
`100 - sand - clay`. Supported rasters have an explicit EPSG:4326 CRS,
north-up square cells and identical shape/transform/CRS. Projected or
unreferenced grids must be explicitly reprojected/georeferenced first; matching
DEM dimensions alone do not establish location. ASCII rasters need their CRS
sidecar, or an explicit declaration: `--dem-crs EPSG:4326` for a lon/lat
`dem.asc` without `.prj`, `--hwsd-crs EPSG:4326` for the shared `hwsd.bil`
(WGS84 lon/lat, no `.prj`). Only EPSG:4326 can be declared (EF5
`PROJ=geographic`); a file that already has another CRS is refused. The converter never invents an origin or labels projected coordinates
as longitude/latitude.

Every active soil fraction must be finite, between 0 and 100 percent, and
sand+silt+clay must sum to 100 within 0.1 percentage point rounding tolerance.
Zero fractions are valid. With `--dem`, active cells are exactly the soil cells
EF5 itself reads for finite DEM cells (EF5 source `src/Grid.h` GetRefLoc /
GetGridLoc, `src/BasicGrids.cpp`): EF5 places each node at its DEM cell's
UPPER-LEFT CORNER (not the centre; the DEM must be a PixelIsArea GeoTIFF
or an ASCII grid with an `xllcorner`/`yllcorner` header, because EF5 reads the
raw origin and the tool stops on PixelIsPoint, a tiepoint not at raster (0,0),
a ModelTransformation tag, or `xllcenter`) and picks the parameter cell by truncating
(corner - grid origin) / cell size in float precision. CREST
(`src/CRESTModel.cpp`) reads a grid with the DEM's row/column count by row and
column directly, so such a grid must share the DEM transform; SAC-SMA
(`src/SAC.cpp`) always uses the corner lookup. EF5 does not check parameter
NoData, so every cell it reads must hold a real value. A DEM cell counts when
its raw value differs from the numeric NoData (GDAL_NODATA tag / ASCII
NODATA_value, read from the file itself), as in EF5; internal TIFF masks and
`.aux.xml` sidecars are ignored, like EF5 does; an uncovered node or
missing soil stops conversion. Other cells remain NoData. Without a DEM every soil cell is required. `--hwsd` looks up the
dominant mapping-unit component; an absent/invalid active texture stops before
any texture grid is written. There is no default 40/40/20 texture.

All CREST/SAC output grids must pass the existing parameter bounds on active
cells. Validation failure returns false / CLI exit 1. CREST IM comes from the
stated `--impervious` choice only: `grid` needs urban.tif/impervious.tif and
stops without it; `zero` writes IM = 0 everywhere and never reads an urban
grid, even if one is present (SAC never reads it either). For a real IM = 0
model run also set the scalar `IM=0` (see the EF5 IM rules below); soil depth
is an explicit model parameter (default 100 cm), not a fetched observation.

Regression tests: `python -B tests/test_convert_params.py`.

## Inputs

| Input | Format | Source |
|-------|--------|--------|
| Soil texture (sand%, clay%, silt%) | GeoTIFF or NetCDF | HWSD, SoilGrids, STATSGO |
| Soil depth | GeoTIFF | SoilGrids, HWSD |
| Land cover / impervious area | GeoTIFF | MODIS LC, NLCD |
| Hydraulic conductivity (Ksat) | GeoTIFF | SoilGrids, HWSD |
| DEM (for slope/area) | From Stage 1 | — |

## Outputs

### CREST parameters

| Parameter | Grid file | Unit | Description | Typical range |
|-----------|-----------|------|-------------|---------------|
| WM | `wm.tif` | mm | Max soil water capacity | 50–500 |
| B | `b.tif` | — | Variable infiltration exponent | 0.1–1.5 |
| IM | `im.tif` | % (0–100) | Impervious area ratio | 0–30 |
| FC/Ksat | `ksat.tif` | mm/hr | Saturated hydraulic conductivity | 0.1–120 |
| KE | (uniform) | — | PET adjustment factor | 0.5–2.0 |
| IWU | (uniform) | % of WM | Initial soil water content | 10–80 |

### SAC-SMA parameters

| Parameter | Grid file | Unit | Description | Typical range |
|-----------|-----------|------|-------------|---------------|
| UZTWM | `uztwm.tif` | mm | Upper zone tension water max | 10–300 |
| UZFWM | `uzfwm.tif` | mm | Upper zone free water max | 5–150 |
| UZK | `uzk.tif` | day⁻¹ | Upper zone withdrawal rate | 0.1–0.7 |
| LZTWM | `lztwm.tif` | mm | Lower zone tension water max | 10–500 |
| LZFSM | `lzfsm.tif` | mm | Lower zone supplemental free water | 5–400 |
| LZFPM | `lzfpm.tif` | mm | Lower zone primary free water | 10–1000 |
| LZSK | `lzsk.tif` | day⁻¹ | Supplemental withdrawal rate | 0.01–0.3 |
| LZPK | `lzpk.tif` | day⁻¹ | Primary withdrawal rate | 0.001–0.05 |
| PCTIM | (uniform) | % | Minimum impervious area | 0–20 |
| ADIMP | (uniform) | % | Additional impervious area | 0–20 |

### Routing parameters (Kinematic Wave)

| Parameter | Unit | Description | Typical range |
|-----------|------|-------------|---------------|
| ALPHA | — | Channel routing: storage A = alpha × Q^beta (code form; the manual writes Q = alpha × A^beta) | 1–10 |
| BETA | — | Channel routing exponent | 0.5–1.0 |
| ALPHA0 | — | Overland routing multiplier | 1–10 |
| TH | cells | Channel threshold (cells for channel designation) | 5–100 |
| UNDER | — | Interflow speed multiplier | 0.5–5 |
| LEAKI | 0–1 | Interflow reservoir leak rate | 0.01–0.1 |
| ISU | — | Initial interflow reservoir | 0 |

## Procedure

### 1. Derive parameter grids from soil data

```bash
python tools/convert_params_to_ef5.py \
    --soil-dir /data/hwsd/ \
    --output-dir /data/params/ \
    --model crest \
    --dem /data/basic/DEM.tif \
    --depth 100 \
    --impervious grid      # needs urban.tif/impervious.tif; or 'zero' for IM = 0 everywhere
```
The IM source (grid or zero) and the silt source are recorded in
`params_provenance.json` in the output folder.

### 2. Configure scalar multipliers in control.txt

The key EF5 design: **gridded parameters are multiplied by scalar parameters**.
- If grid is already calibrated: set scalar = 1.0
- If grid is a priori (uncalibrated): scalar becomes the calibration knob

EF5 IM rules (`src/CRESTModel.cpp` InitializeParameters): with no `im_grid`
the model IM = scalar `IM` / 100; with `im_grid` the model IM = scalar `IM` x
grid value, and EF5 first replaces every grid value of exactly 0 by 0.01. The
result is clipped to 0..1. So a grid in percent needs `IM=0.01`. For
`--impervious zero` the `im.tif` raster holds 0, but the model is only IM = 0
when the scalar is `IM=0` (with or without `im_grid`); with `IM=0.01` EF5 runs
IM = 0.0001. The raster value is not the model value. `params_provenance.json`
records this as `ef5_config_required`.

```ini
[CrestParamSet mybasin]
wm_grid=/data/params/wm.tif
fc_grid=/data/params/ksat.tif
b_grid=/data/params/b.tif
im_grid=/data/params/im.tif
GAUGE=outlet
WM=1.0          # scalar multiplier on wm_grid
B=1.0           # scalar multiplier on b_grid
IM=0.01         # IM scalar (if no grid: 0-100%; if grid: multiplier). Use IM=0 for --impervious zero
KE=1.0          # PET adjustment
FC=1.0          # scalar multiplier on ksat_grid
IWU=50.0        # initial water as % of WM (no grid)
```

### 3. Set routing parameters

```ini
[KWParamSet mybasin]
GAUGE=outlet
UNDER=1.67
LEAKI=0.04
TH=6.0
ISU=0.0
ALPHA=3.0
BETA=0.93
ALPHA0=4.6
```

## Verification

```python
import numpy as np
from osgeo import gdal

def check_param(path, name, expected_range):
    ds = gdal.Open(path)
    data = ds.GetRasterBand(1).ReadAsArray().astype(float)
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    if nodata: data[data == nodata] = np.nan
    valid = data[~np.isnan(data)]
    lo, hi = expected_range
    pct_out = np.sum((valid < lo) | (valid > hi)) / len(valid) * 100
    print(f"{name}: [{valid.min():.2f}, {valid.max():.2f}], mean={valid.mean():.2f}, {pct_out:.1f}% out of range")
    assert pct_out < 10, f"{name}: too many values out of range!"

check_param("wm.tif", "WM", (10, 2000))
check_param("ksat.tif", "FC/Ksat", (0.01, 500))
check_param("b.tif", "B", (0.01, 2.0))
check_param("im.tif", "IM", (0, 100))
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| IM grid in 0–1 range but scalar=5 | Effective IM = 5× grid, too much impervious | If grid is 0–1, keep scalar near 0.01; if grid is 0–100, keep scalar=1 |
| WM too low (<10 mm) | Soil saturates instantly, excessive runoff | Check grid values; increase WM scalar |
| WM too high (>2000 mm) | No runoff generated, all water absorbed | Reduce WM or check soil depth assumption |
| Ksat too high | All water infiltrates, no surface runoff | Verify units are mm/hr, not cm/hr or m/s |
| B=0 | Division errors in variable infiltration curve | B must be > 0; typical 0.1–1.5 |
| Grid resolution mismatch | Parameters applied to wrong cells | Resample param grids to match DEM resolution |
| Grid zero values | Param × 0 = 0, causes NaN/crash | EF5 replaces 0 with 0.01 in grid (see source) |
| IWU > 100 | Initial SM > WM, unstable start | Keep IWU in 0–100 range |
| Missing param for a gauge | Gauge has no parameters, crash | Every independent gauge needs param set |

## Example

```ini
# SAC-SMA parameter set with gridded a priori parameters
[SacParamSet ABRFC]
UZTWM_grid=/data/params/uztwm_usa.tif
UZFWM_grid=/data/params/uzfwm_usa.tif
UZK_grid=/data/params/uzk_usa.tif
LZTWM_grid=/data/params/lztwm_usa.tif
LZFSM_grid=/data/params/lzfsm_usa.tif
LZFPM_grid=/data/params/lzfpm_usa.tif
LZSK_grid=/data/params/lzsk_usa.tif
LZPK_grid=/data/params/lzpk_usa.tif
GAUGE=01055000
UZTWM=1.0
UZFWM=1.0
UZK=1.0
PCTIM=0.1
ADIMP=0.1
RIVA=1.0
ZPERC=1.0
REXP=1.0
LZTWM=1.0
LZFSM=1.0
LZFPM=1.0
LZSK=1.0
LZPK=1.0
PFREE=1.0
SIDE=0.0
RSERV=0.3
UZTWC=0.55
UZFWC=0.14
LZTWC=0.56
LZFSC=0.11
LZFPC=0.46
```
