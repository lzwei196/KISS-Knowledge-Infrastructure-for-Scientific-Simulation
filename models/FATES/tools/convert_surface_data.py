#!/usr/bin/env python3
"""
convert_surface_data.py — Surface Dataset Generator for FATES/CTSM

Generates or modifies CLM surface datasets for single-point FATES runs.
Maps soil properties from HWSD or user-specified values and configures
PFT distributions for the target location.

Follows validate → process → validate pattern.

Usage:
    python convert_surface_data.py --lat -2.609 --lon -60.209 \
        --soil-source hwsd --soil-depth 1.0 --output surfdata_k34.json

    python convert_surface_data.py --lat 45.0 --lon -90.0 \
        --soil-texture "clay_pct=25,sand_pct=40,silt_pct=35" \
        --organic-matter-pct 2.5 --bulk-density 1.35 \
        --soil-depth 2.0 --output surfdata_custom.json

See docs/s2_surface_data.md for the per-layer soil rules (HWSD 0-30 / 30-100
cm; below 1 m only with --deep-layers-from-subsoil; no default soil).
"""

import argparse
import json
import math
import os
import sys
import warnings as _warnings
import numpy as np
from typing import Dict, List, Any, Optional, Tuple

# ─── USDA Soil Texture Classes ──────────────────────────────────────────────
SOIL_TEXTURE_CLASSES = {
    "clay":       {"clay": 60, "sand": 20, "silt": 20},
    "silty_clay": {"clay": 45, "sand": 5,  "silt": 50},
    "sandy_clay": {"clay": 40, "sand": 50, "silt": 10},
    "clay_loam":  {"clay": 33, "sand": 33, "silt": 34},
    "loam":       {"clay": 20, "sand": 40, "silt": 40},
    "sandy_loam": {"clay": 10, "sand": 65, "silt": 25},
    "silt_loam":  {"clay": 15, "sand": 20, "silt": 65},
    "sand":       {"clay": 5,  "sand": 90, "silt": 5},
    "silt":       {"clay": 5,  "sand": 5,  "silt": 90},
}

# ─── CLM Soil Layer Depths (m) ──────────────────────────────────────────────
CLM_SOIL_DEPTHS = [
    0.0175, 0.0451, 0.0906, 0.1655, 0.2891, 0.4929, 0.8289,
    1.3828, 2.2961, 3.8019, 6.3258, 10.5297, 17.5328, 25.0,
    35.0, 45.0  # bedrock layers
]

# ─── Default PFT area fractions (tropical broadleaf evergreen) ──────────────
DEFAULT_PFT_FRACTIONS = {0: 1.0}  # 100% broadleaf evergreen tropical

