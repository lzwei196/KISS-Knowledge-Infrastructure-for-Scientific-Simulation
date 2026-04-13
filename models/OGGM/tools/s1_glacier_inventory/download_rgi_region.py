#!/usr/bin/env python3
"""
Download RGI Region — OGGM Knowledge Infrastructure

Download Randolph Glacier Inventory (RGI) outlines for a specified region.
Auto-detects the correct region from lat/lon coordinates.

Usage:
    python download_rgi_region.py \
        --lat 29.5 --lon 94.5 \
        --output_dir data/rgi/RGIV62
"""

import argparse
import json
import sys
from pathlib import Path

# RGI v6 first-order region centroids for auto-detection
RGI_REGIONS = {
    '01': {'name': 'Alaska', 'lat_range': (53, 72), 'lon_range': (-176, -126)},
    '02': {'name': 'Western Canada and US', 'lat_range': (35, 62), 'lon_range': (-133, -104)},
    '03': {'name': 'Arctic Canada North', 'lat_range': (68, 84), 'lon_range': (-125, -60)},
    '04': {'name': 'Arctic Canada South', 'lat_range': (58, 75), 'lon_range': (-95, -55)},
    '05': {'name': 'Greenland Periphery', 'lat_range': (59, 84), 'lon_range': (-74, -12)},
    '06': {'name': 'Iceland', 'lat_range': (63, 67), 'lon_range': (-25, -13)},
    '07': {'name': 'Svalbard', 'lat_range': (70, 81), 'lon_range': (-10, 35)},
    '08': {'name': 'Scandinavia', 'lat_range': (58, 72), 'lon_range': (4, 32)},
    '09': {'name': 'Russian Arctic', 'lat_range': (68, 82), 'lon_range': (30, 105)},
    '10': {'name': 'North Asia', 'lat_range': (42, 70), 'lon_range': (46, 180)},
    '11': {'name': 'Central Europe', 'lat_range': (42, 48), 'lon_range': (5, 17)},
    '12': {'name': 'Caucasus and Middle East', 'lat_range': (30, 45), 'lon_range': (40, 55)},
    '13': {'name': 'Central Asia', 'lat_range': (27, 50), 'lon_range': (60, 105)},
    '14': {'name': 'South Asia West', 'lat_range': (25, 40), 'lon_range': (66, 82)},
    '15': {'name': 'South Asia East', 'lat_range': (25, 40), 'lon_range': (80, 105)},
    '16': {'name': 'Low Latitudes', 'lat_range': (-20, 20), 'lon_range': (-82, 40)},
    '17': {'name': 'Southern Andes', 'lat_range': (-56, -17), 'lon_range': (-76, -65)},
    '18': {'name': 'New Zealand', 'lat_range': (-46, -42), 'lon_range': (166, 175)},
    '19': {'name': 'Antarctic', 'lat_range': (-78, -53), 'lon_range': (-180, 180)},
}


def detect_region(lat, lon):
    """Detect RGI region from coordinates."""
    for rid, info in RGI_REGIONS.items():
        if (info['lat_range'][0] <= lat <= info['lat_range'][1] and
                info['lon_range'][0] <= lon <= info['lon_range'][1]):
            return rid, info['name']
    return None, None


def main():
    parser = argparse.ArgumentParser(
        description="Download RGI region shapefiles"
    )
    parser.add_argument("--lat", type=float, help="Latitude for auto-detection")
    parser.add_argument("--lon", type=float, help="Longitude for auto-detection")
    parser.add_argument("--rgi_region", type=str, default=None,
                        help="Explicit RGI region number (overrides lat/lon)")
    parser.add_argument("--rgi_version", default="62", help="RGI version (default 62)")
    parser.add_argument("--output_dir", required=True, help="Output directory for RGI files")
    args = parser.parse_args()

    # Determine region
    if args.rgi_region:
        region = args.rgi_region.zfill(2)
        region_name = RGI_REGIONS.get(region, {}).get('name', 'Unknown')
    elif args.lat is not None and args.lon is not None:
        region, region_name = detect_region(args.lat, args.lon)
        if region is None:
            print(f"ERROR: Could not detect RGI region for ({args.lat}, {args.lon})")
            print("Specify --rgi_region manually")
            sys.exit(1)
    else:
        print("ERROR: Provide either (--lat, --lon) or --rgi_region")
        sys.exit(1)

    print(f"RGI Region: {region} ({region_name})")
    print(f"RGI Version: {args.rgi_version}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Try OGGM download
    try:
        import oggm
        from oggm import utils, cfg

        cfg.initialize(logging_level='WARNING')

        print("Downloading RGI via OGGM...")
        rgi_dir = utils.get_rgi_dir(version=args.rgi_version)
        print(f"RGI data cached at: {rgi_dir}")

        # Find the specific region files
        rgi_path = Path(rgi_dir)
        region_dirs = list(rgi_path.glob(f"*{region}*"))

        if region_dirs:
            print(f"Region data found: {region_dirs[0]}")
            result = {
                'status': 'success',
                'rgi_region': region,
                'region_name': region_name,
                'rgi_version': args.rgi_version,
                'rgi_dir': str(region_dirs[0]),
                'cached_at': str(rgi_dir)
            }
        else:
            result = {
                'status': 'warning',
                'message': f'RGI downloaded but region {region} not found in {rgi_dir}',
                'rgi_dir': str(rgi_dir)
            }

    except ImportError:
        print("OGGM not installed. Manual download required.")
        print(f"Download RGI v{args.rgi_version} from: https://www.glims.org/RGI/")
        print(f"Extract region {region} to: {output_dir}")
        result = {
            'status': 'error',
            'message': 'OGGM not installed — manual download required',
            'download_url': 'https://www.glims.org/RGI/',
            'region': region,
            'region_name': region_name
        }

    except Exception as e:
        print(f"Download error: {e}")
        print("Server may be temporarily unavailable. Retry in a few minutes.")
        result = {
            'status': 'error',
            'message': str(e),
            'region': region,
            'region_name': region_name
        }

    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
