#!/usr/bin/env python3
"""S1 Terrain builder for DHSVM (Linux-native, replaces the arcpy/AML path).
Produces dem.bin (float32), slope.bin (float32 rad), aspect.bin (float32 deg 0=N)
and mask.bin (uint8, 1 byte/cell) in flat-binary row-major order, matching the
shipped TestCase/Chiwawa/input binaries (dem.bin=ncells*4, mask.bin=ncells*1).
NOTE: docs/s1_terrain_preparation.md says mask is int32 -- that is WRONG; the
shipped Chiwawa mask.bin is 1 byte/cell. This tool follows the shipped example.
"""
import argparse, os, numpy as np, rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling

def reproject_dem(src_path, epsg, res):
    with rasterio.open(src_path) as src:
        dst_crs = f'EPSG:{epsg}'
        transform, w, h = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds, resolution=res)
        dem = np.empty((h, w), np.float32)
        reproject(source=rasterio.band(src, 1), destination=dem,
                  src_transform=src.transform, src_crs=src.crs,
                  dst_transform=transform, dst_crs=dst_crs,
                  resampling=Resampling.bilinear)
        nod = src.nodata
    if nod is not None:
        dem[dem == nod] = np.nan
    return dem, transform, res

def slope_aspect(dem, cell):
    z = np.where(np.isnan(dem), np.nanmean(dem), dem)
    dzdy, dzdx = np.gradient(z, cell, cell)
    slope = np.arctan(np.hypot(dzdx, dzdy)).astype(np.float32)        # radians
    aspect = (np.degrees(np.arctan2(dzdy, -dzdx)) + 360.0) % 360.0    # 0=N CW
    return slope, aspect.astype(np.float32)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dem', required=True, help='input DEM GeoTIFF (m)')
    ap.add_argument('--epsg', type=int, required=True, help='target projected EPSG (UTM)')
    ap.add_argument('--res', type=float, required=True, help='grid spacing (m)')
    ap.add_argument('--mask', help='basin mask raster (>0 inside); default = finite DEM')
    ap.add_argument('--outdir', required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    dem, transform, cell = reproject_dem(a.dem, a.epsg, a.res)
    nrows, ncols = dem.shape
    if a.mask:
        with rasterio.open(a.mask) as m:
            mraw = m.read(1)
        mask = (np.resize(mraw, dem.shape) > 0).astype(np.uint8)
    else:
        mask = np.isfinite(dem).astype(np.uint8)
    dem_f = np.where(np.isfinite(dem), dem, 0.0).astype(np.float32)
    slope, aspect = slope_aspect(dem, cell)
    dem_f.tofile(os.path.join(a.outdir, 'dem.bin'))
    mask.tofile(os.path.join(a.outdir, 'mask.bin'))       # uint8 == shipped Chiwawa
    slope.tofile(os.path.join(a.outdir, 'slope.bin'))
    aspect.tofile(os.path.join(a.outdir, 'aspect.bin'))
    print(f'OK rows={nrows} cols={ncols} cells={nrows*ncols} '
          f'dem.bin={nrows*ncols*4}B mask.bin={nrows*ncols}B active={int(mask.sum())}')

if __name__ == '__main__':
    main()
