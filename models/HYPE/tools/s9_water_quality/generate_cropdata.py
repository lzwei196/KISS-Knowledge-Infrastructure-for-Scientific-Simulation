#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      generate_cropdata
Stage:        s9_water_quality
Description:  Generate HYPE CropData.txt from NPKGRIDS fertilizer rates and
              crop calendar for any location globally.

              Reads N/P application rates from NPKGRIDS Data KI, applies
              region-specific crop calendars, and writes HYPE-format CropData.txt.

Usage:
    python generate_cropdata.py \
        --lat 32.4 --lon 115.6 \
        --crops wheat,maize \
        --output modelfiles/CropData.txt

Data sources:
    - NPKGRIDS v1.08: N/P/K rates per crop (global, ~10km)
    - CROPGRIDS v1.08: Crop area fraction (for dominant crop detection)
    - Crop calendars: Built-in regional defaults (can be overridden)

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import argparse
import sys
import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Add NPKGRIDS Data KI tool path
sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/data_ki/NPKGRIDS/tools")

# Regional crop calendars (day-of-year for key events)
# Based on FAO crop calendar database and national statistics
CROP_CALENDARS = {
    # China subtropical (Huai River, Yangtze)
    "china_subtropical": {
        "wheat": {"fday1": 300, "fday2": 90, "resday": 160, "bd1": 1, "bd2": 155, "bd3": 170, "bd4": 300, "bd5": 310},
        "maize": {"fday1": 150, "fday2": 210, "resday": 280, "bd1": 1, "bd2": 140, "bd3": 145, "bd4": 290, "bd5": 300},
        "rice":  {"fday1": 120, "fday2": 180, "resday": 270, "bd1": 1, "bd2": 110, "bd3": 115, "bd4": 280, "bd5": 290},
    },
    # US Midwest (Iowa, Illinois, Indiana)
    "us_midwest": {
        "wheat": {"fday1": 260, "fday2": 90, "resday": 180, "bd1": 1, "bd2": 185, "bd3": 190, "bd4": 255, "bd5": 260},
        "maize": {"fday1": 120, "fday2": 180, "resday": 290, "bd1": 1, "bd2": 110, "bd3": 115, "bd4": 300, "bd5": 310},
        "soybean": {"fday1": 135, "fday2": 0, "resday": 280, "bd1": 1, "bd2": 125, "bd3": 130, "bd4": 290, "bd5": 300},
    },
    # Europe temperate (NW Europe)
    "europe_temperate": {
        "wheat": {"fday1": 280, "fday2": 75, "resday": 210, "bd1": 1, "bd2": 215, "bd3": 220, "bd4": 275, "bd5": 280},
        "maize": {"fday1": 120, "fday2": 180, "resday": 280, "bd1": 1, "bd2": 110, "bd3": 115, "bd4": 290, "bd5": 300},
    },
    # Default (generic)
    "default": {
        "wheat": {"fday1": 280, "fday2": 90, "resday": 180, "bd1": 1, "bd2": 185, "bd3": 190, "bd4": 275, "bd5": 280},
        "maize": {"fday1": 130, "fday2": 190, "resday": 280, "bd1": 1, "bd2": 120, "bd3": 125, "bd4": 290, "bd5": 300},
        "rice":  {"fday1": 130, "fday2": 190, "resday": 270, "bd1": 1, "bd2": 120, "bd3": 125, "bd4": 280, "bd5": 290},
        "soybean": {"fday1": 140, "fday2": 0, "resday": 275, "bd1": 1, "bd2": 130, "bd3": 135, "bd4": 285, "bd5": 295},
        "cotton": {"fday1": 120, "fday2": 190, "resday": 300, "bd1": 1, "bd2": 110, "bd3": 115, "bd4": 310, "bd5": 320},
        "sorghum": {"fday1": 140, "fday2": 200, "resday": 270, "bd1": 1, "bd2": 130, "bd3": 135, "bd4": 280, "bd5": 290},
    },
}


def detect_region(lat, lon):
    """Detect crop calendar region from lat/lon."""
    if 20 <= lat <= 45 and 100 <= lon <= 125:
        return "china_subtropical"
    elif 35 <= lat <= 50 and -100 <= lon <= -80:
        return "us_midwest"
    elif 45 <= lat <= 60 and -5 <= lon <= 25:
        return "europe_temperate"
    return "default"


def get_npk_for_crop(lat, lon, crop):
    """Get N/P fertilizer rates from NPKGRIDS."""
    try:
        from get_fertilizer import get_npk_rates
        result = get_npk_rates(lat, lon, crop)
        if "error" in result:
            logger.warning(f"NPKGRIDS error for {crop}: {result['error']}")
            return None
        return result
    except Exception as e:
        logger.warning(f"Could not read NPKGRIDS for {crop}: {e}")
        return None


