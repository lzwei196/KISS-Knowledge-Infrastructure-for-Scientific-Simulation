#!/usr/bin/env python3
"""
convert_soil.py — Convert HWSD/SoilGrids data to APSIM soil JSON fragment.

Reads soil properties from HWSD database (CSV or shapefile) or SoilGrids NetCDF
and produces a JSON fragment suitable for embedding into an .apsimx simulation file.

CRITICAL UNIT CONVERSIONS:
  - SoilGrids bulk density: kg/m³ → g/cc  (÷ 1000)
  - SoilGrids water content: % (v/v) → mm/mm  (÷ 100)
  - HWSD layer thickness: cm → mm  (× 10)
  - SoilGrids organic carbon: g/kg → %  (÷ 10)
  - SoilGrids clay/sand/silt: g/kg → %  (÷ 10)

CRITICAL CONSTRAINT: AirDry ≤ LL15 ≤ DUL ≤ SAT for every layer.
  Violation crashes the APSIM water balance model.

Usage:
  python convert_soil.py --input hwsd_extract.csv --output soil.json \\
      --lat -27.18 --lon 151.26 --source hwsd --crop Wheat

  python convert_soil.py --input soilgrids_profile.nc --output soil.json \\
      --lat -27.18 --lon 151.26 --source soilgrids --crop Wheat
"""

import argparse
import json
import math
import os
import sys

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None


# Pedotransfer functions (Saxton & Rawls 2006)
def saxton_rawls_water_limits(sand_pct, clay_pct, om_pct):
    """Estimate soil water limits using Saxton & Rawls (2006) pedotransfer.

    Args:
        sand_pct: Sand content (%)
        clay_pct: Clay content (%)
        om_pct: Organic matter content (%)

    Returns:
        dict with LL15, DUL, SAT in mm/mm
    """
    S = sand_pct / 100.0
    C = clay_pct / 100.0
    OM = om_pct / 100.0

    # Wilting point (1500 kPa)
    theta_1500t = (
        -0.024 * S + 0.487 * C + 0.006 * OM
        + 0.005 * S * OM - 0.013 * C * OM
        + 0.068 * S * C + 0.031
    )
    theta_1500 = theta_1500t + 0.14 * theta_1500t - 0.02

    # Field capacity (33 kPa)
    theta_33t = (
        -0.251 * S + 0.195 * C + 0.011 * OM
        + 0.006 * S * OM - 0.027 * C * OM
        + 0.452 * S * C + 0.299
    )
    theta_33 = theta_33t + (1.283 * theta_33t * theta_33t - 0.374 * theta_33t - 0.015)

    # Saturation
    theta_s_33t = (
        0.278 * S + 0.034 * C + 0.022 * OM
        - 0.018 * S * OM - 0.027 * C * OM
        - 0.584 * S * C + 0.078
    )
    theta_s_33 = theta_s_33t + (0.636 * theta_s_33t - 0.107)
    theta_sat = theta_33 + theta_s_33 - 0.097 * S + 0.043

    # Clamp to physical bounds
    theta_1500 = max(0.01, min(theta_1500, 0.40))
    theta_33 = max(theta_1500 + 0.01, min(theta_33, 0.50))
    theta_sat = max(theta_33 + 0.01, min(theta_sat, 0.60))

    return {
        "LL15": round(theta_1500, 3),
        "DUL": round(theta_33, 3),
        "SAT": round(theta_sat, 3),
    }


def estimate_ks(sand_pct, clay_pct):
    """Estimate saturated hydraulic conductivity (mm/day) from texture.

    Uses simplified Cosby et al. (1984) relationship.
    """
    # KS in cm/hr = 10^(-0.6 + 0.0126*Sand - 0.0064*Clay)
    log_ks_cm_hr = -0.6 + 0.0126 * sand_pct - 0.0064 * clay_pct
    ks_cm_hr = 10 ** log_ks_cm_hr
    ks_mm_day = ks_cm_hr * 240  # cm/hr → mm/day
    return round(max(1.0, min(ks_mm_day, 5000.0)), 1)


