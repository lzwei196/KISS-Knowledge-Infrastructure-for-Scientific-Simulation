#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      export_nowcast
Stage:        s5_postprocess
Description:  Export pySTEPS nowcast to standard geospatial formats (NetCDF, GeoTIFF, CSV).

CRITICAL:
  - Output unit is mm/h (rainfall intensity). For accumulation, multiply by timestep_hours.
  - GeoTIFF requires CRS from metadata. If projection is missing, defaults to EPSG:4326.
  - For ensemble: exports ensemble mean, individual members, and exceedance probabilities.

Inputs:
  --nowcast_dir:  Directory with nowcast.npz and nowcast_summary.json (from s3)
  --input_dir:    Directory with metadata.json (from s1, for spatial reference)
  --format:       Output format: netcdf, geotiff, csv (default: netcdf)
  --accumulate:   If set, output accumulated precipitation (mm) instead of rate (mm/h)
  --output_dir:   Output directory

Outputs:
  - nowcast.nc / nowcast_*.tif / nowcast.csv
  - export_summary.json

Exit codes:
  0 — success, 1 — input error, 2 — processing error, 3 — output error
"""

import sys
import os
import json
import logging
import argparse
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs(args):
    errors = []
    if not (Path(args.nowcast_dir) / 'nowcast.npz').exists():
        errors.append(f"nowcast.npz not found in {args.nowcast_dir}")
    if not (Path(args.input_dir) / 'metadata.json').exists():
        errors.append(f"metadata.json not found in {args.input_dir}")
    if args.format not in ['netcdf', 'geotiff', 'csv']:
        errors.append(f"Unknown format: {args.format}")
    return errors


def export_netcdf(forecast, metadata, summary, output_dir, accumulate):
    """Export forecast as NetCDF with CF conventions."""
    try:
        import xarray as xr
    except ImportError:
        raise ImportError("xarray required for NetCDF export: pip install xarray netcdf4")

    timestep_min = summary.get('timestep_min', 5)
    n_leadtimes = forecast.shape[-3] if forecast.ndim >= 3 else forecast.shape[0]
    ny, nx = forecast.shape[-2], forecast.shape[-1]

    # Build coordinates
    x1 = metadata.get('x1', 0)
    x2 = metadata.get('x2', nx)
    y1 = metadata.get('y1', 0)
    y2 = metadata.get('y2', ny)
    lons = np.linspace(x1, x2, nx)
    lats = np.linspace(y1, y2, ny)
    times = np.arange(1, n_leadtimes + 1) * timestep_min  # Lead time in minutes

    # Handle accumulation
    unit = 'mm/h'
    var_name = 'precipitation_rate'
    if accumulate:
        forecast = forecast * (timestep_min / 60.0)
        unit = 'mm'
        var_name = 'precipitation_accumulated'
        logger.info(f"Converted to accumulated precipitation (mm), timestep={timestep_min} min")

    is_ensemble = forecast.ndim == 4

    if is_ensemble:
        n_ens = forecast.shape[0]
        # Ensemble mean
        ens_mean = np.mean(forecast, axis=0)

        ds = xr.Dataset({
            'ensemble_mean': (['leadtime', 'y', 'x'], ens_mean,
                              {'units': unit, 'long_name': f'Ensemble mean {var_name}'}),
        })

        # Add a few members (first 5 or all if < 5)
        for i in range(min(5, n_ens)):
            ds[f'member_{i:03d}'] = (['leadtime', 'y', 'x'], forecast[i],
                                      {'units': unit, 'long_name': f'Member {i} {var_name}'})

        # Exceedance probabilities
        for thr in [0.1, 1.0, 5.0, 10.0]:
            prob = np.mean(forecast > thr, axis=0)
            ds[f'prob_gt_{thr}'] = (['leadtime', 'y', 'x'], prob,
                                     {'units': '1', 'long_name': f'P(R > {thr} mm/h)'})
    else:
        ds = xr.Dataset({
            var_name: (['leadtime', 'y', 'x'], forecast,
                       {'units': unit, 'long_name': var_name}),
        })

    ds.coords['leadtime'] = ('leadtime', times, {'units': 'minutes', 'long_name': 'Lead time'})
    ds.coords['x'] = ('x', lons)
    ds.coords['y'] = ('y', lats)

    ds.attrs['projection'] = metadata.get('projection', 'unknown')
    ds.attrs['source'] = 'pySTEPS nowcast'
    ds.attrs['timestep_minutes'] = timestep_min

    out_path = output_dir / 'nowcast.nc'
    ds.to_netcdf(out_path)
    logger.info(f"NetCDF saved: {out_path}")
    return str(out_path)


def export_geotiff(forecast, metadata, summary, output_dir, accumulate):
    """Export forecast as per-leadtime GeoTIFF files."""
    try:
        import rasterio
        from rasterio.transform import from_bounds
        from rasterio.crs import CRS
    except ImportError:
        raise ImportError("rasterio required for GeoTIFF export: pip install rasterio")

    timestep_min = summary.get('timestep_min', 5)

    if accumulate:
        forecast = forecast * (timestep_min / 60.0)

    # Use ensemble mean for ensemble
    if forecast.ndim == 4:
        forecast = np.mean(forecast, axis=0)

    ny, nx = forecast.shape[-2], forecast.shape[-1]
    x1 = metadata.get('x1', 0)
    x2 = metadata.get('x2', nx)
    y1 = metadata.get('y1', 0)
    y2 = metadata.get('y2', ny)

    transform = from_bounds(x1, y1, x2, y2, nx, ny)
    proj_str = metadata.get('projection', 'EPSG:4326')
    try:
        crs = CRS.from_user_input(proj_str)
    except Exception:
        crs = CRS.from_epsg(4326)
        logger.warning(f"Could not parse projection '{proj_str}', defaulting to EPSG:4326")

    out_files = []
    for lt in range(forecast.shape[0]):
        fname = output_dir / f'nowcast_lt{lt+1:03d}.tif'
        with rasterio.open(fname, 'w', driver='GTiff', height=ny, width=nx,
                           count=1, dtype='float32', crs=crs, transform=transform,
                           nodata=-9999) as dst:
            band = forecast[lt].astype(np.float32)
            band[np.isnan(band)] = -9999
            dst.write(band, 1)
        out_files.append(str(fname))

    logger.info(f"GeoTIFF saved: {len(out_files)} files")
    return out_files


def export_csv(forecast, metadata, summary, output_dir, accumulate):
    """Export domain-average time series to CSV."""
    timestep_min = summary.get('timestep_min', 5)

    if accumulate:
        forecast = forecast * (timestep_min / 60.0)

    if forecast.ndim == 4:
        ens_mean = np.mean(forecast, axis=0)
    else:
        ens_mean = forecast

    rows = []
    for lt in range(ens_mean.shape[0]):
        frame = ens_mean[lt]
        rows.append({
            'leadtime_min': (lt + 1) * timestep_min,
            'mean_mmh': round(float(np.nanmean(frame)), 4),
            'max_mmh': round(float(np.nanmax(frame)), 4),
            'p90_mmh': round(float(np.nanpercentile(frame, 90)), 4),
            'wet_fraction': round(float(np.mean(frame > 0.1)), 4),
        })

    import csv
    out_path = output_dir / 'nowcast_timeseries.csv'
    with open(out_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"CSV saved: {out_path}")
    return str(out_path)


def run(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    forecast = np.load(Path(args.nowcast_dir) / 'nowcast.npz')['forecast']
    metadata = json.loads((Path(args.input_dir) / 'metadata.json').read_text())
    summary = json.loads((Path(args.nowcast_dir) / 'nowcast_summary.json').read_text())

    logger.info(f"Exporting forecast shape={forecast.shape} to {args.format}")

    if args.format == 'netcdf':
        out = export_netcdf(forecast, metadata, summary, output_dir, args.accumulate)
    elif args.format == 'geotiff':
        out = export_geotiff(forecast, metadata, summary, output_dir, args.accumulate)
    elif args.format == 'csv':
        out = export_csv(forecast, metadata, summary, output_dir, args.accumulate)

    export_summary = {
        'format': args.format,
        'accumulated': args.accumulate,
        'unit': 'mm' if args.accumulate else 'mm/h',
        'output_files': out if isinstance(out, list) else [out],
        'forecast_shape': list(forecast.shape),
    }
    (output_dir / 'export_summary.json').write_text(json.dumps(export_summary, indent=2))

    return 0


def main():
    parser = argparse.ArgumentParser(description="Export pySTEPS nowcast to standard formats")
    parser.add_argument('--nowcast_dir', required=True, help="Directory with nowcast.npz")
    parser.add_argument('--input_dir', required=True, help="Directory with metadata.json")
    parser.add_argument('--format', default='netcdf', help="Output format: netcdf, geotiff, csv")
    parser.add_argument('--accumulate', action='store_true',
                        help="Output accumulated precipitation (mm) instead of rate (mm/h)")
    parser.add_argument('--output_dir', required=True, help="Output directory")
    args = parser.parse_args()

    errors = validate_inputs(args)
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    try:
        sys.exit(run(args))
    except Exception as e:
        logger.error(f"Processing error: {e}")
        sys.exit(2)


if __name__ == '__main__':
    main()
