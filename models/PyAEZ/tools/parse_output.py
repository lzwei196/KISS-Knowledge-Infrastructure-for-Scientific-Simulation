#!/usr/bin/env python3
"""
Parse PyAEZ GeoTIFF/NumPy outputs and extract results to CSV summary tables.

Reads the output rasters from each module (NB1–NB6) and generates:
  1. A per-pixel CSV with all constraint factors and yields
  2. A summary statistics CSV with zonal means
  3. A suitability classification summary

Usage:
    python parse_output.py --output-dir ./data_output --crop-name maize \
        --mask-file ./data_input/LAO_Admin.tif --csv-out ./results
"""

import argparse
import os
import sys
import csv
import json
import numpy as np
from pathlib import Path


def validate_inputs(config: dict) -> list:
    """Validate that output directory has expected structure."""
    errors = []
    output_dir = Path(config["output_dir"])

    if not output_dir.exists():
        errors.append(f"Output directory not found: {output_dir}")
        return errors

    expected_dirs = ["NB1", "NB2", "NB3", "NB4", "NB5", "NB6"]
    for d in expected_dirs:
        dpath = output_dir / d
        if not dpath.exists():
            errors.append(f"Missing module output: {d}/")

    return errors


def load_raster(filepath: str) -> np.ndarray:
    """Load a GeoTIFF or NumPy file as array."""
    if filepath.endswith(".npy"):
        return np.load(filepath)
    elif filepath.endswith((".tif", ".tiff")):
        try:
            from osgeo import gdal
            ds = gdal.Open(filepath)
            if ds is None:
                raise RuntimeError(f"Cannot open: {filepath}")
            arr = ds.ReadAsArray()
            ds = None
            return arr
        except ImportError:
            raise ImportError("GDAL required to read GeoTIFF files")
    else:
        raise ValueError(f"Unknown file format: {filepath}")


def find_output_files(output_dir: Path, crop_name: str) -> dict:
    """Locate all output files across NB1–NB6 directories."""
    files = {}

    # NB1 outputs
    nb1 = output_dir / "NB1"
    if nb1.exists():
        for f in nb1.glob("*.tif"):
            key = f"m1_{f.stem}"
            files[key] = str(f)
        for f in nb1.glob("*.npy"):
            key = f"m1_{f.stem}"
            files[key] = str(f)

    # NB2–NB6 outputs
    for nb_num in range(2, 7):
        nb_dir = output_dir / f"NB{nb_num}"
        if not nb_dir.exists():
            continue
        for f in nb_dir.glob(f"*{crop_name}*"):
            key = f"m{nb_num}_{f.stem}"
            files[key] = str(f)
        for f in nb_dir.glob("*.tif"):
            if crop_name not in f.stem:
                key = f"m{nb_num}_{f.stem}"
                files[key] = str(f)

    return files


def extract_pixel_table(output_dir: Path, crop_name: str,
                         mask: np.ndarray = None) -> list:
    """
    Extract per-pixel values for yield and all constraint factors.

    Returns list of dicts, one per valid pixel:
      row, col, yield_rain, yield_irr, fc1_rain, fc2_rain, fc3_rain,
      fc4_rain, fc5_rain, lgp, thermal_zone, ...
    """
    files = find_output_files(output_dir, crop_name)

    # Load key arrays
    arrays = {}
    for key, fpath in files.items():
        try:
            arrays[key] = load_raster(fpath)
        except Exception as e:
            print(f"  Warning: could not load {key}: {e}")

    if not arrays:
        return []

    # Get reference shape from first 2D array
    ref_shape = None
    for arr in arrays.values():
        if isinstance(arr, np.ndarray) and arr.ndim == 2:
            ref_shape = arr.shape
            break

    if ref_shape is None:
        print("  No 2D arrays found")
        return []

    rows = []
    ny, nx = ref_shape
    for i in range(ny):
        for j in range(nx):
            if mask is not None and mask[i, j] == 0:
                continue

            pixel = {"row": i, "col": j}
            for key, arr in arrays.items():
                if isinstance(arr, np.ndarray) and arr.ndim == 2:
                    if arr.shape == ref_shape:
                        val = arr[i, j]
                        pixel[key] = float(val) if not np.isnan(val) else None

            rows.append(pixel)

    return rows


def compute_summary_stats(pixel_table: list) -> dict:
    """Compute zonal summary statistics from pixel table."""
    if not pixel_table:
        return {}

    # Collect all numeric keys
    numeric_keys = set()
    for px in pixel_table:
        for k, v in px.items():
            if k not in ("row", "col") and v is not None:
                numeric_keys.add(k)

    stats = {}
    for key in sorted(numeric_keys):
        values = [px[key] for px in pixel_table if px.get(key) is not None]
        if not values:
            continue
        arr = np.array(values)
        stats[key] = {
            "count": len(values),
            "mean": round(float(np.mean(arr)), 2),
            "std": round(float(np.std(arr)), 2),
            "min": round(float(np.min(arr)), 2),
            "max": round(float(np.max(arr)), 2),
            "median": round(float(np.median(arr)), 2),
            "p10": round(float(np.percentile(arr, 10)), 2),
            "p90": round(float(np.percentile(arr, 90)), 2),
        }

    return stats