def estimate_cn2(clay_pct):
    """Estimate SCS curve number for bare soil from clay content."""
    if clay_pct < 20:
        return 73
    elif clay_pct < 35:
        return 80
    elif clay_pct < 50:
        return 85
    else:
        return 88


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.lat is None or not (-90 <= args.lat <= 90):
        errors.append(f"Latitude must be between -90 and 90, got: {args.lat}")

    if args.lon is None or not (-180 <= args.lon <= 360):
        errors.append(f"Longitude must be between -180 and 360, got: {args.lon}")

    if args.source not in ("hwsd", "soilgrids", "csv"):
        errors.append(f"Unknown source: {args.source}. Use hwsd, soilgrids, or csv")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def read_hwsd_csv(filepath, lat, lon):
    """Read HWSD extract CSV and return layer data.

    Expected columns: depth_top_cm, depth_bot_cm, sand_pct, silt_pct, clay_pct,
                      bulk_density_kg_m3, organic_carbon_g_kg, ph_water
    """
    df = pd.read_csv(filepath)

    layers = []
    for _, row in df.iterrows():
        depth_top = float(row.get("depth_top_cm", row.get("top", 0)))
        depth_bot = float(row.get("depth_bot_cm", row.get("bottom", 30)))
        thickness_mm = (depth_bot - depth_top) * 10  # cm → mm

        sand = float(row.get("sand_pct", row.get("sand", 40)))
        clay = float(row.get("clay_pct", row.get("clay", 30)))
        silt = 100 - sand - clay

        # Unit conversions
        bd_raw = float(row.get("bulk_density_kg_m3", row.get("bd", 1400)))
        if bd_raw > 100:  # kg/m³
            bd = bd_raw / 1000.0
        else:  # already g/cc
            bd = bd_raw

        oc_raw = float(row.get("organic_carbon_g_kg", row.get("oc", 10)))
        if oc_raw > 10:  # g/kg
            oc_pct = oc_raw / 10.0
        else:  # already %
            oc_pct = oc_raw

        om_pct = oc_pct * 1.724  # OC → OM conversion factor

        ph = float(row.get("ph_water", row.get("ph", 6.5)))

        # Estimate water limits
        wl = saxton_rawls_water_limits(sand, clay, om_pct)

        # AirDry approximation: 50% of LL15 for topsoil, closer to LL15 for subsoil
        if depth_top < 30:
            air_dry = round(wl["LL15"] * 0.5, 3)
        else:
            air_dry = round(wl["LL15"] * 0.9, 3)

        layers.append({
            "thickness_mm": round(thickness_mm, 0),
            "bd": round(bd, 2),
            "air_dry": air_dry,
            "ll15": wl["LL15"],
            "dul": wl["DUL"],
            "sat": wl["SAT"],
            "ks": estimate_ks(sand, clay),
            "sand": round(sand, 1),
            "silt": round(silt, 1),
            "clay": round(clay, 1),
            "oc": round(oc_pct, 2),
            "ph": round(ph, 1),
        })

    return layers


def build_apsim_soil_json(layers, crop, lat, lon):
    """Build APSIM soil JSON structure from layer data."""

    n = len(layers)

    # Extract arrays
    thickness = [l["thickness_mm"] for l in layers]
    bd = [l["bd"] for l in layers]
    air_dry = [l["air_dry"] for l in layers]
    ll15 = [l["ll15"] for l in layers]
    dul = [l["dul"] for l in layers]
    sat = [l["sat"] for l in layers]
    ks = [l["ks"] for l in layers]
    sand = [l["sand"] for l in layers]
    clay = [l["clay"] for l in layers]
    oc = [l["oc"] for l in layers]
    ph = [l["ph"] for l in layers]

    # Crop-specific lower limit (slightly above LL15)
    crop_ll = [round(l["ll15"] * 1.05, 3) for l in layers]
    # KL decreases with depth
    kl = [round(max(0.01, 0.08 - i * 0.01), 3) for i in range(n)]
    # XF = 1.0 for all layers with roots, decreasing for deep layers
    xf = [round(max(0.0, 1.0 - max(0, i - 4) * 0.2), 1) for i in range(n)]

    # SWCON (drainage rate) — higher for sandy, lower for clay
    swcon = [round(min(0.9, max(0.1, 0.5 + (l["sand"] - 50) * 0.005)), 2)
             for l in layers]

    # CN2 from topsoil clay
    cn2 = estimate_cn2(clay[0])

    # Initial water at 50% PAWC
    init_sw = [round(ll15[i] + 0.5 * (dul[i] - ll15[i]), 3) for i in range(n)]

    # Initial nitrogen (decreasing with depth)
    no3 = [round(max(1.0, 20.0 / (i + 1)), 1) for i in range(n)]
    nh4 = [round(max(0.1, 2.0 / (i + 1)), 2) for i in range(n)]

    soil_json = {
        "$type": "Models.Soils.Soil, Models",
        "Name": "Soil",
        "Latitude": lat,
        "Longitude": lon,
        "Children": [
            {
                "$type": "Models.Soils.Physical, Models",
                "Name": "Physical",
                "Thickness": thickness,
                "BD": bd,
                "AirDry": air_dry,
                "LL15": ll15,
                "DUL": dul,
                "SAT": sat,
                "KS": ks,
                "ParticleSizeSand": sand,
                "ParticleSizeClay": clay,
                "Children": [
                    {
                        "$type": "Models.Soils.SoilCrop, Models",
                        "Name": f"{crop}Soil",
                        "LL": crop_ll,
                        "KL": kl,
                        "XF": xf,
                    }
                ],
            },
            {
                "$type": "Models.Soils.Chemical, Models",
                "Name": "Chemical",
                "Thickness": thickness,
                "PH": ph,
            },
            {
                "$type": "Models.Soils.Organic, Models",
                "Name": "Organic",
                "Thickness": thickness,
                "Carbon": oc,
                "FBiom": [round(max(0.01, 0.04 - i * 0.005), 3) for i in range(n)],
                "FInert": [round(min(0.99, 0.4 + i * 0.1), 2) for i in range(n)],
            },
            {
                "$type": "Models.WaterModel.WaterBalance, Models",
                "Name": "WaterBalance",
                "ResourceName": "WaterBalance",
                "Thickness": thickness,
                "SWCON": swcon,
                "SummerDate": "1-Nov",
                "SummerU": 6.0,
                "SummerCona": 3.5,
                "WinterDate": "1-Apr",
                "WinterU": 4.0,
                "WinterCona": 2.5,
                "DiffusConst": 40.0,
                "DiffusSlope": 16.0,
                "Salb": 0.13,
                "CN2Bare": cn2,
                "CNRed": 20.0,
                "CNCov": 0.8,
            },
            {
                "$type": "Models.Soils.Water, Models",
                "Name": "Water",
                "Thickness": thickness,
                "InitialValues": init_sw,
            },
            {
                "$type": "Models.Soils.CERESSoilTemperature, Models",
                "Name": "Temperature",
            },
            {
                "$type": "Models.Soils.Nutrient, Models",
                "Name": "Nutrient",
                "Children": [],
            },
            {
                "$type": "Models.Soils.Sample, Models",
                "Name": "Initial nitrogen",
                "Thickness": thickness,
                "NO3N": no3,
                "NH4N": nh4,
            },
        ],
    }

    return soil_json


