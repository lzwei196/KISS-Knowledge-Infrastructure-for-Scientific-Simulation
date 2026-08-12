#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      import_radar_data
Stage:        s1_data_import
Description:  Import radar precipitation data from various formats into pysteps-ready arrays.

CRITICAL UNIT CONVERSION:
  Many radar sources provide dBZ (reflectivity). pySTEPS nowcast routines expect mm/h.
  Conversion: R = (10^(dBZ/10) / 200)^(1/1.6)  (Marshall-Palmer Z-R relation)
  Always check metadata['unit'] after import.

Supported formats:
  - OPERA HDF5 (European composite)
  - KNMI HDF5 (Netherlands)
  - MCH GIF (MeteoSwiss)
  - BoM RF3 GeoTIFF (Australian BoM)
  - Generic GeoTIFF (single-band precipitation)
  - Generic NetCDF (with lat/lon/time dims)

Inputs:
  --data_dir:      Directory containing radar files
  --format:        Radar format: opera_hdf5, knmi_hdf5, mch_gif, bom_rf3, geotiff, netcdf
  --start_time:    Start time (YYYYMMDD_HHMM)
  --end_time:      End time (YYYYMMDD_HHMM)
  --timestep:      Frame timestep in minutes (default: 5)
  --n_frames:      Number of past frames to load (default: 4)
  --output_dir:    Output directory for processed arrays
  --convert_to_mmh: Convert to mm/h if input is dBZ (default: true)

Outputs:
  - radar_frames.npz:  NumPy archive with 'data' (n_frames, ny, nx) and 'metadata' dict
  - import_summary.json: Summary with unit info, frame count, spatial extent

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
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

IMPORTERS = {
    'opera_hdf5': 'pysteps.io.importers.import_opera_hdf5',
    'knmi_hdf5':  'pysteps.io.importers.import_knmi_hdf5',
    'mch_gif':    'pysteps.io.importers.import_mch_gif',
    'bom_rf3':    'pysteps.io.importers.import_bom_rf3',
}


def validate_inputs(args):
    errors = []
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        errors.append(f"Data directory not found: {data_dir}")
    if args.format not in list(IMPORTERS.keys()) + ['geotiff', 'netcdf']:
        errors.append(f"Unknown format: {args.format}. "
                      f"Supported: {list(IMPORTERS.keys()) + ['geotiff', 'netcdf']}")
    if args.n_frames < 2:
        errors.append("Need at least 2 frames for motion estimation")
    if args.timestep not in [5, 10, 15, 30, 60]:
        logger.warning(f"Non-standard timestep: {args.timestep} min. Typical: 5, 10, 15.")
    return errors


def dbz_to_mmh(data):
    """Convert dBZ to mm/h using Marshall-Palmer Z-R relation."""
    Z = 10.0 ** (data / 10.0)
    R = (Z / 200.0) ** (1.0 / 1.6)
    return R


def import_with_pysteps(data_dir, fmt, n_frames, timestep):
    """Import using pysteps native importers."""
    import pysteps
    from pysteps.io import archive

    # Try to discover files using pysteps archive
    files = sorted(Path(data_dir).glob('*'))
    if not files:
        raise FileNotFoundError(f"No files found in {data_dir}")

    logger.info(f"Found {len(files)} files in {data_dir}")

    # Import the appropriate reader
    importer_name = IMPORTERS.get(fmt)
    if importer_name:
        mod_path, func_name = importer_name.rsplit('.', 1)
        import importlib
        mod = importlib.import_module(mod_path)
        importer = getattr(mod, func_name)
    else:
        raise ValueError(f"No pysteps importer for format: {fmt}")

    # Read frames
    frames = []
    metadata = None
    selected_files = files[-n_frames:]  # Take last n_frames

    for f in selected_files:
        try:
            data, quality, meta = importer(str(f))
            if data is not None:
                frames.append(data)
                metadata = meta
        except Exception as e:
            logger.warning(f"Failed to read {f.name}: {e}")

    if not frames:
        raise ValueError("No frames successfully imported")

    data = np.stack(frames, axis=0)
    if metadata:
        metadata['accutime'] = timestep

    return data, metadata


def import_geotiff(data_dir, n_frames):
    """Import from single-band GeoTIFF files."""
    try:
        import rasterio
    except ImportError:
        raise ImportError("rasterio required for GeoTIFF import: pip install rasterio")

    files = sorted(Path(data_dir).glob('*.tif')) + sorted(Path(data_dir).glob('*.tiff'))
    if not files:
        raise FileNotFoundError(f"No .tif/.tiff files in {data_dir}")

    selected = files[-n_frames:]
    frames = []
    metadata = {}

    for f in selected:
        with rasterio.open(f) as src:
            data = src.read(1).astype(np.float64)
            nodata = src.nodata
            if nodata is not None:
                data[data == nodata] = np.nan
            frames.append(data)

            if not metadata:
                bounds = src.bounds
                metadata = {
                    'x1': bounds.left, 'x2': bounds.right,
                    'y1': bounds.bottom, 'y2': bounds.top,
                    'xpixelsize': src.res[0], 'ypixelsize': src.res[1],
                    'projection': str(src.crs),
                    'unit': 'mm/h',
                    'transform': None,
                }

    return np.stack(frames, axis=0), metadata


