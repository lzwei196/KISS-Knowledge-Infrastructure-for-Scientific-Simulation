#!/usr/bin/env python3
"""
soil_source_adapter.py
======================
Pluggable multi-backend soil data retrieval for RZWQM2.

Given a lat/lon coordinate and a source identifier, retrieves soil profile
data and returns a normalized JSON schema that any downstream RZWQM2 tool
can consume directly.

Supported sources:
    - vic_global:        VIC 0.25-degree global soil parameters (global_soil_param_new.txt)
    - soilgrids:         ISRIC SoilGrids REST API (global 250m)
    - gssurgo:           US gSSURGO geodatabase (US coverage)
    - canada_shapefile:  Canadian soil database shapefiles
    - hwsd:              Harmonized World Soil Database raster (China)

Brooks-Corey hydraulic parameter estimation follows the original RZWQM2
pedotransfer logic (rzwqm_file.py:2580-2646) with two modes:
    Mode 1 (measured): When KP33, KP1500, KP0, KSAT are available from
        the data source, derive pore_size_dist and bubbling_pressure from
        the actual water retention curve. This is the preferred mode.
    Mode 2 (texture defaults): When only texture (sand/clay %) is available,
        use the soil_default_setter lookup table for all parameters.

Inputs:
    lat             - Latitude in decimal degrees
    lon             - Longitude in decimal degrees
    source          - Source identifier (see above)
    source_path     - Path to local data file/directory
    num_horizons    - Target number of soil horizons (default 5)
    state_code      - US state code (for gssurgo source)

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import json
import math

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
LAT = ""                # Latitude in decimal degrees
LON = ""                # Longitude in decimal degrees
SOURCE = "soilgrids"    # Source identifier (prefer atlas data over model-derived)
SOURCE_PATH = ""        # Path to local soil data
NUM_HORIZONS = "5"      # Target number of horizons
STATE_CODE = ""         # US state abbreviation (for gssurgo)

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))

VALID_SOURCES = ['vic_global', 'soilgrids', 'gssurgo', 'canada_shapefile', 'hwsd']

# Default horizon depths (cm) when source provides fewer layers
DEFAULT_HORIZON_DEPTHS = [10, 30, 60, 100, 200]


def validate_inputs(lat_raw, lon_raw, source, source_path, num_horizons_raw, state_code):
    """Validate inputs."""
    errors = []

    lat = lon = None
    try:
        lat = float(lat_raw) if lat_raw else None
        if lat is None: errors.append("LAT is required.")
    except ValueError:
        errors.append(f"LAT must be numeric: {lat_raw}")
    try:
        lon = float(lon_raw) if lon_raw else None
        if lon is None: errors.append("LON is required.")
    except ValueError:
        errors.append(f"LON must be numeric: {lon_raw}")

    source = source.strip().lower() if source else 'vic_global'
    if source not in VALID_SOURCES:
        errors.append(f"SOURCE must be one of {VALID_SOURCES}")

    num_horizons = 5
    try:
        num_horizons = int(num_horizons_raw) if num_horizons_raw else 5
    except ValueError:
        errors.append(f"NUM_HORIZONS must be integer: {num_horizons_raw}")

    if source == 'gssurgo' and not state_code:
        errors.append("STATE_CODE is required for gssurgo source.")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'lat': lat, 'lon': lon, 'source': source,
        'source_path': source_path, 'num_horizons': num_horizons,
        'state_code': state_code.upper() if state_code else None,
    }


def _get_texture_class(sand_pct, clay_pct):
    """Get USDA texture class from sand/clay percentages (0-100 scale)."""
    try:
        from rzwqm_file import soil_texture_setter
        # soil_texture_setter expects raw percentages (0-100), NOT fractions
        return soil_texture_setter(sand_pct, clay_pct)
    except ImportError:
        # Fallback simplified classification
        silt_pct = 100 - sand_pct - clay_pct
        if clay_pct >= 40:
            return 'clay'
        elif sand_pct >= 85:
            return 'sand'
        elif silt_pct >= 80:
            return 'silt'
        else:
            return 'loam'


def _fill_hydraulic_params(horizon):
    """
    Fill missing hydraulic params using Brooks-Corey pedotransfer functions.

    Two modes (matching rzwqm_scenario_mass_generation logic):

    Mode 1 — MEASURED DATA AVAILABLE:
        When measured KP33, KP1500, KP0, and/or KSAT are provided in the
        horizon dict, use them to derive pore_size_dist and bubbling_pressure
        from the actual water retention curve. Falls back to texture defaults
        only for individual missing values.

    Mode 2 — TEXTURE DEFAULTS ONLY:
        When no measured water retention data is available, use the texture
        class lookup table (soil_default_setter) for all parameters.

    Input horizon dict may contain (all optional — missing triggers estimation):
        ksat_cm_hr:   Measured saturated hydraulic conductivity (cm/hr)
        ws:           Measured saturated water content (= KP0, volumetric)
        fc33:         Measured field capacity at 1/3 bar (= KP33, volumetric)
        fc10:         Measured water content at 1/10 bar (= KP10, volumetric)
        fc15:         Measured wilting point at 15 bar (= KP1500, volumetric)
        texture_class: USDA texture class string
    """
    try:
        from rzwqm_file import (soil_default_setter, pore_size_distribution_estimate,
                                 B_estimate, bubbling_pressure_estimate,
                                 N2_estimate, C2_estimate, fc10_estimate)
    except ImportError:
        return horizon  # Can't fill without pedotransfer functions

    texture = horizon.get('texture_class', 'loam')
    defaults = soil_default_setter(texture)

    if not defaults:
        return horizon

    # Determine whether we have measured water retention data
    has_fc33 = horizon.get('fc33') is not None and horizon['fc33'] > 0
    has_fc15 = horizon.get('fc15') is not None and horizon['fc15'] > 0
    has_ws = horizon.get('ws') is not None and horizon['ws'] > 0
    has_ksat = horizon.get('ksat_cm_hr') is not None and horizon['ksat_cm_hr'] > 0
    has_measured = has_fc33 or has_fc15 or has_ws or has_ksat

    # Always need wr from texture defaults (not typically measured)
    wr = defaults.get('wr', 0.05)
    horizon['wr'] = wr

    if has_measured:
        # --- MODE 1: Use measured values, fill gaps from defaults ---
        ws = horizon['ws'] if has_ws else defaults['ws']
        fc33 = horizon['fc33'] if has_fc33 else defaults['fc33']
        fc15 = horizon['fc15'] if has_fc15 else defaults['fc15']
        ksat = horizon['ksat_cm_hr'] if has_ksat else defaults['ksat']

        # Pore size distribution: estimate from measured fc33 & fc15
        if has_fc33 and has_fc15:
            try:
                psd = pore_size_distribution_estimate(fc33, fc15, wr)
            except Exception:
                psd = defaults.get('pore_size_dist', 0.5)
        else:
            psd = defaults.get('pore_size_dist', 0.5)

        # Bubbling pressure: estimate from measured ws (KP0) & fc33
        if has_ws and has_fc33:
            try:
                B = B_estimate(fc33, wr, psd)
                bp = bubbling_pressure_estimate(ws, psd, wr, B)
            except Exception:
                bp = defaults.get('bubbling_pressure', 20.0)
        else:
            try:
                B = B_estimate(defaults['fc33'], wr, psd)
                bp = defaults.get('bubbling_pressure', 20.0)
            except Exception:
                bp = defaults.get('bubbling_pressure', 20.0)

        # C2: estimate using measured ksat if available
        try:
            C2 = C2_estimate(bp, psd, ksat, 0)
        except Exception:
            C2 = 0.0

        # fc10: estimate if not measured
        fc10 = horizon.get('fc10')
        if not fc10 or fc10 <= 0:
            try:
                fc10 = fc10_estimate(ws, wr, bp, psd)
            except Exception:
                fc10 = defaults.get('fc10', 0.35)

        N2 = N2_estimate(psd)

        horizon['ws'] = ws
        horizon['fc33'] = fc33
        horizon['fc15'] = fc15
        horizon['fc10'] = fc10
        horizon['ksat_cm_hr'] = ksat
        horizon['pore_size_dist'] = round(psd, 4)
        horizon['bubbling_pressure'] = round(bp, 2)
        horizon['N2'] = round(N2, 2)
        horizon['C2'] = round(C2, 4)

    else:
        # --- MODE 2: Pure texture defaults ---
        ws = defaults['ws']
        fc33 = defaults['fc33']
        fc15 = defaults['fc15']
        ksat = defaults['ksat']
        psd = defaults['pore_size_dist']
        bp = defaults['bubbling_pressure']

        try:
            fc10 = fc10_estimate(ws, wr, bp, psd)
        except Exception:
            fc10 = 0.35

        try:
            C2 = C2_estimate(bp, psd, ksat, 0)
        except Exception:
            C2 = 0.0

        N2 = N2_estimate(psd)

        horizon['ws'] = ws
        horizon['wr'] = wr
        horizon['fc33'] = fc33
        horizon['fc15'] = fc15
        horizon['fc10'] = round(fc10, 4)
        horizon['ksat_cm_hr'] = ksat
        horizon['pore_size_dist'] = psd
        horizon['bubbling_pressure'] = bp
        horizon['N2'] = round(N2, 2)
        horizon['C2'] = round(C2, 4)

    return horizon


def _retrieve_vic_global(lat, lon, source_path, num_horizons):
    """Retrieve soil data from VIC global parameter file."""
    if not source_path:
        # Search common locations — user should provide SOURCE_PATH for portability
        home = os.path.expanduser('~')
        candidates = [
            os.path.join(home, 'Hydrocraft', 'Hydrocraft', 'data', 'soil', 'global_soil_param_new.txt'),
            os.path.join(home, 'data', 'soil', 'global_soil_param_new.txt'),
        ]
        for c in candidates:
            if os.path.isfile(c):
                source_path = c
                break

    if not source_path or not os.path.isfile(source_path):
        return None, "VIC global soil parameter file not found. Provide SOURCE_PATH."

    # Read the file and find nearest grid cell
    best_row = None
    best_dist = float('inf')

    with open(source_path) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 53:
                continue
            try:
                row_lat = float(parts[2])
                row_lon = float(parts[3])
                dist = (row_lat - lat) ** 2 + (row_lon - lon) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_row = parts
            except (ValueError, IndexError):
                continue

    if best_row is None:
        return None, "No matching grid cell found in VIC global soil parameter file."

    if math.sqrt(best_dist) > 1.0:
        return None, f"Nearest grid cell is {math.sqrt(best_dist):.2f} degrees away — too far."

    # Extract VIC parameters for 3 layers
    # Column indices (0-based): 9-11=expt, 12-14=ksat(mm/day), 22-24=depth(m),
    # 33-35=bulk_density(kg/m3), 40-42=Wcr_FRACT, 43-45=Wpwp_FRACT
    vic_layers = []
    cumulative_depth = 0
    for layer in range(3):
        expt = float(best_row[9 + layer])
        ksat_mm_day = float(best_row[12 + layer])
        depth_m = float(best_row[22 + layer])
        bulk_density_kgm3 = float(best_row[33 + layer])
        wcr_fract = float(best_row[40 + layer])
        wpwp_fract = float(best_row[43 + layer])

        # Unit conversions
        ksat_cm_hr = ksat_mm_day / 240.0
        pore_size_dist = 2.0 / expt if expt > 0 else 0.5
        bulk_density_gcc = bulk_density_kgm3 / 1000.0
        ws = 1.0 - bulk_density_gcc / 2.65
        ws = max(0.3, min(0.7, ws))  # clamp to physical range
        fc33 = wcr_fract * ws
        fc15 = wpwp_fract * ws

        cumulative_depth += depth_m * 100  # m -> cm

        vic_layers.append({
            'depth_cm': round(cumulative_depth),
            'ksat_cm_hr': round(ksat_cm_hr, 4),
            'pore_size_dist': round(pore_size_dist, 3),
            'ws': round(ws, 4),
            'fc33': round(fc33, 4),
            'fc15': round(fc15, 4),
            'bulk_density_gcc': round(bulk_density_gcc, 3),
            'sand_pct': None,  # Not in VIC global params
            'silt_pct': None,
            'clay_pct': None,
            'texture_class': None,
            'wr': None,
            'bubbling_pressure': None,
        })

    # Expand VIC 3 layers to target horizon count if needed
    horizons = []
    target_depths = DEFAULT_HORIZON_DEPTHS[:num_horizons]
    if len(target_depths) < num_horizons:
        target_depths = [round(d) for d in
                         [i * vic_layers[-1]['depth_cm'] / num_horizons
                          for i in range(1, num_horizons + 1)]]

    for depth in target_depths:
        # Find which VIC layer contains this depth
        source_layer = vic_layers[-1]  # default to deepest
        for vl in vic_layers:
            if depth <= vl['depth_cm']:
                source_layer = vl
                break
        h = dict(source_layer)
        h['depth_cm'] = depth
        # Estimate texture from bulk density + ksat (rough heuristic)
        if h['bulk_density_gcc'] > 1.5 and h['ksat_cm_hr'] < 0.5:
            h['texture_class'] = 'clay loam'
        elif h['bulk_density_gcc'] < 1.3 and h['ksat_cm_hr'] > 5.0:
            h['texture_class'] = 'sandy loam'
        else:
            h['texture_class'] = 'loam'
        horizons.append(_fill_hydraulic_params(h))

    return {
        'source': 'vic_global',
        'lat': float(best_row[2]),
        'lon': float(best_row[3]),
        'vic_grid_id': int(float(best_row[1])),
        'horizons': horizons
    }, None


def _retrieve_soilgrids(lat, lon, num_horizons):
    """
    Retrieve soil data from ISRIC SoilGrids using the soilgrids Python package.

    Fetches: sand, silt, clay, bdod (bulk density), soc (organic carbon)
    at 6 standard depths.

    Note: wv0033/wv1500 (water retention) are not available through the
    soilgrids package. Brooks-Corey parameters are derived via Mode 2
    (texture defaults) from pedotransfer functions.

    Requires: pip install soilgrids rasterio
    """
    depths = ['0-5cm', '5-15cm', '15-30cm', '30-60cm', '60-100cm', '100-200cm']
    depth_cm_map = {
        '0-5cm': 5, '5-15cm': 15, '15-30cm': 30,
        '30-60cm': 60, '60-100cm': 100, '100-200cm': 200
    }

    # Properties available through the soilgrids package
    properties = ['sand', 'silt', 'clay', 'bdod', 'soc']

    depth_props = {d: {} for d in depths}

    try:
        from soilgrids import SoilGrids
        import tempfile
        sg = SoilGrids()

        for prop in properties:
            for depth_label in depths:
                coverage_id = f"{prop}_{depth_label}_mean"
                tmpfile = os.path.join(tempfile.gettempdir(), f'sg_{prop}_{depth_label}.tif')
                try:
                    sg.get_coverage_data(
                        service_id=prop,
                        coverage_id=coverage_id,
                        crs='urn:ogc:def:crs:EPSG::4326',
                        west=lon - 0.002, east=lon + 0.002,
                        south=lat - 0.002, north=lat + 0.002,
                        width=1, height=1,
                        output=tmpfile
                    )
                    if os.path.isfile(tmpfile):
                        import rasterio
                        with rasterio.open(tmpfile) as src:
                            val = float(src.read(1).flatten()[0])
                            nodata = src.nodata
                        os.remove(tmpfile)
                        # Skip nodata values (commonly -32768)
                        if nodata is not None and val == nodata:
                            continue
                        if val < -9000:
                            continue
                        depth_props[depth_label][prop] = val
                except Exception:
                    if os.path.exists(tmpfile):
                        os.remove(tmpfile)
                    continue

    except ImportError:
        # --- Fallback to REST API ---
        try:
            import urllib.request
        except ImportError:
            return None, "Neither soilgrids package nor urllib available."

        url = (
            f"https://rest.isric.org/soilgrids/v2.0/properties/query"
            f"?lon={lon}&lat={lat}"
            f"&property={'&property='.join(properties)}"
            f"&depth={'&depth='.join(depths)}"
            f"&value=mean"
        )

        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            return None, f"SoilGrids API request failed: {e}"

        for layer in data.get('properties', {}).get('layers', []):
            prop_name = layer['name']
            for depth_entry in layer.get('depths', []):
                depth_label = depth_entry['label']
                values = depth_entry.get('values', {})
                mean_val = values.get('mean')
                if mean_val is not None:
                    depth_props[depth_label][prop_name] = mean_val

    # Check we got actual data
    has_data = any(bool(depth_props[d]) for d in depths)
    if not has_data:
        return None, "SoilGrids returned no data for this location. It may be outside coverage (ocean, ice)."

    # --- Convert SoilGrids units to standard units ---
    # sand/silt/clay: g/kg -> % (divide by 10)
    # bdod: cg/cm3 -> g/cm3 (divide by 100)
    # soc: dg/kg -> g/kg (divide by 10)
    all_horizons = []
    for depth_label in depths:
        props = depth_props[depth_label]
        if not props:
            continue

        sand = props.get('sand', 400) / 10.0
        clay = props.get('clay', 200) / 10.0
        silt_raw = props.get('silt')
        silt = silt_raw / 10.0 if silt_raw else (100 - sand - clay)
        bd = props.get('bdod', 140) / 100.0
        soc = props.get('soc', 10) / 10.0

        ws = round(1.0 - bd / 2.65, 4)
        ws = max(0.25, min(0.70, ws))

        h = {
            'depth_cm': depth_cm_map[depth_label],
            'sand_pct': round(sand, 1),
            'silt_pct': round(silt, 1),
            'clay_pct': round(clay, 1),
            'bulk_density_gcc': round(bd, 3),
            'organic_carbon_pct': round(soc, 2),
            'texture_class': _get_texture_class(sand, clay),
            'ws': ws,
            # No measured water retention from soilgrids package
            # -> Mode 2 (texture defaults) for pedotransfer
            'fc33': None,
            'fc15': None,
            'fc10': None,
            'ksat_cm_hr': None,
            'wr': None,
            'bubbling_pressure': None,
            'pore_size_dist': None,
        }

        all_horizons.append(_fill_hydraulic_params(h))

    if not all_horizons:
        return None, "No valid soil horizons could be constructed from SoilGrids data."

    # Subsample to target horizon count
    if len(all_horizons) > num_horizons:
        indices = [int(i * len(all_horizons) / num_horizons) for i in range(num_horizons)]
        horizons = [all_horizons[i] for i in indices]
    else:
        horizons = all_horizons

    return {
        'source': 'soilgrids',
        'lat': lat, 'lon': lon,
        'horizons': horizons
    }, None


def process(args):
    """
    Retrieve soil data from the specified source.
    Returns (success, error_msg, result).
    """
    lat = args['lat']
    lon = args['lon']
    source = args['source']
    source_path = args['source_path']
    num_horizons = args['num_horizons']

    try:
        result = None
        err = None

        if source == 'vic_global':
            result, err = _retrieve_vic_global(lat, lon, source_path, num_horizons)

        elif source == 'soilgrids':
            result, err = _retrieve_soilgrids(lat, lon, num_horizons)

        elif source == 'gssurgo':
            # Wrap existing us_soil_char.py
            return False, "gssurgo backend not yet implemented (requires geopandas + state geodatabase).", None

        elif source == 'canada_shapefile':
            # Wrap existing soil_char_retri.py
            return False, "canada_shapefile backend not yet implemented (requires shapefile paths).", None

        elif source == 'hwsd':
            # Delegate to hwsd_soil_adapter
            from hwsd_soil_adapter import _get_mu_global, _lookup_hwsd, _build_horizons
            hwsd_raster = source_path or 'KISSPATH_STATIC/HWSD_China_Geo.img'
            hwsd_mdb = 'KISSPATH_FORCING/huaihe_raw/soil/HWSD.mdb'
            mu, err_mu = _get_mu_global(lat, lon, hwsd_raster)
            if err_mu:
                return False, err_mu, None
            hwsd_data, err_hw = _lookup_hwsd(mu, hwsd_mdb)
            if err_hw:
                return False, err_hw, None
            horizons = _build_horizons(hwsd_data, num_horizons)
            result = {'source': 'hwsd', 'lat': lat, 'lon': lon,
                      'mu_global': mu, 'horizons': horizons}
            return True, "", result

        if err:
            return False, err, None

        return True, "", result

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(result):
    """Check that horizons were produced with required fields."""
    if not result or 'horizons' not in result:
        return False, "No horizons produced."
    if len(result['horizons']) == 0:
        return False, "Empty horizons list."

    for i, h in enumerate(result['horizons']):
        if h.get('depth_cm', 0) <= 0:
            return False, f"Horizon {i}: invalid depth_cm={h.get('depth_cm')}"
        if h.get('ksat_cm_hr') is None:
            return False, f"Horizon {i}: ksat_cm_hr is missing."
        if h.get('ws') is None:
            return False, f"Horizon {i}: ws (saturated water content) is missing."

    return True, ""


def main():
    lat_raw = sys.argv[1] if len(sys.argv) > 1 else LAT
    lon_raw = sys.argv[2] if len(sys.argv) > 2 else LON
    source = sys.argv[3] if len(sys.argv) > 3 else SOURCE
    source_path = sys.argv[4] if len(sys.argv) > 4 else SOURCE_PATH
    num_horizons_raw = sys.argv[5] if len(sys.argv) > 5 else NUM_HORIZONS
    state_code = sys.argv[6] if len(sys.argv) > 6 else STATE_CODE

    valid, err, args = validate_inputs(lat_raw, lon_raw, source, source_path, num_horizons_raw, state_code)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    success, err, result = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    valid, err = validate_outputs(result)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "result": result,
        "message": (
            f"Retrieved {len(result['horizons'])} soil horizons from {result['source']} "
            f"at ({result['lat']}, {result['lon']})."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