def validate_inputs(args: argparse.Namespace) -> List[str]:
    """Stage 1: Validate command-line arguments."""
    errors = []

    # Every number must be finite (argparse float() accepts 'nan' and 'inf',
    # and NaN passes every < / > range test).
    for name in ("lat", "lon", "soil_depth", "organic_matter_pct", "bulk_density"):
        v = getattr(args, name, None)
        if v is not None and not math.isfinite(v):
            errors.append(f"--{name.replace('_', '-')} must be a finite number, got {v}")

    # Validate coordinates
    if args.lat < -90 or args.lat > 90:
        errors.append(f"Latitude must be in [-90, 90], got {args.lat}")
    if args.lon < -360 or args.lon > 360:
        errors.append(f"Longitude must be in [-360, 360], got {args.lon}")

    # Validate user organic matter and bulk density
    om = args.organic_matter_pct
    if om is not None and math.isfinite(om) and not (0.0 <= om <= 100.0):
        errors.append(f"--organic-matter-pct must be in [0, 100] %, got {om}")
    bd = args.bulk_density
    if bd is not None and math.isfinite(bd) and not (BD_MIN <= bd <= BD_MAX):
        errors.append(f"--bulk-density must be in [{BD_MIN}, {BD_MAX}] g/cm3, got {bd}")

    # Validate soil source
    if args.soil_source == "hwsd" and args.hwsd_path:
        if not os.path.exists(args.hwsd_path):
            errors.append(f"HWSD file not found: {args.hwsd_path}")

    # Validate soil texture if provided
    if args.soil_texture:
        try:
            parts = parse_soil_texture(args.soil_texture)
            for k, v in parts.items():
                if not math.isfinite(v) or v < 0.0 or v > 100.0:
                    errors.append(f"Soil texture {k}_pct must be a finite value in [0, 100], got {v}")
            total = sum(parts.values())
            if not math.isfinite(total) or abs(total - 100.0) > 1.0:
                errors.append(
                    f"Soil texture fractions must sum to 100%, got {total}%")
        except ValueError as e:
            errors.append(f"Invalid soil texture format: {e}")

    # Validate PFT distribution
    if args.pft_distribution:
        try:
            pft_dist = parse_pft_distribution(args.pft_distribution)
            for idx, frac in pft_dist.items():
                if not math.isfinite(frac) or frac < 0.0 or frac > 1.0:
                    errors.append(f"PFT {idx} fraction must be a finite value in [0, 1], got {frac}")
            total = sum(pft_dist.values())
            if not math.isfinite(total) or abs(total - 1.0) > 0.01:
                errors.append(
                    f"PFT fractions must sum to 1.0, got {total}")
            for idx in pft_dist:
                if idx < 0 or idx >= 14:
                    errors.append(f"PFT index must be 0-13, got {idx}")
        except ValueError as e:
            errors.append(f"Invalid PFT distribution format: {e}")

    if args.soil_depth is not None:
        if args.soil_depth <= 0 or args.soil_depth > 100:
            errors.append(f"Soil depth must be in (0, 100] m, got {args.soil_depth}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2),
              file=sys.stderr)
        sys.exit(1)

    return errors


def parse_soil_texture(texture_str: str) -> Dict[str, float]:
    """Parse soil texture string like 'clay_pct=25,sand_pct=40,silt_pct=35'.
    Exactly clay, sand and silt, each once; anything else is an error."""
    parts = {}
    for item in texture_str.split(","):
        key, val = item.strip().split("=")
        key = key.strip().replace("_pct", "")
        if key not in ("clay", "sand", "silt"):
            raise ValueError(f"unknown texture key '{key}' (use clay_pct, sand_pct, silt_pct)")
        if key in parts:
            raise ValueError(f"texture key '{key}' given twice")
        parts[key] = float(val.strip())
    missing = [k for k in ("clay", "sand", "silt") if k not in parts]
    if missing:
        raise ValueError(f"texture lacks {missing}")
    return parts


def parse_pft_distribution(dist_str: str) -> Dict[int, float]:
    """Parse PFT distribution string like '1:0.8,5:0.2'."""
    result = {}
    for item in dist_str.split(","):
        idx, frac = item.strip().split(":")
        i = int(idx.strip())
        if i in result:
            raise ValueError(f"PFT index {i} given twice")
        result[i] = float(frac.strip())
    return result


# HWSD depths: topsoil 0-0.30 m, subsoil 0.30-1.00 m.
HWSD_TOP_BOTTOM_M = 0.30
HWSD_SUB_BOTTOM_M = 1.00
OM_PER_OC = 1.724   # organic matter = 1.724 x organic carbon (van Bemmelen)
BD_MIN, BD_MAX = 0.5, 2.0   # accepted bulk density range, g/cm3
# Pressure -> water head: 1 kPa = 1000 Pa / (rho_w 1000 kg/m3 x g 9.80665 m/s2)
# = 0.10197 m = 101.97 mm of water. CLM / Clapp-Hornberger psi is in mm.
MM_H2O_PER_KPA = 1.0e6 / (1000.0 * 9.80665)
PSI_FC_KPA = 33.0      # field capacity
PSI_WP_KPA = 1500.0    # wilting point