def import_netcdf(data_dir, n_frames, var_name='precipitation'):
    """Import from NetCDF files with lat/lon/time dimensions."""
    try:
        import xarray as xr
    except ImportError:
        raise ImportError("xarray required for NetCDF import: pip install xarray")

    files = sorted(Path(data_dir).glob('*.nc'))
    if not files:
        raise FileNotFoundError(f"No .nc files in {data_dir}")

    ds = xr.open_mfdataset(files)

    # Find precipitation variable
    precip_vars = [v for v in ds.data_vars if any(k in v.lower()
                   for k in ['precip', 'rain', 'rr', 'pr', 'qpe'])]
    if precip_vars:
        var_name = precip_vars[0]
    elif var_name not in ds.data_vars:
        raise ValueError(f"Variable '{var_name}' not found. Available: {list(ds.data_vars)}")

    data = ds[var_name].values
    if data.ndim == 3:
        data = data[-n_frames:]
    elif data.ndim == 2:
        data = data[np.newaxis, :]

    # Build metadata
    lons = ds['lon'].values if 'lon' in ds else ds['x'].values
    lats = ds['lat'].values if 'lat' in ds else ds['y'].values
    metadata = {
        'x1': float(lons.min()), 'x2': float(lons.max()),
        'y1': float(lats.min()), 'y2': float(lats.max()),
        'xpixelsize': float(np.abs(np.diff(lons[:2])[0])) if len(lons) > 1 else 1.0,
        'ypixelsize': float(np.abs(np.diff(lats[:2])[0])) if len(lats) > 1 else 1.0,
        'unit': ds[var_name].attrs.get('units', 'mm/h'),
        'transform': None,
        'projection': 'EPSG:4326',
    }

    ds.close()
    return data.astype(np.float64), metadata


def run(args):
    logger.info(f"Importing {args.n_frames} frames from {args.data_dir} (format: {args.format})")

    # Import data based on format
    if args.format == 'geotiff':
        data, metadata = import_geotiff(args.data_dir, args.n_frames)
    elif args.format == 'netcdf':
        data, metadata = import_netcdf(args.data_dir, args.n_frames)
    else:
        data, metadata = import_with_pysteps(args.data_dir, args.format, args.n_frames,
                                              args.timestep)

    # Handle NaN
    nan_frac = np.isnan(data).mean()
    if nan_frac > 0:
        logger.info(f"NaN fraction: {nan_frac:.2%}")
        if nan_frac > 0.2:
            logger.warning("NaN fraction > 20% — nowcast quality may be poor")
        data = np.nan_to_num(data, nan=0.0)

    # Unit conversion: dBZ → mm/h
    unit = metadata.get('unit', 'mm/h') if metadata else 'mm/h'
    if unit == 'dBZ' and args.convert_to_mmh:
        logger.info("Converting dBZ → mm/h (Marshall-Palmer Z-R)")
        data = dbz_to_mmh(data)
        metadata['unit'] = 'mm/h'
        metadata['transform'] = None
    elif unit == 'dBZ':
        logger.warning("Data is in dBZ but --no-convert_to_mmh specified. "
                        "Ensure you apply dB_transform before nowcasting.")

    # Validate value range
    valid_data = data[data > 0]
    if len(valid_data) > 0:
        p99 = np.percentile(valid_data, 99)
        logger.info(f"Data range: min={data.min():.3f}, max={data.max():.3f}, "
                    f"p99={p99:.3f} {metadata.get('unit', '?')}")
        if metadata.get('unit') == 'mm/h' and p99 > 200:
            logger.warning(f"p99={p99:.1f} mm/h is very high — check units")

    # Save
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert metadata to JSON-serializable
    meta_serializable = {}
    for k, v in (metadata or {}).items():
        if isinstance(v, (np.integer, np.floating)):
            meta_serializable[k] = float(v)
        elif isinstance(v, np.ndarray):
            meta_serializable[k] = v.tolist()
        else:
            meta_serializable[k] = v

    np.savez_compressed(output_dir / 'radar_frames.npz', data=data)
    (output_dir / 'metadata.json').write_text(json.dumps(meta_serializable, indent=2))

    summary = {
        'n_frames': int(data.shape[0]),
        'ny': int(data.shape[1]),
        'nx': int(data.shape[2]),
        'unit': metadata.get('unit', 'unknown'),
        'format': args.format,
        'timestep_min': args.timestep,
        'data_range': {'min': float(data.min()), 'max': float(data.max())},
        'nan_fraction_original': float(nan_frac),
        'spatial_extent': {
            'x1': meta_serializable.get('x1'),
            'x2': meta_serializable.get('x2'),
            'y1': meta_serializable.get('y1'),
            'y2': meta_serializable.get('y2'),
        },
    }
    (output_dir / 'import_summary.json').write_text(json.dumps(summary, indent=2))

    logger.info(f"Saved {data.shape[0]} frames ({data.shape[1]}x{data.shape[2]}) to {output_dir}")
    logger.info(f"Unit: {metadata.get('unit', '?')}, timestep: {args.timestep} min")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Import radar data for pySTEPS nowcasting")
    parser.add_argument('--data_dir', required=True, help="Directory with radar files")
    parser.add_argument('--format', required=True,
                        help="Radar format: opera_hdf5, knmi_hdf5, mch_gif, bom_rf3, geotiff, netcdf")
    parser.add_argument('--start_time', default=None, help="Start time YYYYMMDD_HHMM")
    parser.add_argument('--end_time', default=None, help="End time YYYYMMDD_HHMM")
    parser.add_argument('--timestep', type=int, default=5, help="Frame timestep in minutes")
    parser.add_argument('--n_frames', type=int, default=4, help="Number of past frames")
    parser.add_argument('--output_dir', required=True, help="Output directory")
    parser.add_argument('--convert_to_mmh', type=bool, default=True,
                        help="Convert dBZ to mm/h (default: true)")
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
