#!/usr/bin/env python3
"""
convert_soil_to_monica.py — Convert soil profile data to MONICA site.json format

Supports input from:
  - HWSD (Harmonized World Soil Database) CSV extract
  - SoilGrids API JSON
  - Generic CSV with layer-wise soil properties

Generates the SoilProfileParameters section of site.json with proper units.

Usage:
    python convert_soil_to_monica.py --input soil_profile.csv --format generic_csv \
        --output site.json --lat 52.8 --lon 13.8 --elevation 50 \
        --thickness-col Depth_m --soc-col SOC_pct --sand-col Sand_pct \
        --clay-col Clay_pct --bulk-density-col BD_kg_m3

    python convert_soil_to_monica.py --input hwsd_extract.csv --format hwsd \
        --output site.json --lat 52.8 --lon 13.8 --elevation 50
"""

import argparse
import json
import os
import sys
import csv
import math


# ---------------------------------------------------------------------------
# Pedotransfer functions
# ---------------------------------------------------------------------------

def ptf_field_capacity(sand_frac, clay_frac, soc_pct, bulk_density_kg_m3):
    """
    Estimate field capacity (m³ m⁻³) using Rawls & Brakensiek (1985) PTF.
    sand_frac, clay_frac: mass fractions [0–1]
    soc_pct: soil organic carbon [%]
    bulk_density_kg_m3: bulk density [kg m⁻³]
    """
    bd_gcc = bulk_density_kg_m3 / 1000.0  # → g cm⁻³
    porosity = 1.0 - (bd_gcc / 2.65)
    om_pct = soc_pct / 0.58  # SOC → SOM
    theta_fc = (0.2576 - 0.0020 * sand_frac * 100 + 0.0036 * clay_frac * 100
                + 0.0299 * om_pct)
    theta_fc = max(0.05, min(0.55, theta_fc))
    return round(theta_fc, 4)


def ptf_wilting_point(sand_frac, clay_frac, soc_pct, bulk_density_kg_m3):
    """
    Estimate permanent wilting point (m³ m⁻³) using Rawls & Brakensiek PTF.
    """
    om_pct = soc_pct / 0.58
    theta_wp = (0.0260 + 0.0050 * clay_frac * 100 + 0.0158 * om_pct)
    theta_wp = max(0.01, min(0.40, theta_wp))
    return round(theta_wp, 4)


def ptf_saturation(bulk_density_kg_m3):
    """Estimate saturation (m³ m⁻³) from porosity."""
    bd_gcc = bulk_density_kg_m3 / 1000.0
    porosity = 1.0 - (bd_gcc / 2.65)
    return round(max(0.3, min(0.7, porosity)), 4)