def hwsd_lon(lon: float) -> float:
    """Longitude for the HWSD raster, which uses -180..180."""
    return ((float(lon) + 180.0) % 360.0) - 180.0


def clm_lon(lon: float) -> float:
    """Longitude in the CLM 0..360 convention."""
    return float(lon) % 360.0


def hwsd_subsoil_needed(soil_depth: float, n_layers: int = 15) -> bool:
    """True when an active CLM layer (node depth <= soil_depth) lies below the
    HWSD topsoil (0.30 m), so the HWSD subsoil values are used."""
    return any(HWSD_TOP_BOTTOM_M < d <= soil_depth for d in CLM_SOIL_DEPTHS[:n_layers])


def lookup_hwsd(lat: float, lon: float, hwsd_raster: Optional[str] = None,
                need_sub: bool = True) -> Dict[str, Any]:
    """HWSD topsoil and subsoil at (lat, lon) via the shared
    ki_tools_common.soil_utils.lookup_hwsd (hwsd.bil raster + HWSD_DATA.csv,
    one row for top and sub). Any failure or missing field that is used stops
    the tool. need_sub=False (every active layer is in the 0-30 cm topsoil):
    subsoil values are not read, and "sub" is None.

    Units: texture %, OC % by weight (-> OM % = OC x 1.724), bulk density
    g/cm3 (HWSD T_/S_REF_BULK_DENSITY)."""
    sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
    from ki_tools_common.soil_utils import lookup_hwsd as _lookup
    if hwsd_raster and not os.path.exists(hwsd_raster):
        raise FileNotFoundError(f"--hwsd-path raster not found: {hwsd_raster}")
    lon_h = hwsd_lon(lon)
    try:
        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always")
            h = _lookup(lat, lon_h, hwsd_raster=hwsd_raster)
        comp = dict(h.get("hwsd_component") or {})
        notes = [str(w.message) for w in caught]
        if comp.get("texture_from_dominant") is False:
            notes.append(
                f"HWSD map unit {h['mu_id']}: soil values come from a {comp.get('share_pct')}% "
                f"component, NOT the dominant {comp.get('dominant_share_pct')}% component "
                f"(it has no usable texture); see soil_provenance in the output.")
        top = {"clay_pct": float(h["clay"]), "sand_pct": float(h["sand"]),
               "silt_pct": float(h["silt"]),
               "organic_matter_pct": float(h["oc"]) * OM_PER_OC,
               "bulk_density_g_cm3": float(h["bulk_density"])}
        sub = None
        if need_sub:
            sub = {"clay_pct": float(h["sub_clay"]), "sand_pct": float(h["sub_sand"]),
                   "silt_pct": float(h["sub_silt"]),
                   "organic_matter_pct": float(h["sub_oc"]) * OM_PER_OC,
                   "bulk_density_g_cm3": float(h["sub_bulk_density"])}
        return {
            "top": top,
            "sub": sub,
            "mu_id": h["mu_id"],
            "source": "HWSD (ki_tools_common.lookup_hwsd)",
            "provenance": {
                "source": "HWSD v1.2 (ki_tools_common.lookup_hwsd: hwsd.bil + HWSD_DATA.csv)",
                "mu_id": h["mu_id"],
                "lat": lat,
                "lon_sampled_-180_180": lon_h,
                "component": comp,
                "subsoil_used": bool(need_sub),
                "notes": notes,
            },
        }
    except (RuntimeError, ValueError, FileNotFoundError, KeyError) as e:
        # A failed lookup stops the tool; no default soil is used in its place.
        raise RuntimeError(f"HWSD lookup failed at ({lat}, {lon}): {e}") from e