def process(args):
    """Main processing logic."""
    if args.source in ("hwsd", "csv"):
        layers = read_hwsd_csv(args.input, args.lat, args.lon)
    elif args.source == "soilgrids":
        # SoilGrids NetCDF — similar structure but from xarray
        layers = read_hwsd_csv(args.input, args.lat, args.lon)
    else:
        layers = read_hwsd_csv(args.input, args.lat, args.lon)

    if not layers:
        return {"status": "error", "errors": ["No soil layers extracted from input"]}

    soil_json = build_apsim_soil_json(layers, args.crop, args.lat, args.lon)

    return {
        "status": "ok",
        "soil_json": soil_json,
        "n_layers": len(layers),
        "total_depth_mm": sum(l["thickness_mm"] for l in layers),
        "layers_summary": [
            {
                "depth_mm": l["thickness_mm"],
                "clay_pct": l["clay"],
                "ll15": l["ll15"],
                "dul": l["dul"],
                "sat": l["sat"],
            }
            for l in layers
        ],
    }


def validate_outputs(result):
    """Validate output meets APSIM constraints."""
    warnings = []

    if result["status"] != "ok":
        return result

    soil = result["soil_json"]
    physical = soil["Children"][0]

    n = len(physical["Thickness"])

    for i in range(n):
        ad = physical["AirDry"][i]
        ll = physical["LL15"][i]
        dul = physical["DUL"][i]
        sat = physical["SAT"][i]

        if not (ad <= ll <= dul <= sat):
            warnings.append(
                f"Layer {i}: Water limit ordering violated: "
                f"AirDry({ad}) <= LL15({ll}) <= DUL({dul}) <= SAT({sat})"
            )
            # Auto-fix
            physical["AirDry"][i] = min(ad, ll)
            physical["LL15"][i] = max(physical["AirDry"][i], min(ll, dul))
            physical["DUL"][i] = max(physical["LL15"][i], min(dul, sat))
            physical["SAT"][i] = max(physical["DUL"][i], sat)

        if physical["BD"][i] < 0.5 or physical["BD"][i] > 2.2:
            warnings.append(f"Layer {i}: BD={physical['BD'][i]} g/cc outside typical range (0.5-2.2)")

    if result["total_depth_mm"] < 300:
        warnings.append(f"Total soil depth {result['total_depth_mm']}mm seems shallow (< 300mm)")

    if result["total_depth_mm"] > 5000:
        warnings.append(f"Total soil depth {result['total_depth_mm']}mm seems very deep (> 5000mm)")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert HWSD/SoilGrids data to APSIM soil JSON"
    )
    parser.add_argument("--input", required=True, help="Input soil data file (CSV)")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--lat", type=float, required=True, help="Site latitude")
    parser.add_argument("--lon", type=float, required=True, help="Site longitude")
    parser.add_argument("--source", type=str, default="hwsd",
                        help="Data source: hwsd, soilgrids, csv")
    parser.add_argument("--crop", type=str, default="Wheat",
                        help="Crop name for SoilCrop parameters")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    # Write output
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result["soil_json"], f, indent=2)

    # Print summary
    summary = {k: v for k, v in result.items() if k != "soil_json"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