def sand_clay_to_ka5(sand_pct, clay_pct):
    """
    Approximate German KA5 texture class from sand/clay percentages.
    This is a simplified mapping for the most common texture classes.
    """
    if sand_pct > 85:
        return "Ss"   # Sand
    elif sand_pct > 70 and clay_pct < 10:
        return "Su2"  # Slightly silty sand
    elif sand_pct > 50 and clay_pct < 15:
        return "Sl2"  # Slightly loamy sand
    elif sand_pct > 50 and clay_pct < 25:
        return "Sl4"  # Strongly loamy sand
    elif clay_pct > 45:
        return "Tt"   # Clay
    elif clay_pct > 35:
        return "Lt2"  # Clayey loam
    elif clay_pct > 25:
        return "Ls3"  # Sandy clay loam
    elif sand_pct < 20 and clay_pct < 15:
        return "Ut4"  # Silty loam
    elif sand_pct < 40:
        return "Ls2"  # Sandy loam
    else:
        return "Sl3"  # Loamy sand


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []
    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")
    if args.lat is None or args.lon is None:
        errors.append("--lat and --lon are required")
    if args.format == "generic_csv":
        for req in ["thickness_col", "sand_col", "clay_col"]:
            if getattr(args, req) is None:
                errors.append(f"--{req.replace('_', '-')} is required for generic_csv")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def validate_outputs(site_json):
    """Validate the generated site.json for consistency."""
    warnings = []
    params = site_json.get("SiteParameters", {})
    layers = site_json.get("SoilProfileParameters", [])

    if not layers:
        warnings.append("No soil layers defined")
        return warnings

    total_depth = sum(l.get("Thickness", [0.1])[0] if isinstance(l.get("Thickness"), list)
                      else l.get("Thickness", 0.1) for l in layers)
    if total_depth < 0.5:
        warnings.append(f"Total soil depth {total_depth:.2f} m is very shallow (< 0.5 m)")
    if total_depth > 3.0:
        warnings.append(f"Total soil depth {total_depth:.2f} m exceeds typical MONICA max (2 m)")

    for i, layer in enumerate(layers):
        soc = layer.get("SoilOrganicCarbon", [0])[0] if isinstance(
            layer.get("SoilOrganicCarbon"), list) else layer.get("SoilOrganicCarbon", 0)
        bd = layer.get("SoilRawDensity", [1400])[0] if isinstance(
            layer.get("SoilRawDensity"), list) else layer.get("SoilRawDensity", 1400)

        if soc > 20:
            warnings.append(f"Layer {i}: SOC={soc}% is very high (organic soil?)")
        if bd < 500 or bd > 2000:
            warnings.append(f"Layer {i}: Bulk density={bd} kg m⁻³ outside typical [500, 2000]")

    return warnings


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process_generic_csv(args):
    """Read generic soil CSV and build MONICA soil layers."""
    layers = []
    with open(args.input, "r", newline="") as f:
        reader = csv.DictReader(f, delimiter=args.csv_sep or ",")
        for rec in reader:
            thickness_raw = float(rec[args.thickness_col])
            sand_raw = float(rec[args.sand_col])
            clay_raw = float(rec[args.clay_col])

            # Auto-detect units: if sand > 1, assume percent → convert to fraction
            if sand_raw > 1.0:
                sand_frac = sand_raw / 100.0
                clay_frac = clay_raw / 100.0
                sand_pct = sand_raw
                clay_pct = clay_raw
            else:
                sand_frac = sand_raw
                clay_frac = clay_raw
                sand_pct = sand_raw * 100
                clay_pct = clay_raw * 100

            # Auto-detect thickness: if > 1, assume cm → convert to m
            thickness_m = thickness_raw
            if thickness_raw > 1.0:
                thickness_m = thickness_raw / 100.0

            # SOC
            soc_pct = 0.5  # default
            if args.soc_col and args.soc_col in rec:
                soc_raw = float(rec[args.soc_col])
                # Auto-detect: if > 10, probably g/kg → / 10
                if soc_raw > 10:
                    soc_pct = soc_raw / 10.0
                else:
                    soc_pct = soc_raw

            # Bulk density
            bd_kg_m3 = 1400  # default
            if args.bulk_density_col and args.bulk_density_col in rec:
                bd_raw = float(rec[args.bulk_density_col])
                # Auto-detect: if < 5, probably g/cm³ → × 1000
                if bd_raw < 5:
                    bd_kg_m3 = bd_raw * 1000.0
                else:
                    bd_kg_m3 = bd_raw

            # pH
            ph = 6.5  # default
            if args.ph_col and args.ph_col in rec:
                ph = float(rec[args.ph_col])

            ka5 = sand_clay_to_ka5(sand_pct, clay_pct)

            layer = {
                "Thickness": [thickness_m, "m"],
                "SoilOrganicCarbon": [round(soc_pct, 2), "%"],
                "SoilRawDensity": [round(bd_kg_m3, 0), "kg m-3"],
                "Sand": round(sand_frac, 3),
                "Clay": round(clay_frac, 3),
                "KA5TextureClass": ka5,
                "pH": round(ph, 1),
            }
            layers.append(layer)

    return layers