def classify_suitability(pixel_table: list, yield_key: str) -> dict:
    """
    Classify pixels into FAO suitability classes based on yield.

    Classes (fraction of maximum yield):
      VS (Very Suitable): >80%
      S (Suitable): 60-80%
      MS (Moderately Suitable): 40-60%
      mS (Marginally Suitable): 20-40%
      NS (Not Suitable): <20%
      N (Not Suitable - zero): 0
    """
    values = [px.get(yield_key) for px in pixel_table if px.get(yield_key) is not None]
    if not values:
        return {}

    arr = np.array(values)
    max_yield = np.max(arr[arr > 0]) if np.any(arr > 0) else 1.0

    counts = {"VS": 0, "S": 0, "MS": 0, "mS": 0, "NS": 0, "N": 0}
    for v in values:
        if v <= 0:
            counts["N"] += 1
        else:
            frac = v / max_yield
            if frac > 0.8:
                counts["VS"] += 1
            elif frac > 0.6:
                counts["S"] += 1
            elif frac > 0.4:
                counts["MS"] += 1
            elif frac > 0.2:
                counts["mS"] += 1
            else:
                counts["NS"] += 1

    total = len(values)
    pcts = {k: round(100 * v / total, 1) for k, v in counts.items()}

    return {"counts": counts, "percentages": pcts, "total_pixels": total,
            "max_yield": round(float(max_yield), 1)}


def write_csv(pixel_table: list, output_path: str):
    """Write pixel table to CSV."""
    if not pixel_table:
        print("  No data to write")
        return

    keys = list(pixel_table[0].keys())
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(pixel_table)

    print(f"  Written {len(pixel_table)} rows to {output_path}")


def validate_outputs(csv_dir: str) -> list:
    """Validate that output CSVs were created."""
    errors = []
    csv_path = Path(csv_dir)

    expected = ["pixel_values.csv", "summary_stats.json", "suitability.json"]
    for f in expected:
        if not (csv_path / f).exists():
            errors.append(f"Missing output: {f}")

    # Check pixel CSV has data
    px_csv = csv_path / "pixel_values.csv"
    if px_csv.exists():
        with open(str(px_csv)) as f:
            reader = csv.reader(f)
            n_rows = sum(1 for _ in reader) - 1  # minus header
            if n_rows == 0:
                errors.append("pixel_values.csv has no data rows")

    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(f"  ✗ {e}")
    else:
        print("All output files validated successfully")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Parse PyAEZ outputs to CSV")
    parser.add_argument("--output-dir", required=True, help="PyAEZ output directory")
    parser.add_argument("--crop-name", required=True, help="Crop name")
    parser.add_argument("--mask-file", default=None, help="Study area mask GeoTIFF")
    parser.add_argument("--csv-out", required=True, help="Output CSV directory")
    args = parser.parse_args()

    csv_dir = Path(args.csv_out)
    csv_dir.mkdir(parents=True, exist_ok=True)

    # Load mask if provided
    mask = None
    if args.mask_file and os.path.exists(args.mask_file):
        mask = load_raster(args.mask_file)
        print(f"Loaded mask: {mask.shape}, {np.sum(mask > 0)} valid pixels")

    # Pre-validation
    errors = validate_inputs(vars(args))
    if errors:
        for e in errors:
            print(f"WARNING: {e}")

    # Extract pixel table
    print("\nExtracting pixel values...")
    output_dir = Path(args.output_dir)
    pixel_table = extract_pixel_table(output_dir, args.crop_name, mask)
    print(f"  Extracted {len(pixel_table)} pixels")

    # Write CSV
    write_csv(pixel_table, str(csv_dir / "pixel_values.csv"))

    # Summary statistics
    print("\nComputing summary statistics...")
    stats = compute_summary_stats(pixel_table)
    with open(str(csv_dir / "summary_stats.json"), "w") as f:
        json.dump(stats, f, indent=2)
    print(f"  Computed stats for {len(stats)} variables")

    # Suitability classification
    print("\nClassifying suitability...")
    suitability = {}
    for condition in ["rain", "irr"]:
        for prefix in ["m2", "m5"]:
            key = f"{prefix}_{args.crop_name}_yield_{condition}"
            if any(key in px for px in pixel_table[:1]):
                suit = classify_suitability(pixel_table, key)
                if suit:
                    suitability[f"yield_{condition}_{prefix}"] = suit

    with open(str(csv_dir / "suitability.json"), "w") as f:
        json.dump(suitability, f, indent=2)
    print(f"  Classified {len(suitability)} yield maps")

    # Post-validation
    val_errors = validate_outputs(str(csv_dir))
    if val_errors:
        sys.exit(1)

    print("\nParsing complete.")


if __name__ == "__main__":
    main()