def compute_hydraulic_properties(clay_pct: float, sand_pct: float,
                                  bulk_density_g_cm3: float) -> Dict[str, float]:
    """Compute soil hydraulic properties from texture (Clapp-Hornberger) and
    the given bulk density (porosity = 1 - BD / 2.65)."""
    # Clapp-Hornberger parameters from soil texture
    # Based on Cosby et al. (1984)
    b_ch = 2.91 + 0.159 * clay_pct
    psi_sat = -10.0 * (10.0 ** (1.88 - 0.0131 * sand_pct))  # mm
    k_sat = 0.0070556 * (10.0 ** (-0.884 + 0.0153 * sand_pct))  # mm/s

    # Porosity from the given bulk density (particle density 2.65 g/cm³)
    bd = float(bulk_density_g_cm3)
    if not (BD_MIN <= bd <= BD_MAX):
        raise ValueError(f"bulk density {bd} g/cm3 outside 0.5-2.0")
    porosity = 1.0 - bd / 2.65

    # Field capacity (-33 kPa) and wilting point (-1500 kPa) from the
    # Clapp-Hornberger curve theta = porosity x (psi / psi_sat)^(-1/b), with
    # psi and psi_sat both in mm of water head (kPa -> mm first).
    psi_fc_mm = PSI_FC_KPA * MM_H2O_PER_KPA
    psi_wp_mm = PSI_WP_KPA * MM_H2O_PER_KPA
    fc = porosity * min(1.0, (psi_fc_mm / abs(psi_sat)) ** (-1.0 / b_ch))
    wp = porosity * min(1.0, (psi_wp_mm / abs(psi_sat)) ** (-1.0 / b_ch))

    return {
        "b_clapp_hornberger": round(b_ch, 3),
        "psi_sat_mm": round(psi_sat, 3),
        "k_sat_mm_s": round(k_sat, 6),
        "porosity": round(porosity, 4),
        "field_capacity": round(fc, 4),
        "wilting_point": round(wp, 4),
        "bulk_density_g_cm3": round(bd, 3),
    }


def generate_soil_profile(top: Dict[str, float], sub: Optional[Dict[str, float]],
                          soil_depth: float, deep_from_subsoil: bool = False,
                          n_layers: int = 15, hwsd: Optional[bool] = None) -> Dict[str, Any]:
    """Soil properties per CLM soil layer (by layer node depth).

    HWSD source: node depth <= 0.30 m -> HWSD topsoil, 0.30-1.00 m -> HWSD
    subsoil. A layer below 1.00 m (and within soil_depth) has no HWSD value:
    the tool stops unless deep_from_subsoil is set, which copies the subsoil
    values there and records that rule in the output. Manual / texture-class
    source (sub is None): the user's single values apply to every layer down
    to soil_depth, as stated by the user. Layers below soil_depth are bedrock
    (0). No depth trend is invented. hwsd=True with sub None is allowed only
    when no active layer is below 0.30 m (HWSD subsoil not needed).
    """
    if hwsd is None:
        hwsd = sub is not None
    depths = CLM_SOIL_DEPTHS[:n_layers]
    keys = ("clay_pct", "sand_pct", "silt_pct", "organic_matter_pct", "bulk_density_g_cm3")
    prof = {k: [] for k in keys}
    source_by_layer = []
    n_soil = 0
    deep = [d for d in depths if HWSD_SUB_BOTTOM_M < d <= soil_depth]
    if hwsd and sub is None and any(HWSD_TOP_BOTTOM_M < d <= soil_depth for d in depths):
        raise ValueError("HWSD subsoil values are needed for layers below 0.30 m but were not read")
    if hwsd and deep and not deep_from_subsoil:
        raise ValueError(
            f"--soil-depth {soil_depth} m puts {len(deep)} CLM layer(s) (node depths "
            f"{[round(d, 3) for d in deep]} m) below the HWSD depth (1.00 m), where HWSD "
            f"has no values. Use --soil-depth <= 1.0, or pass --deep-layers-from-subsoil "
            f"to copy the HWSD 30-100 cm values there on purpose.")
    for d in depths:
        if d > soil_depth:
            vals, src = {k: 0.0 for k in keys}, "bedrock (below --soil-depth)"
        else:
            n_soil += 1
            if not hwsd:
                vals, src = top, "user values (manual / texture class)"
            elif d <= HWSD_TOP_BOTTOM_M:
                vals, src = top, "HWSD topsoil 0-30 cm"
            elif d <= HWSD_SUB_BOTTOM_M:
                vals, src = sub, "HWSD subsoil 30-100 cm"
            else:
                vals, src = sub, "HWSD subsoil 30-100 cm COPIED below 1 m (--deep-layers-from-subsoil)"
        for k in keys:
            prof[k].append(round(float(vals[k]), 4))
        source_by_layer.append(src)
    # CLM surface-data ORGANIC is organic matter density in kg/m3:
    # OM% / 100 x bulk density (g/cm3) x 1000.
    organic_kg_m3 = [round(om / 100.0 * bd * 1000.0, 3)
                     for om, bd in zip(prof["organic_matter_pct"], prof["bulk_density_g_cm3"])]
    return {
        "layer_depths_m": depths,
        "n_soil_layers": n_soil,
        "clay_pct": prof["clay_pct"],
        "sand_pct": prof["sand_pct"],
        "silt_pct": prof["silt_pct"],
        "organic_matter_pct": prof["organic_matter_pct"],
        "bulk_density_g_cm3": prof["bulk_density_g_cm3"],
        "ORGANIC_kg_m3": organic_kg_m3,
        "source_by_layer": source_by_layer,
        "deep_layers_from_subsoil": bool(deep_from_subsoil and hwsd and deep),
    }