def process_hwsd(args):
    """Read HWSD-format CSV and build MONICA soil layers."""
    layers = []
    with open(args.input, "r", newline="") as f:
        reader = csv.DictReader(f, delimiter=args.csv_sep or ",")
        for rec in reader:
            # HWSD standard column names
            sand_pct = float(rec.get("T_SAND", rec.get("S_SAND", 50)))
            clay_pct = float(rec.get("T_CLAY", rec.get("S_CLAY", 20)))
            soc_pct = float(rec.get("T_OC", rec.get("S_OC", 1.0)))
            bd_gcc = float(rec.get("T_BULK_DENSITY", rec.get("S_BULK_DENSITY", 1.4)))
            ph = float(rec.get("T_PH_H2O", rec.get("S_PH_H2O", 6.5)))

            # HWSD provides topsoil (0-30cm) and subsoil (30-100cm)
            is_topsoil = "T_SAND" in rec or "T_CLAY" in rec
            if is_topsoil:
                # Split topsoil into 3 × 10 cm layers
                for _ in range(3):
                    layers.append({
                        "Thickness": [0.1, "m"],
                        "SoilOrganicCarbon": [round(soc_pct, 2), "%"],
                        "SoilRawDensity": [round(bd_gcc * 1000, 0), "kg m-3"],
                        "Sand": round(sand_pct / 100, 3),
                        "Clay": round(clay_pct / 100, 3),
                        "KA5TextureClass": sand_clay_to_ka5(sand_pct, clay_pct),
                        "pH": round(ph, 1),
                    })
            else:
                # Split subsoil into 7 × 10 cm layers
                for _ in range(7):
                    layers.append({
                        "Thickness": [0.1, "m"],
                        "SoilOrganicCarbon": [round(soc_pct * 0.5, 2), "%"],
                        "SoilRawDensity": [round(bd_gcc * 1000, 0), "kg m-3"],
                        "Sand": round(sand_pct / 100, 3),
                        "Clay": round(clay_pct / 100, 3),
                        "KA5TextureClass": sand_clay_to_ka5(sand_pct, clay_pct),
                        "pH": round(ph, 1),
                    })

    # Pad to 20 layers (2 m) if needed
    while len(layers) < 20:
        if layers:
            deep = dict(layers[-1])
            deep["SoilOrganicCarbon"] = [0.1, "%"]
            layers.append(deep)
        else:
            layers.append({
                "Thickness": [0.1, "m"],
                "SoilOrganicCarbon": [0.5, "%"],
                "SoilRawDensity": [1500, "kg m-3"],
                "Sand": 0.4,
                "Clay": 0.2,
                "KA5TextureClass": "Ls2",
                "pH": 6.5,
            })

    return layers[:20]


def build_site_json(layers, args):
    """Assemble full site.json structure."""
    site = {
        "SiteParameters": {
            "Latitude": [args.lat, "decimal degrees"],
            "Slope": [0, "m/m"],
            "HeightNN": [args.elevation or 0, "m"],
            "NDeposition": [args.n_deposition or 30, "kg N ha-1 y-1"],
            "MaxMineralLayerDepth": 2.0,
            "AtmosphericCO2": [args.co2 or 412, "ppm"],
        },
        "SoilProfileParameters": layers,
        "SoilTemperatureParameters": ["include-from-file", "general/soil-temperature.json"],
        "EnvironmentParameters": {
            "WindSpeedHeight": [2.5, "m"],
            "LeachingDepth": [2.0, "m"],
        },
        "SoilOrganicParameters": ["include-from-file", "general/soil-organic.json"],
        "SoilTransportParameters": ["include-from-file", "general/soil-transport.json"],
        "SoilMoistureParameters": ["include-from-file", "general/soil-moisture.json"],
    }
    return site


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert soil data to MONICA site.json format")
    parser.add_argument("--input", required=True, help="Input soil data file")
    parser.add_argument("--format", choices=["generic_csv", "hwsd"], default="generic_csv")
    parser.add_argument("--output", required=True, help="Output site.json path")
    parser.add_argument("--csv-sep", default=",", help="CSV separator")
    parser.add_argument("--lat", type=float, required=True, help="Site latitude")
    parser.add_argument("--lon", type=float, required=True, help="Site longitude")
    parser.add_argument("--elevation", type=float, default=0, help="Elevation [m]")
    parser.add_argument("--n-deposition", type=float, default=30,
                        help="N deposition [kg N ha-1 yr-1]")
    parser.add_argument("--co2", type=float, default=412, help="Atmospheric CO2 [ppm]")
    parser.add_argument("--thickness-col", help="Layer thickness column")
    parser.add_argument("--soc-col", help="Soil organic carbon column")
    parser.add_argument("--sand-col", help="Sand fraction/percent column")
    parser.add_argument("--clay-col", help="Clay fraction/percent column")
    parser.add_argument("--bulk-density-col", help="Bulk density column")
    parser.add_argument("--ph-col", help="pH column")

    args = parser.parse_args()
    validate_inputs(args)

    if args.format == "generic_csv":
        layers = process_generic_csv(args)
    elif args.format == "hwsd":
        layers = process_hwsd(args)
    else:
        print(json.dumps({"status": "error", "errors": [f"Unknown format: {args.format}"]}),
              file=sys.stderr)
        sys.exit(1)

    site = build_site_json(layers, args)
    warnings = validate_outputs(site)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(site, f, indent=2)

    result = {
        "status": "success",
        "output": args.output,
        "n_layers": len(layers),
        "total_depth_m": sum(l["Thickness"][0] for l in layers),
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
