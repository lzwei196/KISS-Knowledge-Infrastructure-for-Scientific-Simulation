#!/usr/bin/env python3
"""
hwsd_soil_adapter.py
====================
Retrieve soil properties from HWSD (Harmonized World Soil Database) for RZWQM2.

Reads the HWSD China raster (.img) to get MU_GLOBAL soil type code, then looks
up soil properties (sand, silt, clay, bulk density, organic carbon, pH, CEC)
from the HWSD.mdb Access database via mdb-tools.

Returns a normalized horizon list compatible with the RZWQM2 soil pipeline.
HWSD provides two layers: topsoil (0-30cm) and subsoil (30-100cm). The adapter
expands these into 6 horizons at standard depths for RZWQM2.

Requirements:
    - mdb-tools installed (apt install mdbtools)
    - rasterio

Inputs:
    lat             - Latitude in decimal degrees
    lon             - Longitude in decimal degrees
    hwsd_raster     - Path to HWSD_China_Geo.img
    hwsd_mdb        - Path to HWSD.mdb
    num_horizons    - Target horizons (default 6)

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""
import sys
import os
import json
import subprocess
import csv
import io

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
LAT = ""
LON = ""
HWSD_RASTER = "KISSPATH_STATIC/HWSD_China_Geo.img"
HWSD_MDB = "KISSPATH_FORCING/huaihe_raw/soil/HWSD.mdb"
NUM_HORIZONS = "6"

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))

# USDA texture class mapping (from HWSD D_USDA_TEX_CLASS table)
# Must match soil_default_setter() keys in rzwqm_file.py exactly
USDA_TEX = {
    1: "clay", 2: "silty clay", 3: "clay", 4: "silty clay loam ",
    5: "clay loam", 6: "silt", 7: "siltyloam", 8: "sandy clay",
    9: "loam", 10: "sandy clay loam", 11: "sandy loam", 12: "loamy sand", 13: "sand"
}


def _get_mu_global(lat, lon, raster_path):
    """Read MU_GLOBAL soil type code from HWSD raster at given lat/lon."""
    import rasterio
    import numpy as np

    with rasterio.open(raster_path) as src:
        row, col = src.index(lon, lat)
        val = int(src.read(1)[row, col])

    if val == 0:
        return None, "HWSD raster returned 0 (nodata/water) at this location."
    return val, None


def _lookup_hwsd(mu_global, mdb_path):
    """Look up soil properties from HWSD.mdb for a given MU_GLOBAL code."""
    result = subprocess.run(
        ['mdb-export', mdb_path, 'HWSD_DATA'],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        return None, f"mdb-export failed: {result.stderr}"

    reader = csv.DictReader(io.StringIO(result.stdout))

    # Find the dominant component (highest SHARE, lowest SEQ) for this MU
    best = None
    best_share = 0
    for row in reader:
        if row['MU_GLOBAL'] == str(mu_global):
            share = int(row.get('SHARE', 0) or 0)
            if share > best_share and row.get('T_SAND'):
                best = row
                best_share = share

    if best is None:
        # Try nearby MU codes (within ±10)
        result2 = subprocess.run(
            ['mdb-export', mdb_path, 'HWSD_DATA'],
            capture_output=True, text=True, timeout=60
        )
        reader2 = csv.DictReader(io.StringIO(result2.stdout))
        for row in reader2:
            try:
                mu = int(row['MU_GLOBAL'])
                if abs(mu - mu_global) <= 10 and row.get('T_SAND') and row['T_SAND']:
                    share = int(row.get('SHARE', 0) or 0)
                    if share > best_share:
                        best = row
                        best_share = share
            except (ValueError, KeyError):
                continue

    if best is None:
        return None, f"No soil data found for MU_GLOBAL={mu_global} (or nearby codes)."

    def _safe_float(val, default=0.0):
        try:
            return float(val) if val else default
        except (ValueError, TypeError):
            return default

    def _safe_int(val, default=9):
        try:
            return int(val) if val else default
        except (ValueError, TypeError):
            return default

    topsoil = {
        'sand_pct': _safe_float(best.get('T_SAND')),
        'silt_pct': _safe_float(best.get('T_SILT')),
        'clay_pct': _safe_float(best.get('T_CLAY')),
        'usda_tex_class': _safe_int(best.get('T_USDA_TEX_CLASS')),
        'bulk_density_gcc': _safe_float(best.get('T_REF_BULK_DENSITY'), 1.4),
        'organic_carbon_pct': _safe_float(best.get('T_OC')),
        'ph': _safe_float(best.get('T_PH_H2O'), 6.5),
        'cec_soil': _safe_float(best.get('T_CEC_SOIL')),
    }
    subsoil = {
        'sand_pct': _safe_float(best.get('S_SAND')),
        'silt_pct': _safe_float(best.get('S_SILT')),
        'clay_pct': _safe_float(best.get('S_CLAY')),
        'usda_tex_class': _safe_int(best.get('S_USDA_TEX_CLASS')),
        'bulk_density_gcc': _safe_float(best.get('S_REF_BULK_DENSITY'), 1.4),
        'organic_carbon_pct': _safe_float(best.get('S_OC')),
        'ph': _safe_float(best.get('S_PH_H2O'), 6.5),
        'cec_soil': _safe_float(best.get('S_CEC_SOIL')),
    }

    return {'topsoil': topsoil, 'subsoil': subsoil, 'mu_global': int(best['MU_GLOBAL'])}, None


def _build_horizons(hwsd_data, num_horizons):
    """Expand HWSD 2-layer data into N horizons with hydraulic properties."""
    from rzwqm_file import soil_default_setter, fc10_estimate, N2_estimate, C2_estimate

    topsoil = hwsd_data['topsoil']
    subsoil = hwsd_data['subsoil']

    # Standard depths: topsoil to 30cm, subsoil to 200cm
    if num_horizons == 6:
        layers = [
            (5, topsoil), (15, topsoil), (30, topsoil),
            (60, subsoil), (100, subsoil), (200, subsoil),
        ]
    elif num_horizons == 4:
        layers = [
            (15, topsoil), (30, topsoil),
            (60, subsoil), (200, subsoil),
        ]
    else:
        # Generic split
        layers = [(30, topsoil), (200, subsoil)]
        while len(layers) < num_horizons:
            # Subdivide deepest layer
            d = layers[-1][0]
            mid = layers[-2][0] + (d - layers[-2][0]) // 2
            layers.insert(-1, (mid, layers[-1][1]))

    horizons = []
    for depth_cm, soil_data in layers:
        tex_class = USDA_TEX.get(soil_data['usda_tex_class'], 'loam')
        defaults = soil_default_setter(tex_class)
        if not defaults:
            defaults = soil_default_setter('loam')

        bd = soil_data['bulk_density_gcc']
        ws = round(1.0 - bd / 2.65, 4)
        ws = max(0.30, min(0.65, ws))

        # Use texture defaults for hydraulic params
        wr = defaults['wr']
        fc33 = defaults['fc33']
        fc15 = defaults['fc15']
        ksat = defaults['ksat']
        psd = defaults['pore_size_dist']
        bp = defaults['bubbling_pressure']
        fc10 = fc10_estimate(ws, wr, bp, psd)
        N2 = N2_estimate(psd)
        C2 = C2_estimate(bp, psd, ksat, 0)

        horizons.append({
            'depth_cm': depth_cm,
            'sand_pct': soil_data['sand_pct'],
            'silt_pct': soil_data['silt_pct'],
            'clay_pct': soil_data['clay_pct'],
            'bulk_density_gcc': bd,
            'organic_carbon_pct': soil_data['organic_carbon_pct'],
            'texture_class': tex_class,
            'ws': ws,
            'wr': wr,
            'fc33': fc33,
            'fc15': fc15,
            'fc10': round(fc10, 4),
            'ksat_cm_hr': ksat,
            'pore_size_dist': psd,
            'bubbling_pressure': bp,
            'N2': round(N2, 2),
            'C2': round(C2, 4),
        })

    return horizons


def main():
    lat_raw = sys.argv[1] if len(sys.argv) > 1 else LAT
    lon_raw = sys.argv[2] if len(sys.argv) > 2 else LON
    raster_path = sys.argv[3] if len(sys.argv) > 3 else HWSD_RASTER
    mdb_path = sys.argv[4] if len(sys.argv) > 4 else HWSD_MDB
    num_horizons_raw = sys.argv[5] if len(sys.argv) > 5 else NUM_HORIZONS

    # Validate
    errors = []
    try:
        lat = float(lat_raw)
    except (ValueError, TypeError):
        errors.append(f"LAT must be numeric: {lat_raw}")
        lat = None
    try:
        lon = float(lon_raw)
    except (ValueError, TypeError):
        errors.append(f"LON must be numeric: {lon_raw}")
        lon = None
    try:
        num_horizons = int(num_horizons_raw)
    except (ValueError, TypeError):
        num_horizons = 6

    if not os.path.isfile(raster_path):
        errors.append(f"HWSD raster not found: {raster_path}")
    if not os.path.isfile(mdb_path):
        errors.append(f"HWSD.mdb not found: {mdb_path}")

    if errors:
        print(json.dumps({"status": "INPUT_ERROR", "message": "; ".join(errors)}))
        sys.exit(1)

    # Step 1: Get MU_GLOBAL from raster
    try:
        mu_global, err = _get_mu_global(lat, lon, raster_path)
        if err:
            print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
            sys.exit(2)
    except Exception as e:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": f"Raster read error: {e}"}))
        sys.exit(2)

    # Step 2: Lookup soil properties from MDB
    try:
        hwsd_data, err = _lookup_hwsd(mu_global, mdb_path)
        if err:
            print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
            sys.exit(2)
    except Exception as e:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": f"MDB lookup error: {e}"}))
        sys.exit(2)

    # Step 3: Build horizons
    try:
        horizons = _build_horizons(hwsd_data, num_horizons)
    except Exception as e:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": f"Horizon build error: {e}"}))
        sys.exit(2)

    # Output
    result = {
        'source': 'hwsd',
        'lat': lat,
        'lon': lon,
        'mu_global': mu_global,
        'topsoil': hwsd_data['topsoil'],
        'subsoil': hwsd_data['subsoil'],
        'horizons': horizons,
    }

    print(json.dumps({
        "status": "SUCCESS",
        "result": result,
        "message": (
            f"Retrieved soil from HWSD (MU_GLOBAL={mu_global}) at ({lat}, {lon}). "
            f"Topsoil: {hwsd_data['topsoil']['texture_class'] if 'texture_class' in hwsd_data['topsoil'] else USDA_TEX.get(hwsd_data['topsoil']['usda_tex_class'], 'unknown')}, "
            f"sand={hwsd_data['topsoil']['sand_pct']}%, clay={hwsd_data['topsoil']['clay_pct']}%. "
            f"{len(horizons)} horizons generated."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