def generate_cropdata(lat, lon, crops, output_path, region=None):
    """Generate CropData.txt from NPKGRIDS + crop calendar."""
    if region is None:
        region = detect_region(lat, lon)
    logger.info(f"Using crop calendar region: {region}")

    calendar = CROP_CALENDARS.get(region, CROP_CALENDARS["default"])

    crop_list = [c.strip().lower() for c in crops.split(",")]
    records = []

    for cropid, crop in enumerate(crop_list, start=1):
        # Get NPK rates from NPKGRIDS
        npk = get_npk_for_crop(lat, lon, crop)
        if npk is None:
            logger.warning(f"Using default fertilizer rates for {crop}")
            n_rate = 150.0
            p_rate = 30.0
        else:
            n_rate = npk["N_kgha"]
            p_rate = npk["P_kgha"]
            logger.info(f"  {crop}: N={n_rate} kgN/ha, P={p_rate} kgP/ha (from NPKGRIDS)")

        if n_rate <= 0:
            n_rate = 50.0  # minimum default
            logger.info(f"  {crop}: N rate was 0, using minimum default {n_rate}")
        if p_rate <= 0:
            p_rate = 10.0  # minimum default
            logger.info(f"  {crop}: P rate was 0, using minimum default {p_rate}")

        # Get crop calendar
        cal = calendar.get(crop, CROP_CALENDARS["default"].get(crop, {
            "fday1": 130, "fday2": 190, "resday": 270,
            "bd1": 1, "bd2": 120, "bd3": 125, "bd4": 280, "bd5": 290,
        }))

        # Split fertilizer: 60% basal, 40% topdress
        fn1 = round(n_rate * 0.6, 1)
        fn2 = round(n_rate * 0.4, 1)
        fp1 = round(p_rate * 0.6, 1)
        fp2 = round(p_rate * 0.4, 1)

        # Residual N/P (10% of applied N, proportional P)
        resn = round(n_rate * 0.10, 1)
        resp = round(p_rate * 0.10, 1)

        record = {
            "cropid": cropid,
            "reg": 1,
            "fn1": fn1, "fp1": fp1,
            "fday1": cal["fday1"], "fdown1": 0.5,
            "fn2": fn2, "fp2": fp2,
            "fday2": cal["fday2"], "fdown2": 0.3,
            "resn": resn, "resp": resp,
            "resday": cal["resday"], "resdown": 0.3, "resfast": 0.7,
            "up1": 0.5, "up2": 150, "up3": 0.5,
            "upupper": 0.6, "pnupr": round(p_rate / max(n_rate, 1), 3),
            "bd1": cal["bd1"], "bd2": cal["bd2"],
            "bd3": cal["bd3"], "bd4": cal["bd4"], "bd5": cal["bd5"],
        }
        records.append((crop, record))

    # Write CropData.txt
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    cols = ["cropid", "reg", "fn1", "fp1", "fday1", "fdown1",
            "fn2", "fp2", "fday2", "fdown2",
            "resn", "resp", "resday", "resdown", "resfast",
            "up1", "up2", "up3", "upupper", "pnupr",
            "bd1", "bd2", "bd3", "bd4", "bd5"]

    with open(out, "w") as f:
        f.write(f"!! CropData.txt generated from NPKGRIDS for lat={lat}, lon={lon}\n")
        f.write(f"!! Region: {region}, Crops: {', '.join(crop_list)}\n")
        f.write("\t".join(cols) + "\n")
        for crop_name, rec in records:
            vals = [str(rec[c]) for c in cols]
            f.write("\t".join(vals) + "\n")

    logger.info(f"Wrote CropData.txt to {out} ({len(records)} crops)")

    result = {
        "status": "success",
        "output": str(out),
        "region": region,
        "crops": [],
    }
    for crop_name, rec in records:
        result["crops"].append({
            "name": crop_name,
            "cropid": rec["cropid"],
            "N_total_kgha": rec["fn1"] + rec["fn2"],
            "P_total_kgha": rec["fp1"] + rec["fp2"],
            "fert_day1": rec["fday1"],
            "fert_day2": rec["fday2"],
        })

    return result


def main():
    parser = argparse.ArgumentParser(description="Generate HYPE CropData.txt from NPKGRIDS")
    parser.add_argument("--lat", type=float, required=True, help="Basin centroid latitude")
    parser.add_argument("--lon", type=float, required=True, help="Basin centroid longitude")
    parser.add_argument("--crops", required=True,
                        help="Comma-separated crops: wheat,maize,rice,soybean,cotton,sorghum")
    parser.add_argument("--output", required=True, help="Output CropData.txt path")
    parser.add_argument("--region", default=None,
                        choices=list(CROP_CALENDARS.keys()),
                        help="Override auto-detected region")
    args = parser.parse_args()

    try:
        result = generate_cropdata(args.lat, args.lon, args.crops, args.output, args.region)
    except Exception as e:
        logger.error(f"Failed: {e}")
        sys.exit(2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
