#!/usr/bin/env python3
"""Convert HWSD or SoilGrids soil data to DNDC .spf soil profile format.

Follows the validate-process-validate pattern:
  1. Validate inputs (database paths, coordinates, data availability)
  2. Process: read soil properties, apply pedotransfer, write .spf
  3. Validate outputs (physical plausibility of profile)

DNDC .spf format:
  Line 1: total_depth(m) num_layers
  Subsequent lines (one per layer):
    layer_num thickness(m) density(g/cm3) SOC(kgC/kg) texture_ID pH
    field_cap(WFPS) wilt_pt(WFPS) porosity(v/v) hydro_cond(m/hr) clay_fraction

DNDC Texture IDs:
  1=Sand, 2=Loamy_sand, 3=Sandy_loam, 4=Silt_loam, 5=Loam,
  6=Sandy_clay_loam, 7=Silty_clay_loam, 8=Clay_loam,
  9=Sandy_clay, 10=Silty_clay, 11=Clay, 12=Organic
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DNDC texture classification
# ---------------------------------------------------------------------------

TEXTURE_NAMES = {
    1: "Sand", 2: "Loamy_sand", 3: "Sandy_loam", 4: "Silt_loam",
    5: "Loam", 6: "Sandy_clay_loam", 7: "Silty_clay_loam",
    8: "Clay_loam", 9: "Sandy_clay", 10: "Silty_clay",
    11: "Clay", 12: "Organic",
}

# Validation bounds
VALID_RANGES = {
    "bulk_density": (0.8, 1.8),    # g/cm3
    "porosity":     (0.3, 0.8),    # v/v
    "pH":           (3.0, 9.0),
    "soc":          (0.0, 0.6),    # kgC/kg
    "clay_frac":    (0.0, 1.0),
    "field_cap":    (0.0, 1.0),    # WFPS
    "wilt_pt":      (0.0, 1.0),    # WFPS
}

# Default 9-layer profile structure to 2 m depth
DEFAULT_LAYER_THICKNESSES = [
    0.05, 0.05, 0.10, 0.10, 0.20, 0.20, 0.30, 0.50, 0.50
]  # sum = 2.0 m

# SOC decay factors by layer (fraction of topsoil SOC retained)
SOC_DECAY_FACTORS = [
    1.00, 0.85, 0.65, 0.50, 0.35, 0.25, 0.15, 0.08, 0.04
]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_inputs(source_path: str, lat: float, lon: float,
                    source_type: str) -> dict:
    """Validate all inputs before processing.

    Returns a dict with validated parameters.

    Raises
    ------
    ValueError  on any invalid parameter
    FileNotFoundError  if source path does not exist
    """
    errors: list[str] = []

    sp = Path(source_path)
    if not sp.exists():
        raise FileNotFoundError(f"Soil data source not found: {source_path}")

    if not (-90.0 <= lat <= 90.0):
        errors.append(f"Latitude {lat} outside [-90, 90]")
    if not (-180.0 <= lon <= 180.0):
        errors.append(f"Longitude {lon} outside [-180, 180]")

    valid_sources = ("hwsd", "soilgrids")
    if source_type.lower() not in valid_sources:
        errors.append(
            f"Unknown source_type '{source_type}'. Must be one of {valid_sources}"
        )

    if errors:
        raise ValueError("Input validation failed:\n  " + "\n  ".join(errors))

    return {
        "source_path": sp,
        "lat": float(lat),
        "lon": float(lon),
        "source_type": source_type.lower(),
    }


# ---------------------------------------------------------------------------
# USDA texture triangle classification
# ---------------------------------------------------------------------------

def classify_texture(sand: float, silt: float, clay: float) -> int:
    """Map sand/silt/clay percentages to DNDC texture ID.

    Parameters are fractions (0-1) or percentages (0-100); auto-detected.
    Returns DNDC texture ID (1-12).
    """
    # Normalise to fractions
    total = sand + silt + clay
    if total > 2.0:  # looks like percentages
        sand, silt, clay = sand / 100.0, silt / 100.0, clay / 100.0

    # USDA texture triangle (simplified decision tree)
    if clay >= 0.40:
        if sand >= 0.45:
            return 9   # Sandy clay
        elif silt >= 0.40:
            return 10  # Silty clay
        else:
            return 11  # Clay
    elif clay >= 0.27:
        if sand >= 0.20 and sand < 0.45:
            return 8   # Clay loam
        elif sand >= 0.45:
            return 6   # Sandy clay loam
        else:
            return 7   # Silty clay loam
    elif clay >= 0.07 and clay < 0.27:
        if silt >= 0.50 and clay >= 0.12:
            return 4   # Silt loam
        elif sand >= 0.52:
            if clay < 0.20 and sand >= 0.70:
                return 3  # Sandy loam
            else:
                return 6  # Sandy clay loam
        else:
            return 5   # Loam
    elif sand >= 0.85:
        if clay < 0.10 and silt < 0.15:
            return 1   # Sand
        else:
            return 2   # Loamy sand
    elif silt >= 0.80:
        return 4  # Silt loam
    elif sand >= 0.70:
        return 3  # Sandy loam
    else:
        return 5  # Loam (default)


# ---------------------------------------------------------------------------
# Pedotransfer functions
# ---------------------------------------------------------------------------

def pedotransfer_field_capacity(clay: float, soc: float) -> float:
    """Estimate field capacity (WFPS) from clay fraction and SOC.

    Based on Saxton & Rawls (2006) simplified.
    clay: fraction (0-1)
    soc: kgC/kg
    """
    om = soc * 1.724  # approximate OM from OC
    fc = 0.2576 + 0.3650 * clay + 0.1142 * om
    return float(np.clip(fc, 0.10, 0.95))


def pedotransfer_wilting_point(clay: float, soc: float) -> float:
    """Estimate wilting point (WFPS) from clay fraction and SOC.

    Based on Saxton & Rawls (2006) simplified.
    """
    om = soc * 1.724
    wp = 0.0260 + 0.5000 * clay + 0.0158 * om
    return float(np.clip(wp, 0.02, 0.80))


def estimate_porosity(bulk_density: float, particle_density: float = 2.65) -> float:
    """Calculate porosity from bulk density and particle density."""
    porosity = 1.0 - (bulk_density / particle_density)
    return float(np.clip(porosity, 0.30, 0.80))


def estimate_hydraulic_conductivity(clay: float, sand: float) -> float:
    """Estimate saturated hydraulic conductivity (m/hr).

    Simplified Kozeny-Carman style estimate.
    """
    # Approximate log-linear relationship
    ksat_cm_hr = 10.0 ** (1.52 - 2.0 * clay + 0.5 * sand)
    ksat_m_hr = ksat_cm_hr / 100.0
    return float(np.clip(ksat_m_hr, 0.0001, 1.0))


# ---------------------------------------------------------------------------
# Source-specific readers
# ---------------------------------------------------------------------------

def _read_hwsd(db_path: Path, lat: float, lon: float) -> dict:
    """Read topsoil properties from HWSD database.

    Tries SQLite HWSD v2 first, falls back to CSV extract.

    Returns dict with keys: sand, silt, clay (fractions),
    bulk_density (g/cm3), soc (kgC/kg), pH.
    """
    props = None

    # Try SQLite (HWSD v2 format)
    sqlite_file = db_path if db_path.suffix == ".db" else db_path / "HWSD2.db"
    if sqlite_file.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(sqlite_file))
            cursor = conn.cursor()

            # Find the SMU (soil mapping unit) for the coordinates
            # HWSD uses a raster lookup; here we query the data table directly
            # assuming an auxiliary spatial index or nearest-point table
            cursor.execute("""
                SELECT T_SAND, T_SILT, T_CLAY, T_BULK_DENSITY,
                       T_OC, T_PH_H2O
                FROM HWSD2_SMU
                ORDER BY ABS(LAT - ?) + ABS(LON - ?)
                LIMIT 1
            """, (lat, lon))
            row = cursor.fetchone()
            conn.close()

            if row:
                sand_pct, silt_pct, clay_pct, bd, oc_pct, ph = row
                props = {
                    "sand": (sand_pct or 40.0) / 100.0,
                    "silt": (silt_pct or 30.0) / 100.0,
                    "clay": (clay_pct or 30.0) / 100.0,
                    "bulk_density": float(bd or 1.35),
                    "soc": (oc_pct or 1.0) / 100.0,  # percent to fraction
                    "pH": float(ph or 6.5),
                }
        except Exception as exc:
            logger.warning("HWSD SQLite read failed: %s", exc)

    # CSV fallback
    if props is None:
        csv_path = db_path if db_path.suffix == ".csv" else db_path / "HWSD_DATA.csv"
        if csv_path.exists():
            props = _read_hwsd_csv(csv_path, lat, lon)

    if props is None:
        raise RuntimeError(
            f"Could not extract soil properties from HWSD at ({lat}, {lon})"
        )

    return props


def _read_hwsd_csv(csv_path: Path, lat: float, lon: float) -> dict:
    """Read HWSD properties from a pre-extracted CSV."""
    import csv
    best = None
    best_dist = float("inf")

    with open(csv_path, "r") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                rlat = float(row.get("LAT", row.get("lat", 0)))
                rlon = float(row.get("LON", row.get("lon", 0)))
                dist = abs(rlat - lat) + abs(rlon - lon)
                if dist < best_dist:
                    best_dist = dist
                    best = row
            except (ValueError, KeyError):
                continue

    if best is None:
        return None

    return {
        "sand": float(best.get("T_SAND", best.get("sand", 40))) / 100.0,
        "silt": float(best.get("T_SILT", best.get("silt", 30))) / 100.0,
        "clay": float(best.get("T_CLAY", best.get("clay", 30))) / 100.0,
        "bulk_density": float(best.get("T_BULK_DENSITY",
                                        best.get("bulk_density", 1.35))),
        "soc": float(best.get("T_OC", best.get("soc", 1.0))) / 100.0,
        "pH": float(best.get("T_PH_H2O", best.get("pH", 6.5))),
    }


def _read_soilgrids(sg_dir: Path, lat: float, lon: float) -> dict:
    """Read soil properties from SoilGrids directory.

    SoilGrids provides layers at 0-5, 5-15, 15-30, 30-60, 60-100, 100-200 cm.
    We use the topsoil (0-30 cm average) for profile generation.
    """
    # Try GeoTIFF files first
    try:
        import rasterio

        def _read_sg_raster(var_name: str) -> float:
            """Read the nearest pixel value from a SoilGrids GeoTIFF."""
            candidates = list(sg_dir.glob(f"*{var_name}*0-5cm*.tif"))
            if not candidates:
                candidates = list(sg_dir.glob(f"*{var_name}*.tif"))
            if not candidates:
                raise FileNotFoundError(f"No SoilGrids raster for {var_name}")

            with rasterio.open(str(candidates[0])) as src:
                row, col = src.index(lon, lat)
                val = src.read(1)[row, col]
            return float(val)

        # SoilGrids units: sand/silt/clay in g/kg, SOC in dg/kg,
        # bulk density in cg/cm3, pH in pH*10
        sand_gkg = _read_sg_raster("sand")
        silt_gkg = _read_sg_raster("silt")
        clay_gkg = _read_sg_raster("clay")
        soc_dgkg = _read_sg_raster("soc")
        bdod_cgcm3 = _read_sg_raster("bdod")
        phh2o_x10 = _read_sg_raster("phh2o")

        return {
            "sand": sand_gkg / 1000.0,
            "silt": silt_gkg / 1000.0,
            "clay": clay_gkg / 1000.0,
            "bulk_density": bdod_cgcm3 / 100.0,
            "soc": soc_dgkg / 10000.0,  # dg/kg -> kgC/kg
            "pH": phh2o_x10 / 10.0,
        }
    except ImportError:
        logger.info("rasterio not available; trying JSON/CSV fallback for SoilGrids")

    # JSON fallback (e.g., from SoilGrids REST API download)
    json_path = sg_dir / "soilgrids_point.json"
    if json_path.exists():
        with open(json_path) as fh:
            data = json.load(fh)
        # Parse SoilGrids API response format
        props = data.get("properties", {}).get("layers", [])
        result = {
            "sand": 0.4, "silt": 0.3, "clay": 0.3,
            "bulk_density": 1.35, "soc": 0.01, "pH": 6.5,
        }
        for layer in props:
            name = layer.get("name", "")
            # Use the 0-5cm depth value
            depths = layer.get("depths", [])
            val = None
            for d in depths:
                if "0-5" in d.get("label", ""):
                    val = d.get("values", {}).get("mean")
                    break
            if val is None and depths:
                val = depths[0].get("values", {}).get("mean")
            if val is None:
                continue
            val = float(val)
            if "sand" in name:
                result["sand"] = val / 1000.0
            elif "silt" in name:
                result["silt"] = val / 1000.0
            elif "clay" in name:
                result["clay"] = val / 1000.0
            elif "soc" in name:
                result["soc"] = val / 10000.0
            elif "bdod" in name:
                result["bulk_density"] = val / 100.0
            elif "phh2o" in name:
                result["pH"] = val / 10.0
        return result

    raise RuntimeError(
        f"Could not extract soil properties from SoilGrids at ({lat}, {lon})"
    )


# ---------------------------------------------------------------------------
# Profile generation
# ---------------------------------------------------------------------------

def build_profile(topsoil: dict, num_layers: int = 9) -> list[dict]:
    """Build a DNDC soil profile from topsoil properties.

    Generates ``num_layers`` layers with SOC decreasing with depth.

    Parameters
    ----------
    topsoil : dict
        Keys: sand, silt, clay (fractions), bulk_density, soc, pH
    num_layers : int
        Number of soil layers (default 9 -> 2m depth)

    Returns
    -------
    list[dict]
        One dict per layer with all required .spf fields.
    """
    thicknesses = DEFAULT_LAYER_THICKNESSES[:num_layers]
    soc_factors = SOC_DECAY_FACTORS[:num_layers]

    sand = topsoil["sand"]
    silt = topsoil["silt"]
    clay = topsoil["clay"]
    bd_top = topsoil["bulk_density"]
    soc_top = topsoil["soc"]
    ph = topsoil["pH"]

    texture_id = classify_texture(sand, silt, clay)

    layers: list[dict] = []
    for i in range(num_layers):
        soc_i = soc_top * soc_factors[i]
        # Bulk density increases slightly with depth
        bd_i = min(bd_top + 0.02 * i, 1.80)
        porosity_i = estimate_porosity(bd_i)
        fc_i = pedotransfer_field_capacity(clay, soc_i)
        wp_i = pedotransfer_wilting_point(clay, soc_i)
        ksat_i = estimate_hydraulic_conductivity(clay, sand)

        layers.append({
            "layer_num": i + 1,
            "thickness": thicknesses[i],
            "density": round(bd_i, 3),
            "soc": round(soc_i, 6),
            "texture_id": texture_id,
            "pH": round(ph, 2),
            "field_cap": round(fc_i, 4),
            "wilt_pt": round(wp_i, 4),
            "porosity": round(porosity_i, 4),
            "hydro_cond": round(ksat_i, 6),
            "clay_fraction": round(clay, 4),
        })

    return layers


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_profile(layers: list[dict]) -> list[str]:
    """Validate a soil profile against physical plausibility bounds.

    Returns list of warning strings (empty if all OK).
    """
    warnings: list[str] = []

    for layer in layers:
        ln = layer["layer_num"]
        for key, (lo, hi) in VALID_RANGES.items():
            val = layer.get(key)
            if val is not None and not (lo <= val <= hi):
                warnings.append(
                    f"Layer {ln}: {key} = {val} outside [{lo}, {hi}]"
                )

        # Field capacity must exceed wilting point
        if layer["field_cap"] <= layer["wilt_pt"]:
            warnings.append(
                f"Layer {ln}: field_cap ({layer['field_cap']}) <= "
                f"wilt_pt ({layer['wilt_pt']})"
            )

        # Porosity must be >= field capacity
        if layer["porosity"] < layer["field_cap"]:
            warnings.append(
                f"Layer {ln}: porosity ({layer['porosity']}) < "
                f"field_cap ({layer['field_cap']})"
            )

    total_depth = sum(l["thickness"] for l in layers)
    if abs(total_depth - 2.0) > 0.01:
        warnings.append(
            f"Total profile depth {total_depth:.3f} m differs from expected 2.0 m"
        )

    return warnings


def validate_output_file(filepath: Path) -> list[str]:
    """Re-read and validate a written .spf file.

    Returns list of issues found.
    """
    issues: list[str] = []
    if not filepath.exists():
        issues.append(f"Output file does not exist: {filepath}")
        return issues

    with open(filepath, "r") as fh:
        lines = fh.readlines()

    if len(lines) < 2:
        issues.append("SPF file has fewer than 2 lines")
        return issues

    # Parse header
    header = lines[0].strip().split()
    if len(header) != 2:
        issues.append(f"Header line should have 2 fields, got {len(header)}")
        return issues

    try:
        total_depth = float(header[0])
        num_layers = int(header[1])
    except ValueError as exc:
        issues.append(f"Cannot parse header: {exc}")
        return issues

    if num_layers != len(lines) - 1:
        issues.append(
            f"Header says {num_layers} layers but file has {len(lines) - 1} data lines"
        )

    # Validate each layer line
    for i, line in enumerate(lines[1:], 1):
        parts = line.strip().split()
        if len(parts) != 11:
            issues.append(f"Layer line {i}: expected 11 fields, got {len(parts)}")
            continue
        try:
            bd = float(parts[2])
            porosity = float(parts[8])
            ph = float(parts[5])
            if not (0.8 <= bd <= 1.8):
                issues.append(f"Layer {i}: bulk_density {bd} outside [0.8, 1.8]")
            if not (0.3 <= porosity <= 0.8):
                issues.append(f"Layer {i}: porosity {porosity} outside [0.3, 0.8]")
            if not (3.0 <= ph <= 9.0):
                issues.append(f"Layer {i}: pH {ph} outside [3.0, 9.0]")
        except (ValueError, IndexError) as exc:
            issues.append(f"Layer {i}: parse error: {exc}")

    return issues


# ---------------------------------------------------------------------------
# SPF file writer
# ---------------------------------------------------------------------------

def write_spf(layers: list[dict], output_path: Path) -> None:
    """Write a DNDC .spf soil profile file."""
    total_depth = sum(l["thickness"] for l in layers)
    num_layers = len(layers)

    with open(output_path, "w") as fh:
        fh.write(f"{total_depth:.2f} {num_layers}\n")
        for layer in layers:
            fh.write(
                f"{layer['layer_num']:d} "
                f"{layer['thickness']:.2f} "
                f"{layer['density']:.3f} "
                f"{layer['soc']:.6f} "
                f"{layer['texture_id']:d} "
                f"{layer['pH']:.2f} "
                f"{layer['field_cap']:.4f} "
                f"{layer['wilt_pt']:.4f} "
                f"{layer['porosity']:.4f} "
                f"{layer['hydro_cond']:.6f} "
                f"{layer['clay_fraction']:.4f}\n"
            )


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process(source_path: str, lat: float, lon: float,
            source_type: str, output_file: str,
            num_layers: int = 9) -> str:
    """End-to-end: validate inputs -> convert -> validate outputs.

    Parameters
    ----------
    source_path : str
        Path to HWSD database / SoilGrids directory.
    lat, lon : float
        Target coordinates.
    source_type : str
        'hwsd' or 'soilgrids'.
    output_file : str
        Output .spf file path.
    num_layers : int
        Number of soil layers (default 9).

    Returns
    -------
    str
        Path to created .spf file.
    """
    # --- Phase 1: Validate inputs ---
    params = validate_inputs(source_path, lat, lon, source_type)
    logger.info("Input validation passed. Source: %s", source_type)

    # --- Phase 2: Process ---
    if params["source_type"] == "hwsd":
        topsoil = _read_hwsd(params["source_path"], params["lat"], params["lon"])
    else:
        topsoil = _read_soilgrids(params["source_path"], params["lat"], params["lon"])

    logger.info("Topsoil properties: %s", topsoil)

    layers = build_profile(topsoil, num_layers)

    # Pre-write validation
    pre_warnings = validate_profile(layers)
    if pre_warnings:
        logger.warning("Profile validation warnings (pre-write):")
        for w in pre_warnings:
            logger.warning("  %s", w)

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_spf(layers, out_path)
    logger.info("Wrote soil profile to %s (%d layers)", out_path, len(layers))

    # --- Phase 3: Validate output ---
    post_issues = validate_output_file(out_path)
    if post_issues:
        logger.warning("Output file validation issues:")
        for issue in post_issues:
            logger.warning("  %s", issue)
    else:
        logger.info("Output file validation passed.")

    return str(out_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Convert HWSD / SoilGrids soil data to DNDC .spf format."
    )
    parser.add_argument("--source-path", required=True,
                        help="Path to HWSD database or SoilGrids directory")
    parser.add_argument("--lat", type=float, required=True,
                        help="Latitude of target site")
    parser.add_argument("--lon", type=float, required=True,
                        help="Longitude of target site")
    parser.add_argument("--source-type", required=True,
                        choices=["hwsd", "soilgrids"],
                        help="Soil data source")
    parser.add_argument("--output", required=True,
                        help="Output .spf file path")
    parser.add_argument("--num-layers", type=int, default=9,
                        help="Number of soil layers (default 9)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        result = process(
            source_path=args.source_path,
            lat=args.lat,
            lon=args.lon,
            source_type=args.source_type,
            output_file=args.output,
            num_layers=args.num_layers,
        )
        print(f"Created soil profile: {result}")
    except Exception:
        logger.exception("Fatal error during soil conversion")
        sys.exit(1)


if __name__ == "__main__":
    main()