def generate_surface_dataset(lat: float, lon: float,
                              soil_profile: Dict[str, List[float]],
                              pft_distribution: Dict[int, float],
                              hydraulic_props: Dict[str, float],
                              output_path: str,
                              soil_provenance: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Generate a surface dataset description (JSON format for documentation)."""
    # In a full implementation, this would write a NetCDF file via the host
    # model's mksurfdata_esmf tool. Here we generate the specification.
    dataset = {
        "metadata": {
            "title": f"FATES surface dataset for ({lat}, {lon})",
            "conventions": "CLM surface data format",
            "source": "convert_surface_data.py",
            "creation_date": "auto-generated",
        },
        "grid": {
            "latitude": lat,
            "longitude": clm_lon(lon),  # CLM uses 0-360
            "n_soil_layers": soil_profile["n_soil_layers"],
            "layer_depths_m": soil_profile["layer_depths_m"],
        },
        "soil_properties": {
            "clay_pct_by_layer": soil_profile["clay_pct"],
            "sand_pct_by_layer": soil_profile["sand_pct"],
            "silt_pct_by_layer": soil_profile["silt_pct"],
            "organic_matter_by_layer": soil_profile["organic_matter_pct"],
            "organic_matter_unit": "% by mass (= HWSD OC % x 1.724)",
            "bulk_density_g_cm3_by_layer": soil_profile["bulk_density_g_cm3"],
            "ORGANIC_kg_m3_by_layer": soil_profile["ORGANIC_kg_m3"],
            "ORGANIC_note": "CLM surfdata ORGANIC (organic matter density, kg/m3) = OM% / 100 x BD x 1000",
            "source_by_layer": soil_profile["source_by_layer"],
            "deep_layers_from_subsoil": soil_profile["deep_layers_from_subsoil"],
            "hydraulic": hydraulic_props,
            "provenance": soil_provenance,
        },
        "vegetation": {
            "pft_distribution": {f"PFT_{k}": v for k, v in pft_distribution.items()},
            "total_pft_fraction": sum(pft_distribution.values()),
            "n_active_pfts": len(pft_distribution),
        },
        "output_file": output_path,
    }

    # Write JSON specification
    with open(output_path, "w") as f:
        json.dump(dataset, f, indent=2)

    return dataset


def validate_outputs(dataset: Dict[str, Any]) -> List[str]:
    """Stage 3: Validate generated surface dataset."""
    warnings = []

    # Check soil texture sums
    soil = dataset.get("soil_properties", {})
    clay = soil.get("clay_pct_by_layer", [])
    sand = soil.get("sand_pct_by_layer", [])
    silt = soil.get("silt_pct_by_layer", [])

    for i, (c, s, si) in enumerate(zip(clay, sand, silt)):
        total = c + s + si
        if abs(total - 100.0) > 2.0 and total > 0:
            warnings.append(
                f"Layer {i}: texture fractions sum to {total:.1f}%, expected 100%")

    # Check PFT distribution
    veg = dataset.get("vegetation", {})
    total_pft = veg.get("total_pft_fraction", 0)
    if abs(total_pft - 1.0) > 0.01:
        warnings.append(
            f"PFT fractions sum to {total_pft}, expected 1.0")

    # Check coordinate conversion
    grid = dataset.get("grid", {})
    lon = grid.get("longitude", 0)
    if lon < 0:
        warnings.append(
            f"Longitude is negative ({lon}°). CLM typically uses 0-360° convention.")

    # Check hydraulic properties
    hydro_all = soil.get("hydraulic", {})
    sets = hydro_all.items() if "topsoil" in hydro_all else [("soil", hydro_all)]
    for name, hydro in sets:
        if hydro["field_capacity"] > hydro["porosity"]:
            warnings.append(
                f"{name}: field capacity ({hydro['field_capacity']}) > porosity "
                f"({hydro['porosity']}) — physically impossible")
        porosity = hydro["porosity"]
        if porosity < 0.2 or porosity > 0.7:
            warnings.append(
                f"{name}: porosity {porosity} outside typical range [0.2, 0.7]")
        fc = hydro["field_capacity"]
        wp = hydro["wilting_point"]
        if fc <= wp:
            warnings.append(
                f"{name}: field capacity ({fc}) <= wilting point ({wp}) — physically impossible")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Generate surface dataset for FATES/CTSM single-point runs")
    parser.add_argument("--lat", type=float, required=True, help="Latitude (degrees)")
    parser.add_argument("--lon", type=float, required=True, help="Longitude (degrees)")
    parser.add_argument("--soil-source", choices=["hwsd", "manual", "texture_class"],
                        default="manual", help="Soil data source")
    parser.add_argument("--hwsd-path", help="Optional hwsd.bil raster path for --soil-source hwsd "
                        "(default: the server HWSD raster used by ki_tools_common)")
    parser.add_argument("--deep-layers-from-subsoil", action="store_true",
                        help="HWSD source only: copy the HWSD 30-100 cm subsoil values into CLM "
                             "layers below 1.0 m (within --soil-depth). Without it such layers stop "
                             "the tool. Recorded in the output.")
    parser.add_argument("--organic-matter-pct", type=float,
                        help="Organic matter %% for --soil-texture / --texture-class (required there)")
    parser.add_argument("--bulk-density", type=float,
                        help="Bulk density g/cm3 for --soil-texture / --texture-class (required there)")
    parser.add_argument("--soil-texture",
                        help="Manual texture: clay_pct=25,sand_pct=40,silt_pct=35")
    parser.add_argument("--texture-class", choices=list(SOIL_TEXTURE_CLASSES.keys()),
                        help="USDA soil texture class name")
    parser.add_argument("--soil-depth", type=float, default=2.0,
                        help="Soil depth in meters (default: 2.0)")
    parser.add_argument("--pft-distribution",
                        help="PFT fractions: '1:0.8,5:0.2'")
    parser.add_argument("--output", required=True, help="Output file path")
    args = parser.parse_args()

    # Stage 1: Validate inputs
    validate_inputs(args)

    # Stage 2: Process
    # Determine soil texture
    # Every soil value comes from HWSD or from values the user states; there
    # is no default soil.
    if args.soil_source == "hwsd":
        soil = lookup_hwsd(args.lat, args.lon, args.hwsd_path,
                           need_sub=hwsd_subsoil_needed(args.soil_depth))
        top, sub = soil["top"], soil["sub"]
        provenance = soil["provenance"]
    elif args.texture_class or args.soil_texture:
        if args.organic_matter_pct is None or args.bulk_density is None:
            sys.exit("ERROR: --soil-texture / --texture-class also need --organic-matter-pct and "
                     "--bulk-density (no default organic matter or density is used)")
        if args.texture_class:
            tex = SOIL_TEXTURE_CLASSES[args.texture_class]
        else:
            parts = parse_soil_texture(args.soil_texture)
            missing = [k for k in ("clay", "sand", "silt") if k not in parts]
            if missing:
                sys.exit(f"ERROR: --soil-texture lacks {missing}")
            tex = parts
        provenance = {"source": f"user values ({'--texture-class ' + args.texture_class if args.texture_class else '--soil-texture'}, "
                                "--organic-matter-pct, --bulk-density)"}
        top = {"clay_pct": float(tex["clay"]), "sand_pct": float(tex["sand"]),
               "silt_pct": float(tex["silt"]), "organic_matter_pct": args.organic_matter_pct,
               "bulk_density_g_cm3": args.bulk_density}
        sub = None
    else:
        sys.exit("ERROR: give --soil-source hwsd, --soil-texture or --texture-class "
                 "(no default loam is used)")
    clay_pct, sand_pct, silt_pct = top["clay_pct"], top["sand_pct"], top["silt_pct"]

    # Hydraulic properties: HWSD topsoil, plus subsoil only when active layers
    # use it; user values: one set.
    hydraulic_props = compute_hydraulic_properties(clay_pct, sand_pct, top["bulk_density_g_cm3"])
    if args.soil_source == "hwsd":
        hydraulic_props = {"topsoil": hydraulic_props}
        if sub is not None:
            hydraulic_props["subsoil"] = compute_hydraulic_properties(
                sub["clay_pct"], sub["sand_pct"], sub["bulk_density_g_cm3"])

    # Generate soil profile
    soil_profile = generate_soil_profile(top, sub, args.soil_depth,
                                         deep_from_subsoil=args.deep_layers_from_subsoil,
                                         hwsd=(args.soil_source == "hwsd"))

    # Parse PFT distribution
    if args.pft_distribution:
        pft_dist = parse_pft_distribution(args.pft_distribution)
    else:
        pft_dist = DEFAULT_PFT_FRACTIONS

    # Generate surface dataset
    dataset = generate_surface_dataset(
        args.lat, args.lon, soil_profile, pft_dist,
        hydraulic_props, args.output, soil_provenance=provenance)

    # Stage 3: Validate outputs
    warnings = validate_outputs(dataset)
    warnings = list((provenance or {}).get("notes", [])) + warnings

    # Print summary
    summary = {
        # Any warning (substituted HWSD component, failed sanity check) is
        # shown in the status, not hidden under a plain "success".
        "status": "success_with_warnings" if warnings else "success",
        "location": {"lat": args.lat, "lon": args.lon},
        "soil": {
            "clay_pct": clay_pct,
            "sand_pct": sand_pct,
            "silt_pct": silt_pct,
            "depth_m": args.soil_depth,
        },
        "hydraulic": hydraulic_props,
        "soil_provenance": provenance,
        "n_active_pfts": len(pft_dist),
        "output_file": args.output,
        "warnings": warnings,
    }
    print(json.dumps(summary, indent=2))

    if warnings:
        print("\n--- Output Validation Warnings ---", file=sys.stderr)
        for w in warnings:
            print(f"  WARNING: {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
