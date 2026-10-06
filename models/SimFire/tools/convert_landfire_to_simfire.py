#!/usr/bin/env python3
"""
convert_landfire_to_simfire.py — Convert LandFire GeoTIFF fuel/elevation to SimFire format.

Downloads or reads LandFire FBFM-13 fuel model and elevation rasters for a given
geographic bounding box, then converts them to SimFire-compatible numpy arrays.

CRITICAL UNIT CONVERSIONS:
  - Elevation: LandFire provides meters. SimFire expects feet. Multiply by 3.28084.
  - Fuel models: LandFire uses integer codes (1-13, 91-99). SimFire maps these to
    Fuel dataclass objects with (w_0, delta, M_x, sigma) in lb/ft², ft, -, ft²/ft³.
  - Area: Config specifies height/width in meters, resolution in meters (30m).

Output:
  - fuel_array.npy: int array of FBFM-13 codes, shape (H, W)
  - elevation_array.npy: float array of elevation in FEET, shape (H, W)
  - metadata.json: bounding box, CRS, resolution, conversion notes

Usage:
    python convert_landfire_to_simfire.py \\
        --latitude 38.422 --longitude -118.266 \\
        --height 2000 --width 2000 \\
        --resolution 30 --year 2020 \\
        --output-dir ./simfire_terrain/

    python convert_landfire_to_simfire.py \\
        --fuel-tif fuel.tif --elev-tif elev.tif \\
        --output-dir ./simfire_terrain/
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

# FBFM-13 fuel model code mapping
# Non-burnable codes map to 0 (w_0=0)
FBFM13_VALID_CODES = set(range(1, 14))  # 1-13 burnable
FBFM13_NONBURNABLE = {91, 92, 93, 98, 99, -32768, -9999, 0}

# Fuel parameters: (w_0 [lb/ft²], delta [ft], M_x [-], sigma [ft²/ft³])
FUEL_PARAMS = {
    1:  (0.0340, 1.000, 0.12, 3500),
    2:  (0.0918, 1.000, 0.15, 2784),
    3:  (0.1377, 2.500, 0.25, 1500),
    4:  (0.2296, 6.000, 0.20, 1739),
    5:  (0.0459, 2.000, 0.20, 1683),
    6:  (0.0688, 2.500, 0.25, 1564),
    7:  (0.0459, 2.500, 0.40, 1552),
    8:  (0.0688, 0.200, 0.30, 1889),
    9:  (0.1331, 0.200, 0.25, 2484),
    10: (0.1377, 1.000, 0.25, 1764),
    11: (0.0688, 1.000, 0.15, 1182),
    12: (0.1836, 2.300, 0.20, 1145),
    13: (0.3214, 3.000, 0.25, 1159),
}

METERS_TO_FEET = 3.28084

# ---------------------------------------------------------------------------
# LandFire Product Service (LFPS) v2 client + shim
#
# WHY THIS EXISTS (verified live 2026-08-09):
#   simfire 2.0.1 acquires operational fuel/elevation through the `landfire`
#   PyPI client (v0.5.0), which posts to the ArcGIS GPServer endpoint
#     https://lfps.usgs.gov/arcgis/rest/services/LandfireProductService/
#         GPServer/LandfireProductService/submitJob
#   USGS RETIRED that endpoint.  It now serves the LFPS *web page* (HTML), so
#   `landfire` does `response.json()` on a Next.js document and dies with
#     requests.exceptions.JSONDecodeError: Expecting value: line 1 column 1
#   i.e. simfire's ENTIRE `terrain.{topography,fuel}.type: operational` path is
#   dead as shipped.  triplets.yaml dt_012 only anticipated
#   ConnectionError|HTTPError|Timeout, which does NOT match.  See dt_020.
#
# The replacement REST API is:
#   GET https://lfps.usgs.gov/api/products                -> product catalogue
#   GET https://lfps.usgs.gov/api/job/submit?Layer_List=..&Area_of_Interest=..
#                                           &Email=..[&Output_Projection=..]
#   GET https://lfps.usgs.gov/api/job/status?JobId=..     -> .outputFile (zip)
# Notes learned by probing the live service:
#   * `Email` is now a REQUIRED parameter (400 "Required" without it).
#   * `Resample_Resolution` must be >= 31; OMIT it to get native 30 m.
#   * Layer names changed: 200F13_19/200F13_20 -> LF2016_FBFM13,
#     220F13_22 -> LF2022_FBFM13, ELEV2020 -> LF2020_Elev.
#   * OMIT `Output_Projection` to keep LANDFIRE's native 30 m Albers grid.
#     Asking for 4326 returns ~0.00037 deg SQUARE-IN-DEGREES cells (~41 m N-S,
#     ~32 m E-W at 40 deg N) which silently contradicts simfire's hard-coded
#     0.00027777777803598015 deg-per-pixel and its pixel_scale of 30/0.3048 ft.
#     Native Albers cells ARE exactly 30 m square, so pixel_scale is honest.
#     The upstream `landfire` docstring says the same thing: the native Albers
#     projection is "needed for most fire models (FlamMap, FARSITE, etc.)".
#   * lfps.usgs.gov fails TLS through the sandbox HTTP proxy
#     (SSL_ERROR_SYSCALL); the session below sets trust_env=False so it always
#     goes direct, mirroring what ki_tools_common.load_forcing does for
#     NASA POWER.
# ---------------------------------------------------------------------------

LFPS2_SUBMIT_URL = "https://lfps.usgs.gov/api/job/submit"
LFPS2_STATUS_URL = "https://lfps.usgs.gov/api/job/status"
LFPS2_PRODUCTS_URL = "https://lfps.usgs.gov/api/products"

# Legacy `landfire`-client layer id  ->  live LFPS v2 layerName
LEGACY_TO_LFPS2_LAYER = {
    "200F13_19": "LF2016_FBFM13",   # LF 2016 Remap, what simfire asks for year 2019
    "200F13_20": "LF2016_FBFM13",   # ... and for year 2020
    "220F13_22": "LF2022_FBFM13",   # LF 2022
    "ELEV2020": "LF2020_Elev",
}

LFPS2_DEFAULT_EMAIL = os.environ.get("LFPS_EMAIL", "hydrocraft@example.org")


def _lfps2_session():
    """A requests session that bypasses the environment proxy.

    lfps.usgs.gov terminates TLS through the local proxy with
    ``SSL_ERROR_SYSCALL``; direct connections succeed.
    """
    import requests

    s = requests.Session()
    s.trust_env = False
    return s


def lfps2_map_layers(layers):
    """Translate legacy `landfire`-client layer ids to live LFPS v2 names.

    Unknown ids are passed through unchanged (they may already be v2 names).
    """
    return [LEGACY_TO_LFPS2_LAYER.get(str(lyr), str(lyr)) for lyr in layers]


def isotropize_bbox(bbox, safety=1.05):
    """Widen a lon/lat AOI so its E-W extent in METRES >= its N-S extent.

    simfire computes its bottom-right corner with a single isotropic constant,
    ``0.00027777777803598015`` degrees "= 30 m", for BOTH latitude and
    longitude (config.py:340-342).  That is true for latitude but NOT for
    longitude: at 40 deg N one such step spans only ~23.5 m.  It then crops the
    returned raster to ``[:floor(height/30), :floor(width/30)]``
    (layers.py:123-127).  On a real 30 m grid the requested AOI therefore runs
    OUT OF COLUMNS once floor(width/30) exceeds ~360 at mid-latitudes, and the
    crop silently returns a NARROWER array than the config asked for -- the
    domain is quietly truncated in the east-west direction.

    Widening the AOI eastward costs only download time (simfire crops back to
    the configured column count), so it is the safe side to err on.

    Args:
        bbox: "minx miny maxx maxy" string or 4-sequence, decimal degrees.
        safety: extra multiplicative margin on the required width.

    Returns:
        str: possibly-widened "minx miny maxx maxy".
    """
    import math

    parts = [float(v) for v in (bbox.split() if isinstance(bbox, str) else bbox)]
    # TRAP: simfire emits its AOI as (lon_TL, lat_TL, lon_BR, lat_BR)
    # (layers.py:239-244), i.e. "minx MAXY maxx MINY" -- the LATITUDES ARE
    # DESCENDING, not the "minx miny maxx maxy" every bbox parser assumes.
    # Reading it positionally makes (maxy - miny) NEGATIVE, the widening test
    # below silently passes, and the domain stays truncated. Normalise first.
    lons = sorted((parts[0], parts[2]))
    lats = sorted((parts[1], parts[3]))
    minx, maxx = lons
    miny, maxy = lats
    mean_lat = 0.5 * (miny + maxy)
    m_per_deg_lat = 111320.0
    m_per_deg_lon = max(1.0, 111320.0 * math.cos(math.radians(mean_lat)))

    need_m = (maxy - miny) * m_per_deg_lat * safety
    have_m = (maxx - minx) * m_per_deg_lon
    if have_m < need_m:
        maxx = minx + need_m / m_per_deg_lon
    return f"{minx} {miny} {maxx} {maxy}"


def lfps2_request_data(
    bbox,
    layers,
    output_path,
    email=None,
    output_projection=None,
    poll_seconds=20,
    timeout_seconds=5400,
    show_status=True,
    isotropic_pad=True,
):
    """Download LandFire layers via the live LFPS v2 REST API.

    Args:
        bbox: "minx miny maxx maxy" in decimal degrees (WGS84), or a 4-sequence.
        layers: list of layer ids (legacy or v2 names; legacy are translated).
        output_path: destination .zip path.
        email: contact address required by LFPS. Falls back to $LFPS_EMAIL.
        output_projection: EPSG integer, or None (default) to keep LANDFIRE's
            native 30 m Albers grid -- STRONGLY preferred for fire models.
        poll_seconds: status poll interval.
        timeout_seconds: give up after this long.

    Returns:
        str: the output_path that was written.

    Raises:
        RuntimeError: on submit rejection, job failure, or timeout.
    """
    import time

    if not isinstance(bbox, str):
        bbox = " ".join(str(v) for v in bbox)
    # simfire builds its bbox string with embedded newlines/indentation from a
    # line-continued f-string; collapse any whitespace run to a single space.
    bbox = " ".join(str(bbox).split())
    if isotropic_pad:
        bbox = isotropize_bbox(bbox)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    params = {
        "Layer_List": ";".join(lfps2_map_layers(layers)),
        "Area_of_Interest": bbox,
        "Email": email or LFPS2_DEFAULT_EMAIL,
    }
    if output_projection is not None:
        params["Output_Projection"] = str(output_projection)

    sess = _lfps2_session()
    resp = sess.get(LFPS2_SUBMIT_URL, params=params, timeout=180)
    try:
        payload = resp.json()
    except ValueError:
        raise RuntimeError(
            f"LFPS submit did not return JSON (HTTP {resp.status_code}). "
            f"First 200 chars: {resp.text[:200]!r}"
        )
    if "jobId" not in payload:
        raise RuntimeError(f"LFPS submit rejected: {payload}")
    job_id = payload["jobId"]
    if show_status:
        print(f"  LFPS job {job_id} submitted for {params['Layer_List']}", flush=True)

    deadline = time.time() + timeout_seconds
    status, output_file = payload.get("status", "Pending"), None
    while time.time() < deadline:
        time.sleep(poll_seconds)
        try:
            st = sess.get(LFPS2_STATUS_URL, params={"JobId": job_id}, timeout=120).json()
        except Exception as exc:  # transient network blip -> keep polling
            if show_status:
                print(f"  LFPS status poll retry ({exc})", flush=True)
            continue
        status = st.get("status", status)
        output_file = st.get("outputFile")
        if status == "Succeeded" and output_file:
            break
        if status == "Failed":
            msgs = [m.get("description", "") for m in st.get("messages", [])][-5:]
            raise RuntimeError(f"LFPS job {job_id} failed: {msgs}")
    else:
        raise RuntimeError(
            f"LFPS job {job_id} did not finish within {timeout_seconds}s "
            f"(last status: {status})"
        )

    with sess.get(output_file, stream=True, timeout=1800) as dl:
        dl.raise_for_status()
        with open(str(out), "wb") as fh:
            for chunk in dl.iter_content(chunk_size=1 << 20):
                if chunk:
                    fh.write(chunk)

    if out.stat().st_size < 1024:
        raise RuntimeError(f"LFPS download suspiciously small: {out.stat().st_size} B")
    if show_status:
        print(f"  LFPS job {job_id} -> {out} ({out.stat().st_size} B)", flush=True)
    return str(out)


def install_lfps2_shim(email=None, output_projection=None, show_status=True):
    """Redirect the `landfire` client (and hence simfire) onto LFPS v2.

    simfire's ``LandFireLatLongBox.query_lat_lon_layer_data`` builds a
    ``landfire.Landfire`` and calls ``request_data(layers=..., output_path=...)``.
    Patching that ONE method leaves simfire's operational pipeline -- bbox
    construction, zip unpacking, band ordering, cropping -- completely intact
    while swapping the dead transport for the live one.

    Call this BEFORE constructing ``simfire.utils.config.Config``.

    Args:
        email: LFPS contact address (required by the service).
        output_projection: EPSG int, or None (default) for native 30 m Albers.
            NOTE simfire passes ``output_crs="4326"`` to the Landfire
            constructor; the shim deliberately IGNORES it, because the 4326
            reprojection breaks the 30 m square-cell assumption baked into
            simfire's pixel_scale and its floor(height/30) crop.

    Returns:
        bool: True if the patch was installed.
    """
    import landfire

    def _patched_request_data(self, layers, output_path, show_status=show_status,
                              backoff_base_value=5):
        # TRAP: the key is "Area_Of_Interest" with a CAPITAL O
        # (landfire/__init__.py:36). Reading "Area_of_Interest" silently yields
        # "" and the AOI parser then dies with
        #   ValueError: not enough values to unpack (expected 4, got 0)
        params = getattr(self, "_base_params", {}) or {}
        bbox = (
            params.get("Area_Of_Interest")
            or params.get("Area_of_Interest")
            or getattr(self, "bbox", "")
        )
        if not str(bbox).strip():
            raise RuntimeError(
                "LFPS shim could not find the AOI on the Landfire client "
                f"(keys present: {sorted(params)})"
            )
        return lfps2_request_data(
            bbox=bbox,
            layers=list(layers),
            output_path=output_path,
            email=email,
            output_projection=output_projection,
            poll_seconds=max(5, int(backoff_base_value) * 4),
            show_status=show_status,
        )

    landfire.Landfire.request_data = _patched_request_data
    return True


def validate_inputs(args):
    """Validate command-line arguments before processing.

    Checks geographic bounds, resolution, file existence.
    Exits with JSON error if validation fails.
    """
    errors = []

    if args.fuel_tif and args.elev_tif:
        # File mode: check files exist
        if not os.path.isfile(args.fuel_tif):
            errors.append(f"Fuel GeoTIFF not found: {args.fuel_tif}")
        if not os.path.isfile(args.elev_tif):
            errors.append(f"Elevation GeoTIFF not found: {args.elev_tif}")
    else:
        # Download mode: check coordinates
        if args.latitude is None or args.longitude is None:
            errors.append("Must provide --latitude and --longitude, or --fuel-tif and --elev-tif")
        if args.latitude is not None and not (-90 <= args.latitude <= 90):
            errors.append(f"Latitude {args.latitude} out of range [-90, 90]")
        if args.longitude is not None and not (-180 <= args.longitude <= 180):
            errors.append(f"Longitude {args.longitude} out of range [-180, 180]")
        if args.height <= 0 or args.width <= 0:
            errors.append(f"Height ({args.height}) and width ({args.width}) must be positive meters")
        if args.resolution != 30:
            errors.append(f"Resolution must be 30m (LandFire native), got {args.resolution}")
        if args.year not in (2019, 2020, 2022):
            errors.append(f"LandFire year must be 2019, 2020, or 2022, got {args.year}")

    if errors:
        print(json.dumps({"status": "error", "stage": "validate_inputs", "errors": errors}))
        sys.exit(1)


def read_geotiff(filepath):
    """Read a GeoTIFF file and return (data_array, metadata_dict).

    Uses geotiff or rasterio depending on availability.
    """
    try:
        from geotiff import GeoTiff
        geo = GeoTiff(str(filepath))
        data = np.array(geo.read())
        meta = {
            "crs": str(geo.crs_code),
            "bbox": geo.tif_bBox,
            "shape": list(data.shape),
        }
        return data, meta
    except ImportError:
        pass

    try:
        import rasterio
        with rasterio.open(str(filepath)) as src:
            data = src.read(1)
            meta = {
                "crs": str(src.crs),
                "bbox": list(src.bounds),
                "shape": list(data.shape),
                "transform": list(src.transform)[:6],
            }
            return data, meta
    except ImportError:
        print(json.dumps({
            "status": "error",
            "errors": ["Neither geotiff nor rasterio installed. pip install geotiff rasterio"]
        }))
        sys.exit(1)


def download_landfire(latitude, longitude, height, width, resolution, year, output_dir):
    """Download LandFire fuel and elevation data using the landfire package.

    Returns paths to downloaded GeoTIFF files.
    """
    try:
        from landfire import Landfire
    except ImportError:
        print(json.dumps({
            "status": "error",
            "errors": ["landfire package not installed. pip install landfire"]
        }))
        sys.exit(1)

    # Compute bounding box from top-left + dimensions
    # LandFire bbox: (west, south, east, north)
    from geopy.distance import geodesic

    south_point = geodesic(meters=height).destination((latitude, longitude), 180)
    east_point = geodesic(meters=width).destination((latitude, longitude), 90)

    bbox = (longitude, south_point.latitude, east_point.longitude, latitude)

    del Landfire  # only imported to prove the dependency is installed

    # NOTE (2026-08-09): the legacy `landfire` client's GPServer endpoint is
    # retired -- go straight to LFPS v2. FBFM13 and ELEV are requested in ONE
    # job so both bands land on an identical grid (band 0 = fuel, band 1 =
    # elevation, the order simfire's _make_data() assumes).
    fuel_layer = "LF2022_FBFM13" if int(year) >= 2022 else "LF2016_FBFM13"
    zip_path = os.path.join(output_dir, "landfire_lfps.zip")
    lfps2_request_data(
        bbox=f"{bbox[0]} {bbox[1]} {bbox[2]} {bbox[3]}",
        layers=[fuel_layer, "LF2020_Elev"],
        output_path=zip_path,
        output_projection=None,  # native 30 m Albers -- see module header
    )

    import shutil

    shutil.unpack_archive(zip_path, output_dir)
    tifs = sorted(Path(output_dir).glob("*.tif"))
    if not tifs:
        raise RuntimeError(f"LFPS zip contained no .tif: {zip_path}")
    # Single 2-band GeoTIFF: hand the same path back for both layers; the
    # caller's read_geotiff() picks band 1, so split it here instead.
    import rasterio

    fuel_path = os.path.join(output_dir, "landfire_fuel.tif")
    elev_path = os.path.join(output_dir, "landfire_elev.tif")
    with rasterio.open(str(tifs[0])) as src:
        prof = src.profile
        prof.update(count=1)
        with rasterio.open(fuel_path, "w", **prof) as dst:
            dst.write(src.read(1), 1)
        with rasterio.open(elev_path, "w", **prof) as dst:
            dst.write(src.read(2), 1)

    return fuel_path, elev_path


def convert_fuel_array(fuel_raw):
    """Convert raw LandFire FBFM codes to clean integer array.

    Maps non-burnable codes (91, 92, 93, 98, 99, nodata) to 0.
    Validates all codes are in expected range.

    Returns:
        fuel_clean: int array with values in {0, 1, 2, ..., 13}
        stats: dict with code distribution
    """
    fuel_clean = fuel_raw.copy().astype(int)

    # Map non-burnable and nodata to 0
    for code in FBFM13_NONBURNABLE:
        fuel_clean[fuel_raw == code] = 0

    # Check for unexpected codes
    unique_codes = set(np.unique(fuel_clean))
    expected = FBFM13_VALID_CODES | {0}
    unexpected = unique_codes - expected
    if unexpected:
        print(json.dumps({
            "status": "warning",
            "message": f"Unexpected fuel codes found: {unexpected}. Mapping to non-burnable (0)."
        }), file=sys.stderr)
        for code in unexpected:
            fuel_clean[fuel_clean == code] = 0

    stats = {}
    for code in sorted(expected):
        count = int(np.sum(fuel_clean == code))
        if count > 0:
            stats[str(code)] = count

    return fuel_clean, stats


def convert_elevation_array(elev_raw):
    """Convert elevation from meters (LandFire) to feet (SimFire).

    CRITICAL: SimFire Rothermel model expects elevation in FEET.
    LandFire provides elevation in METERS.
    Conversion: feet = meters × 3.28084

    Returns:
        elev_feet: float array in feet
        stats: dict with min, max, mean elevation
    """
    # Handle nodata values
    nodata_mask = (elev_raw < -1000) | (elev_raw > 30000)
    elev_clean = elev_raw.astype(float)
    elev_clean[nodata_mask] = 0.0

    # CRITICAL CONVERSION: meters → feet
    elev_feet = elev_clean * METERS_TO_FEET

    stats = {
        "min_ft": float(np.min(elev_feet[~nodata_mask])) if not nodata_mask.all() else 0.0,
        "max_ft": float(np.max(elev_feet[~nodata_mask])) if not nodata_mask.all() else 0.0,
        "mean_ft": float(np.mean(elev_feet[~nodata_mask])) if not nodata_mask.all() else 0.0,
        "nodata_pixels": int(np.sum(nodata_mask)),
    }

    return elev_feet, stats


def validate_outputs(fuel_array, elev_array, output_dir):
    """Post-processing validation of converted arrays.

    Checks:
    - Arrays have same shape
    - Fuel codes are valid
    - Elevation values are in reasonable range (feet)
    - At least some burnable pixels exist
    """
    errors = []

    if fuel_array.shape != elev_array.shape:
        errors.append(
            f"Shape mismatch: fuel {fuel_array.shape} vs elevation {elev_array.shape}"
        )

    burnable = np.sum((fuel_array >= 1) & (fuel_array <= 13))
    if burnable == 0:
        errors.append("No burnable pixels found. Check fuel model data or bounding box.")

    elev_min = np.min(elev_array)
    elev_max = np.max(elev_array)
    if elev_max > 30000:  # ~30000 ft = Mt. Everest
        errors.append(
            f"Elevation max {elev_max:.0f} ft seems too high. "
            "Check if data is in meters (should be feet)."
        )
    if elev_min < -2000:  # Below Death Valley
        errors.append(
            f"Elevation min {elev_min:.0f} ft seems too low. Check nodata handling."
        )

    if errors:
        print(json.dumps({"status": "error", "stage": "validate_outputs", "errors": errors}))
        sys.exit(1)

    return {
        "shape": list(fuel_array.shape),
        "burnable_pixels": int(burnable),
        "total_pixels": int(fuel_array.size),
        "burnable_fraction": float(burnable / fuel_array.size),
        "elevation_range_ft": [float(elev_min), float(elev_max)],
    }


def process(args):
    """Main processing pipeline: download/read → convert → validate → save."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Acquire data
    if args.fuel_tif and args.elev_tif:
        fuel_raw, fuel_meta = read_geotiff(args.fuel_tif)
        elev_raw, elev_meta = read_geotiff(args.elev_tif)
    else:
        fuel_path, elev_path = download_landfire(
            args.latitude, args.longitude,
            args.height, args.width,
            args.resolution, args.year,
            str(output_dir),
        )
        fuel_raw, fuel_meta = read_geotiff(fuel_path)
        elev_raw, elev_meta = read_geotiff(elev_path)

    # Step 2: Convert
    fuel_array, fuel_stats = convert_fuel_array(fuel_raw)
    elev_array, elev_stats = convert_elevation_array(elev_raw)

    # Step 3: Validate outputs
    validation = validate_outputs(fuel_array, elev_array, str(output_dir))

    # Step 4: Save
    fuel_path = output_dir / "fuel_array.npy"
    elev_path = output_dir / "elevation_array.npy"
    meta_path = output_dir / "metadata.json"

    np.save(str(fuel_path), fuel_array)
    np.save(str(elev_path), elev_array)

    metadata = {
        "source": "LandFire FBFM-13 + ELEV",
        "fuel_stats": fuel_stats,
        "elevation_stats": elev_stats,
        "validation": validation,
        "fuel_meta": fuel_meta if 'fuel_meta' in dir() else {},
        "elev_meta": elev_meta if 'elev_meta' in dir() else {},
        "unit_conversions": {
            "elevation": "meters → feet (×3.28084)",
            "fuel_codes": "FBFM-13 integer codes (1-13 burnable, 0 non-burnable)",
        },
    }
    with open(str(meta_path), "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    return {
        "fuel_array": str(fuel_path),
        "elevation_array": str(elev_path),
        "metadata": str(meta_path),
        "validation": validation,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert LandFire GeoTIFF fuel/elevation to SimFire format"
    )
    # Download mode arguments
    parser.add_argument("--latitude", type=float, default=None,
                        help="Top-left latitude (decimal degrees)")
    parser.add_argument("--longitude", type=float, default=None,
                        help="Top-left longitude (decimal degrees)")
    parser.add_argument("--height", type=float, default=2000,
                        help="Area height in meters")
    parser.add_argument("--width", type=float, default=2000,
                        help="Area width in meters")
    parser.add_argument("--resolution", type=int, default=30,
                        help="Resolution in meters (must be 30)")
    parser.add_argument("--year", type=int, default=2020,
                        help="LandFire year (2019, 2020, 2022)")

    # File mode arguments
    parser.add_argument("--fuel-tif", type=str, default=None,
                        help="Path to fuel model GeoTIFF")
    parser.add_argument("--elev-tif", type=str, default=None,
                        help="Path to elevation GeoTIFF")

    parser.add_argument("--output-dir", type=str, required=True,
                        help="Output directory for converted arrays")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)

    print(json.dumps({"status": "success", "output": result}, indent=2, default=str))


if __name__ == "__main__":
    main()
