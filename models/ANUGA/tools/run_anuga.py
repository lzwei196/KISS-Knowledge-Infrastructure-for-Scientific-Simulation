#!/usr/bin/env python3
"""
run_anuga.py — Set up and execute an ANUGA 2D shallow-water simulation for a
real-world catchment using DEM data and CMFD/MSWX rainfall forcing.

Creates an unstructured triangular mesh domain from a bounding polygon derived
from the catchment coordinates, fits DEM elevation, applies rainfall forcing
from convert_forcing_to_anuga.py output, and runs the simulation.

Workflow:
  1. Build bounding polygon from lat/lon center + catchment extent
  2. Create triangular mesh (anuga.create_domain_from_regions)
  3. Fit DEM elevation to mesh (from GeoTIFF via rasterio or ki_tools_common)
  4. Set initial conditions (dry bed or flat stage at elevation)
  5. Load rainfall time series and apply via Rate_operator
  6. Set boundary conditions (Reflective upslope, Transmissive at outlet)
  7. Run simulation (domain.evolve)
  8. Write SWW output for post-processing by parse_anuga_output.py

Usage:
    python run_anuga.py \
        --lat 32.9 --lon 117.4 \
        --extent_m 5000 \
        --forcing_csv ./forcing/rainfall_timeseries.csv \
        --output_dir ./output/ \
        --finaltime 86400 \
        --yieldstep 300

Output:
    <output_dir>/anuga_sim.sww — ANUGA SWW output file (stage, momentum, elevation)
    <output_dir>/run_summary.json — run metadata (elapsed time, mesh stats, etc.)
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
import warnings

import numpy as np

warnings.simplefilter("ignore")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Ensure ki_tools_common is importable
_ki_common = "KISSPATH_KI_TOOLS_COMMON"
if _ki_common not in sys.path:
    sys.path.insert(0, _ki_common)

# HydroCraft python env for anuga and other packages
_penv = "KISSPATH_PYTHON_ENV/lib/python3.12/site-packages"
if _penv not in sys.path:
    sys.path.insert(0, _penv)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def latlon_to_utm(lat, lon):
    """Convert lat/lon to approximate UTM easting/northing (meters).

    Uses a simple equirectangular projection centered on the given point.
    Sufficient for small catchments (< 50 km).
    """
    # UTM zone center
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * np.cos(np.radians(lat))
    return m_per_deg_lon, m_per_deg_lat


def latlon_to_domain_xy(center_lat, center_lon, lat, lon):
    """(lat, lon) → (x, y) metres in the ABSOLUTE polygon frame.

    The absolute frame is the one anuga.Region and the SWW xllcorner/yllcorner
    offsets use: metres from the domain centre, spanning -extent_m/2..+extent_m/2.
    It is NOT the mesh-relative 0..extent_m frame that set_quantity() callables
    see. Hand-computing this conversion is how the inlet ends up in a corner,
    so every caller (inlet placement, gauge extraction) should come through
    here and use the SAME equirectangular mapping as build_bounding_polygon.
    """
    m_per_deg_lon, m_per_deg_lat = latlon_to_utm(center_lat, center_lon)
    return ((lon - center_lon) * m_per_deg_lon,
            (lat - center_lat) * m_per_deg_lat)


def build_bounding_polygon(lat, lon, extent_m):
    """Build a rectangular bounding polygon in local coordinates.

    Returns polygon as list of (x, y) tuples in meters, centered at (0, 0).
    The origin (0, 0) corresponds to (lat, lon).
    """
    half = extent_m / 2.0
    return [
        (-half, -half),
        (half, -half),
        (half, half),
        (-half, half),
    ]


CHINA_DEM = "KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif"
MERIT_DEM_DIR = "KISSPATH_DATA/MERIT_DEM"
COP30_DEM_DIR = "KISSPATH_STATIC/dem_tiles_cache"


def cop30_tile_name(lat, lon):
    """Copernicus GLO-30 cached tile name containing (lat, lon).

    1x1 degree tiles named after their SOUTH-WEST corner:
    Copernicus_DSM_COG_10_N49_00_W122_00_DEM.tif spans lat 49..50 N,
    lon 122..121 W. Only a partial cache exists (North America + East Asia),
    so a miss is normal and falls through to MERIT.
    """
    tlat = int(np.floor(lat))
    tlon = int(np.floor(lon))
    ns = "N%02d" % tlat if tlat >= 0 else "S%02d" % abs(tlat)
    ew = "E%03d" % tlon if tlon >= 0 else "W%03d" % abs(tlon)
    return f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM.tif"


def merit_tile_name(lat, lon):
    """MERIT DEM v1.0.2 5x5-degree tile file name containing (lat, lon).

    Tiles are named after their SOUTH-WEST corner floored to a multiple of 5:
    n45w125_dem.tif spans lat 45..50 N, lon 125..120 W. Note the hemisphere
    letter follows the CORNER, so lon -121.7 -> w125 (not w120).
    """
    tlat = int(np.floor(lat / 5.0) * 5)
    tlon = int(np.floor(lon / 5.0) * 5)
    ns = "n%02d" % tlat if tlat >= 0 else "s%02d" % abs(tlat)
    ew = "e%03d" % tlon if tlon >= 0 else "w%03d" % abs(tlon)
    return f"{ns}{ew}_dem.tif"


def resolve_dem_sources(lat, lon, extent_m, dem_path=None):
    """Return the list of DEM rasters covering the domain bbox.

    Selection order:
      1. --dem_path, if given (single file; used verbatim).
      2. The China 90 m DEM, when the whole bbox falls inside its footprint.
      3. Copernicus GLO-30 (30 m) cached tiles, when ALL tiles the bbox
         touches are present.
      4. MERIT DEM 90 m global tiles overlapping the bbox (1-4 tiles).

    The China DEM used to be HARDCODED here, so every non-China site died in
    the `raise FileNotFoundError` below no matter what data existed. The
    global MERIT fallback is what makes a HYDAT / GRDC-Caravan site runnable;
    GLO-30 is preferred where cached because 90 m smears a several-hundred-
    metre river channel into the floodplain, which biases simulated stage.
    """
    import rasterio

    half = extent_m / 2.0
    m_per_deg_lon, m_per_deg_lat = latlon_to_utm(lat, lon)
    lat_min = lat - half / m_per_deg_lat
    lat_max = lat + half / m_per_deg_lat
    lon_min = lon - half / m_per_deg_lon
    lon_max = lon + half / m_per_deg_lon
    bbox = (lon_min, lat_min, lon_max, lat_max)

    if dem_path:
        if not os.path.isfile(dem_path):
            raise FileNotFoundError(f"--dem_path not found: {dem_path}")
        return [dem_path], bbox

    if os.path.isfile(CHINA_DEM):
        with rasterio.open(CHINA_DEM) as src:
            b = src.bounds
        if (b.left <= lon_min and lon_max <= b.right
                and b.bottom <= lat_min and lat_max <= b.top):
            return [CHINA_DEM], bbox

    def _tiles(namer, root):
        names, paths, missing = [], [], []
        for la in (lat_min, lat_max):
            for lo in (lon_min, lon_max):
                n = namer(la, lo)
                if n in names:
                    continue
                names.append(n)
                p = os.path.join(root, n)
                (paths if os.path.isfile(p) else missing).append(p)
        return names, paths, missing

    # Preferred: Copernicus GLO-30, but only when the cache covers the WHOLE
    # bbox -- a partial cover would silently truncate the domain.
    cop_names, cop_paths, cop_missing = _tiles(cop30_tile_name, COP30_DEM_DIR)
    if cop_paths and not cop_missing:
        logger.info("Using Copernicus GLO-30 tiles: %s", cop_names)
        return cop_paths, bbox
    if cop_paths and cop_missing:
        logger.info("Copernicus GLO-30 covers the bbox only partially "
                    "(missing %s); falling back to MERIT 90 m",
                    [os.path.basename(p) for p in cop_missing])

    # Global fallback: every MERIT tile the bbox touches.
    tiles, seen = [], set()
    for la in (lat_min, lat_max):
        for lo in (lon_min, lon_max):
            name = merit_tile_name(la, lo)
            if name in seen:
                continue
            seen.add(name)
            p = os.path.join(MERIT_DEM_DIR, name)
            if os.path.isfile(p):
                tiles.append(p)
            else:
                logger.warning("MERIT tile missing: %s", p)
    if not tiles:
        raise FileNotFoundError(
            "No DEM covers bbox %.4f,%.4f..%.4f,%.4f: the China DEM does not "
            "contain it and no MERIT tile (%s) is on disk. Pass --dem_path."
            % (lon_min, lat_min, lon_max, lat_max,
               ", ".join(sorted(seen)))
        )
    return tiles, bbox


def load_dem_elevation(lat, lon, extent_m, resolution_m=90,
                       allow_synthetic=False, dem_path=None):
    """Load DEM elevation values for the domain area.

    Tries:
      1. --dem_path / China DEM 90m / MERIT DEM 90m global tiles (rasterio)
      2. ki_tools_common.terrain.get_terrain (single-point fallback)

    Returns:
        function(x, y) → elevation array, suitable for domain.set_quantity
    """
    half = extent_m / 2.0
    m_per_deg_lon, m_per_deg_lat = latlon_to_utm(lat, lon)

    # Try rasterio for gridded DEM
    try:
        import rasterio
        from rasterio.merge import merge as rio_merge
        from scipy.interpolate import RegularGridInterpolator

        sources, bbox = resolve_dem_sources(lat, lon, extent_m, dem_path)
        lon_min, lat_min, lon_max, lat_max = bbox

        if True:
            if len(sources) == 1:
                src = rasterio.open(sources[0])
                try:
                    # Read window
                    row_min, col_min = src.index(lon_min, lat_max)
                    row_max, col_max = src.index(lon_max, lat_min)
                    row_min, row_max = min(row_min, row_max), max(row_min, row_max)
                    col_min, col_max = min(col_min, col_max), max(col_min, col_max)

                    # Clamp to valid range
                    row_min = max(0, row_min)
                    col_min = max(0, col_min)
                    row_max = min(src.height - 1, row_max)
                    col_max = min(src.width - 1, col_max)

                    win = rasterio.windows.Window(
                        col_min, row_min,
                        col_max - col_min + 1, row_max - row_min + 1,
                    )
                    elev_grid = src.read(1, window=win).astype(float)
                    nodata = src.nodata
                finally:
                    src.close()
            else:
                # Domain straddles a tile seam: mosaic just the bbox.
                handles = [rasterio.open(p) for p in sources]
                try:
                    mosaic, _tr = rio_merge(
                        handles, bounds=(lon_min, lat_min, lon_max, lat_max))
                    elev_grid = mosaic[0].astype(float)
                    nodata = handles[0].nodata
                finally:
                    for h in handles:
                        h.close()

            if nodata is not None:
                elev_grid[elev_grid == nodata] = np.nan
            # MERIT encodes ocean/void as large negatives as well as nodata.
            elev_grid[elev_grid < -400.0] = np.nan

            # Build coordinate arrays in local meters
            nrows, ncols = elev_grid.shape
            if nrows < 2 or ncols < 2:
                raise ValueError("DEM window too small")

            # Rows go from north to south in raster.
            # ANUGA evaluates set_quantity() callables in MESH-RELATIVE
            # coordinates (0..extent_m), NOT polygon coordinates
            # (-half..+half): create_domain_from_regions sets geo_reference
            # to the polygon min corner. Build the grid in that same frame,
            # else ~50%% of vertices fall outside and get extrapolated.
            x_coords = np.linspace(0.0, extent_m, ncols)
            y_coords = np.linspace(extent_m, 0.0, nrows)  # north to south

            # Fill NaN with nearest
            mask = np.isnan(elev_grid)
            if mask.all():
                raise ValueError(
                    "DEM window is entirely nodata for bbox "
                    "%.4f,%.4f..%.4f,%.4f" % (lon_min, lat_min, lon_max, lat_max)
                )
            if mask.any():
                from scipy.ndimage import distance_transform_edt
                indices = distance_transform_edt(mask, return_distances=False, return_indices=True)
                elev_grid = elev_grid[tuple(indices)]

            interp = RegularGridInterpolator(
                (y_coords[::-1], x_coords),  # must be ascending
                elev_grid[::-1, :],
                method="linear",
                bounds_error=False,
                fill_value=None,
            )

            _x_lo, _x_hi = float(x_coords.min()), float(x_coords.max())
            _y_lo, _y_hi = float(y_coords.min()), float(y_coords.max())
            _dem_lo = float(np.nanmin(elev_grid))
            _dem_hi = float(np.nanmax(elev_grid))

            def elevation_func(x, y):
                # Clamp to the DEM grid: scipy fill_value=None EXTRAPOLATES,
                # which fabricates +/-1000 m terrain outside the window.
                xq = np.clip(np.asarray(x, dtype=float), _x_lo, _x_hi)
                yq = np.clip(np.asarray(y, dtype=float), _y_lo, _y_hi)
                return interp(np.column_stack([yq, xq]))

            elevation_func.dem_range = (_dem_lo, _dem_hi)
            elevation_func.dem_sources = list(sources)
            elevation_func.bbox = bbox

            logger.info(f"Loaded DEM from {sources}: {nrows}x{ncols} cells, "
                        f"elev range {_dem_lo:.1f}-{_dem_hi:.1f} m")
            return elevation_func

    except Exception as e:
        # Elevation drives the wet/dry mask, so silently substituting a
        # synthetic slope fabricates terrain and invalidates depth and
        # inundation extent. Fail loud unless explicitly opted out.
        if not allow_synthetic:
            raise RuntimeError(
                "DEM load failed for declared DEM %s: %s. Refusing to "
                "substitute a synthetic sloped surface. Pass "
                "--allow_synthetic_dem only for smoke tests that do not "
                "score inundation extent."
                % (dem_path or "auto (China 90m / MERIT 90m tiles)", e)
            ) from e
        logger.warning(f"DEM loading via rasterio failed: {e}")

    # Fallback: single-point elevation with gentle slope
    try:
        from ki_tools_common.terrain import get_terrain
        terrain = get_terrain(lat, lon)
        base_elev = terrain["elevation"]
        slope = terrain["slope"]
    except Exception:
        base_elev = 20.0
        slope = 0.001

    logger.info(f"Using uniform elevation {base_elev:.1f} m with slope {slope:.4f}")

    def elevation_func(x, y):
        # Gentle slope from north to south (y direction)
        return base_elev + slope * y

    # Attach the analytic range so the caller's range guard still fires on
    # the synthetic path instead of silently skipping (getattr -> None).
    elevation_func.dem_range = (
        min(base_elev, base_elev + slope * extent_m),
        max(base_elev, base_elev + slope * extent_m),
    )
    return elevation_func


def load_rainfall_csv(csv_path):
    """Load rainfall time series from convert_forcing_to_anuga.py output.

    Returns:
        times: numpy array of time in seconds
        rates: numpy array of rainfall rate in m/s
    """
    times = []
    rates = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row["time_seconds"]))
            rates.append(float(row["rainfall_m_per_s"]))

    return np.array(times), np.array(rates)


def make_rainfall_function(times, rates):
    """Create a callable f(t) → rainfall_rate_m_s from time series arrays."""
    def rainfall_rate(t):
        if t <= times[0]:
            return float(rates[0])
        if t >= times[-1]:
            return float(rates[-1])
        idx = np.searchsorted(times, t, side="right") - 1
        return float(rates[idx])

    return rainfall_rate


def load_inflow_csv(csv_path):
    """Load an inflow hydrograph from build_inflow_hydrograph.py output.

    Returns:
        times: numpy array of time in seconds
        flows: numpy array of discharge in m^3/s
    """
    times = []
    flows = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row["time_seconds"]))
            flows.append(float(row["discharge_m3s"]))

    if len(times) < 2:
        raise ValueError(
            f"{csv_path}: need >= 2 hydrograph rows, got {len(times)}"
        )
    return np.array(times), np.array(flows)


def make_inflow_function(times, flows):
    """Create a callable f(t) → discharge_m3s for Inlet_operator.

    Inlet_operator.update_Q(t) calls Q(t) when Q is callable, so a plain
    step-interpolating closure drives a time-varying inlet. Held flat outside
    the record rather than extrapolated: linear extrapolation off the end of a
    hydrograph is how fabricated forcing gets in.
    """
    def inflow_rate(t):
        if t <= times[0]:
            return float(flows[0])
        if t >= times[-1]:
            return float(flows[-1])
        idx = np.searchsorted(times, t, side="right") - 1
        return float(flows[idx])

    return inflow_rate


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Validate run parameters."""
    errors = []

    if not (-90 <= args.lat <= 90):
        errors.append(f"Latitude out of range: {args.lat}")
    if not (-180 <= args.lon <= 180):
        errors.append(f"Longitude out of range: {args.lon}")
    if args.extent_m <= 0:
        errors.append(f"extent_m must be positive, got {args.extent_m}")
    if args.finaltime <= 0:
        errors.append(f"finaltime must be positive, got {args.finaltime}")
    if args.yieldstep <= 0:
        errors.append(f"yieldstep must be positive, got {args.yieldstep}")

    if args.forcing_csv and not os.path.isfile(args.forcing_csv):
        errors.append(f"Forcing CSV not found: {args.forcing_csv}")

    if args.inflow_csv:
        if not os.path.isfile(args.inflow_csv):
            errors.append(f"Inflow CSV not found: {args.inflow_csv}")
        if args.inlet_xy is None:
            errors.append("--inlet_xy is required when --inflow_csv is given")
        if args.inlet_radius_m <= 0:
            errors.append(
                f"inlet_radius_m must be positive, got {args.inlet_radius_m}"
            )

    if args.inlet_xy is not None:
        # Inlet coordinates are ABSOLUTE (polygon frame), i.e. metres from the
        # domain centre spanning -extent_m/2..+extent_m/2. This is NOT the
        # mesh-relative 0..extent_m frame that set_quantity() callables see --
        # anuga.Region resolves centres against absolute centroids. An inlet
        # placed in the wrong frame lands in a corner (silently partial) or
        # outside the mesh, so bound-check it here in the frame Region uses.
        half = args.extent_m / 2.0
        ix, iy = args.inlet_xy
        if abs(ix) > half or abs(iy) > half:
            errors.append(
                f"--inlet_xy ({ix}, {iy}) lies outside the domain "
                f"(+/-{half:.0f} m from centre, absolute frame). Give the "
                "inlet in metres from the domain centre, not mesh-relative."
            )
        elif args.inlet_radius_m > 0 and (
            abs(ix) + args.inlet_radius_m > half
            or abs(iy) + args.inlet_radius_m > half
        ):
            logger.warning(
                f"Inlet circle at ({ix}, {iy}) r={args.inlet_radius_m} m "
                f"extends past the domain edge (+/-{half:.0f} m); the inlet "
                "region will be clipped and inject over fewer triangles."
            )

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"{len(errors)} validation error(s)")


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------
def process(args):
    """Main pipeline: validate → setup domain → run → summarize."""

    # Step 1: Validate
    validate_inputs(args)

    import anuga

    os.makedirs(args.output_dir, exist_ok=True)

    # Step 2: Build domain
    logger.info(f"Creating mesh: {args.extent_m}m x {args.extent_m}m, "
                f"max triangle area = {args.max_area} m²")

    bounding_polygon = build_bounding_polygon(args.lat, args.lon, args.extent_m)

    domain = anuga.create_domain_from_regions(
        bounding_polygon,
        boundary_tags={
            "bottom": [0],
            "right": [1],
            "top": [2],
            "left": [3],
        },
        maximum_triangle_area=args.max_area,
    )

    domain.set_name("anuga_sim")
    domain.set_datadir(args.output_dir)
    domain.set_flow_algorithm("DE0")

    n_triangles = len(domain)
    logger.info(f"Mesh created: {n_triangles} triangles")

    # Step 3: Set elevation from DEM
    logger.info("Setting elevation from DEM...")
    elevation_func = load_dem_elevation(
        args.lat, args.lon, args.extent_m,
        allow_synthetic=args.allow_synthetic_dem,
        dem_path=args.dem_path,
    )
    domain.set_quantity("elevation", elevation_func)

    # Guard: fitted elevation must lie within the source DEM range. A frame or
    # extrapolation bug fabricates terrain and silently corrupts depth/extent.
    _rng = getattr(elevation_func, "dem_range", None)
    if _rng is not None:
        _el = np.asarray(
            domain.quantities["elevation"].get_values(location="centroids"),
            dtype=float,
        )
        if _el.min() < _rng[0] - 1.0 or _el.max() > _rng[1] + 1.0:
            raise ValueError(
                "Fitted elevation %.1f..%.1f m falls outside source DEM range "
                "%.1f..%.1f m - DEM interpolation frame/extrapolation bug."
                % (_el.min(), _el.max(), _rng[0], _rng[1])
            )
        logger.info(
            "Elevation fit OK: %.1f..%.1f m (DEM %.1f..%.1f m)"
            % (_el.min(), _el.max(), _rng[0], _rng[1])
        )

    # Step 4: Initial conditions — dry bed (stage = elevation)
    domain.set_quantity("stage", expression="elevation")
    domain.set_quantity("friction", args.manning_n)

    # Step 5: Boundary conditions
    # Transmissive at the outlet side, Reflective on the other 3 (upslope).
    # The outlet must face the direction the reach actually drains: the Huai
    # flows west->east, so an east-draining reach needs outlet_side='right'.
    # Leaving it on 'bottom' for such a reach walls off the true outlet and
    # ponds the inflow against a Reflective edge.
    Br = anuga.Reflective_boundary(domain)
    Bt = anuga.Transmissive_boundary(domain)
    boundary_map = {tag: Br for tag in ("bottom", "right", "top", "left")}
    boundary_map[args.outlet_side] = Bt
    domain.set_boundary(boundary_map)
    logger.info(f"Boundaries: Transmissive outlet on '{args.outlet_side}', "
                f"Reflective on the other 3 sides")

    # Step 6: Apply rainfall forcing
    if args.forcing_csv:
        logger.info(f"Loading rainfall from {args.forcing_csv}")
        rain_times, rain_rates = load_rainfall_csv(args.forcing_csv)
        rain_func = make_rainfall_function(rain_times, rain_rates)

        from anuga.operators.rate_operators import Rate_operator
        Rate_operator(domain, rate=rain_func, label="rainfall")
        logger.info(f"Rainfall applied: {len(rain_times)} timesteps, "
                    f"max rate {np.max(rain_rates):.2e} m/s")
    elif not args.inflow_csv:
        logger.warning("No forcing CSV provided — running with dry conditions only")

    # Step 6b: Apply riverine inflow via Inlet_operator (dag: "inflow
    # discharge", m^3/s). This is what makes a riverine event runnable at all;
    # rain-on-grid alone cannot reproduce a flood routed in from upstream.
    inflow_peak_m3s = None
    if args.inflow_csv:
        logger.info(f"Loading inflow hydrograph from {args.inflow_csv}")
        q_times, q_flows = load_inflow_csv(args.inflow_csv)
        inflow_func = make_inflow_function(q_times, q_flows)

        if q_times[-1] < args.finaltime:
            logger.warning(
                f"Hydrograph ends at t={q_times[-1]:.0f}s but finaltime is "
                f"{args.finaltime:.0f}s; the final discharge "
                f"{q_flows[-1]:.1f} m^3/s will be held flat for the "
                f"remaining {args.finaltime - q_times[-1]:.0f}s."
            )

        # anuga.Region resolves `center` against ABSOLUTE centroid coordinates
        # (see validate_inputs). Region raises if the circle intersects no
        # centroid, so a fully-misplaced inlet fails loud rather than
        # injecting nothing.
        inlet_region = anuga.Region(
            domain,
            center=(float(args.inlet_xy[0]), float(args.inlet_xy[1])),
            radius=float(args.inlet_radius_m),
        )
        n_inlet = (len(inlet_region.indices)
                   if inlet_region.indices is not None else n_triangles)
        if n_inlet == 0:
            raise ValueError(
                f"Inlet region at {tuple(args.inlet_xy)} r="
                f"{args.inlet_radius_m} m contains no triangles; no discharge "
                "would enter the domain."
            )

        from anuga.structures.inlet_operator import Inlet_operator
        Inlet_operator(domain, inlet_region, Q=inflow_func, label="inflow")

        inflow_peak_m3s = float(np.max(q_flows))
        logger.info(
            f"Inflow applied at ({args.inlet_xy[0]:.0f}, "
            f"{args.inlet_xy[1]:.0f}) over {n_inlet} triangles: "
            f"{len(q_times)} steps, Q {np.min(q_flows):.1f}.."
            f"{inflow_peak_m3s:.1f} m^3/s"
        )

    # Step 7: Run simulation
    logger.info(f"Running simulation: finaltime={args.finaltime}s, "
                f"yieldstep={args.yieldstep}s")
    t0 = time.time()

    for t in domain.evolve(yieldstep=args.yieldstep, finaltime=args.finaltime):
        if int(t) % max(1, int(args.finaltime / 10)) == 0:
            logger.info(f"  t = {t:.0f}s / {args.finaltime:.0f}s")

    elapsed = time.time() - t0

    # Merge parallel SWW files if needed
    try:
        domain.sww_merge(delete_old=True)
    except Exception:
        pass

    sww_path = os.path.join(args.output_dir, "anuga_sim.sww")
    logger.info(f"Simulation complete: {elapsed:.1f}s walltime")

    # Step 8: Write summary
    summary = {
        "lat": args.lat,
        "lon": args.lon,
        "extent_m": args.extent_m,
        "n_triangles": n_triangles,
        "max_area_m2": args.max_area,
        "manning_n": args.manning_n,
        "finaltime_s": args.finaltime,
        "yieldstep_s": args.yieldstep,
        "elapsed_s": round(elapsed, 1),
        "forcing_csv": args.forcing_csv,
        "outlet_side": args.outlet_side,
        "inflow_csv": args.inflow_csv,
        "inlet_xy": (list(args.inlet_xy) if args.inlet_xy is not None else None),
        "inlet_radius_m": (args.inlet_radius_m if args.inflow_csv else None),
        "inflow_peak_m3s": inflow_peak_m3s,
        "sww_output": sww_path,
        "sww_exists": os.path.isfile(sww_path),
        "dem_sources": list(getattr(elevation_func, "dem_sources", [])),
        "dem_range_m": list(getattr(elevation_func, "dem_range", []) or []),
        "dem_bbox_lonlat": list(getattr(elevation_func, "bbox", []) or []),
    }

    summary_path = os.path.join(args.output_dir, "run_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Summary written to {summary_path}")

    if not os.path.isfile(sww_path):
        logger.error(f"SWW output not found at {sww_path}")
        sys.exit(1)

    logger.info(f"Output: {sww_path} ({os.path.getsize(sww_path) / 1e6:.1f} MB)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Run ANUGA 2D shallow-water simulation with DEM and forcing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--lat", type=float, required=True,
                        help="Center latitude (degrees N)")
    parser.add_argument("--lon", type=float, required=True,
                        help="Center longitude (degrees E)")
    parser.add_argument("--extent_m", type=float, default=5000,
                        help="Domain extent in meters (default: 5000)")
    parser.add_argument("--max_area", type=float, default=10000,
                        help="Maximum triangle area in m² (default: 10000)")
    parser.add_argument("--manning_n", type=float, default=0.03,
                        help="Manning's roughness coefficient (default: 0.03)")
    parser.add_argument("--forcing_csv", default=None,
                        help="Path to rainfall_timeseries.csv from convert_forcing")
    parser.add_argument("--finaltime", type=float, default=86400,
                        help="Simulation duration in seconds (default: 86400 = 1 day)")
    parser.add_argument("--yieldstep", type=float, default=300,
                        help="Output interval in seconds (default: 300)")
    parser.add_argument("--output_dir", default=".",
                        help="Output directory (default: current)")
    parser.add_argument("--outlet_side", choices=["bottom", "right", "top", "left"],
                        default="bottom",
                        help="Domain edge carrying the Transmissive outlet; the "
                             "other 3 are Reflective. Must face the reach's "
                             "drainage direction (Huai drains east -> 'right')")
    parser.add_argument("--inflow_csv", default=None,
                        help="Inflow hydrograph CSV (time_seconds,discharge_m3s) "
                             "from build_inflow_hydrograph.py; applied via "
                             "Inlet_operator for riverine runs")
    parser.add_argument("--inlet_xy", type=float, nargs=2, default=None,
                        metavar=("X", "Y"),
                        help="Inlet centre in metres from the domain centre "
                             "(ABSOLUTE frame, +/-extent_m/2). Required with "
                             "--inflow_csv")
    parser.add_argument("--inlet_radius_m", type=float, default=2000.0,
                        help="Radius of the circular inlet region (m)")
    parser.add_argument("--inlet_latlon", type=float, nargs=2, default=None,
                        metavar=("LAT", "LON"),
                        help="Inlet position as lat/lon; converted to the "
                             "absolute frame with the same equirectangular "
                             "mapping the mesh uses. Alternative to --inlet_xy")
    parser.add_argument("--dem_path", default=None,
                        help="Explicit DEM GeoTIFF. Default: China 90m DEM "
                             "when the domain fits inside it, else the "
                             "overlapping MERIT DEM 90m global tiles")
    parser.add_argument("--allow_synthetic_dem", action="store_true",
                        help="Permit the synthetic sloped-surface fallback "
                             "when the DEM cannot be read (smoke tests "
                             "only; invalidates inundation extent)")

    args = parser.parse_args()

    if args.inlet_latlon is not None:
        if args.inlet_xy is not None:
            parser.error("Give --inlet_xy or --inlet_latlon, not both")
        x, y = latlon_to_domain_xy(args.lat, args.lon,
                                   args.inlet_latlon[0], args.inlet_latlon[1])
        args.inlet_xy = [x, y]
        logger.info("Inlet lat/lon (%.5f, %.5f) -> absolute frame "
                    "(%.0f, %.0f) m", args.inlet_latlon[0],
                    args.inlet_latlon[1], x, y)

    process(args)


if __name__ == "__main__":
    main()
