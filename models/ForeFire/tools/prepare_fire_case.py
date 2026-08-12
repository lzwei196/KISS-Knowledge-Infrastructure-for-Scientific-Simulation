#!/usr/bin/env python3
"""
prepare_fire_case.py — stage-0 tool: build a complete ForeFire case from an
observed fire perimeter (MTBS) plus global terrain / land-cover / wind data.

Before this tool existed, SKILL.md's pipeline listed stage 0 ("Configuration")
as *(manual)* and shipped no way to obtain any of its outputs, so every runner
had to hand-roll the domain box, the DEM warp, the fuel raster and the observed
perimeter — i.e. re-implement the four steps that decide whether the run is even
comparable to the observation. Those hand-rolled versions are exactly where the
silent errors live (wrong CRS, fuel index outside fuels.csv -> dt_009, fire
reaching the grid edge -> dt_021, obs perimeter left in geographic degrees while
the simulation is in UTM metres).

What it produces, in ONE output directory per fire:

    obs_perimeter.geojson   observed final perimeter, reprojected to the case UTM
    dem_utm.tif             MERIT DEM (90 m) warped to the case UTM grid
    fuel_utm.tif            Anderson fuel index derived from GLC_FCS30 30 m land cover
    case.json               domain corners, EPSG, resolution, ignition point,
                            mean wind vector, observed area, provenance

Downstream:  convert_fuel_params -> fuels.csv,
             convert_landscape_to_nc --dem_tif dem_utm.tif --fuel_tif fuel_utm.tif,
             run_forefire, parse_forefire_output, validate_spread.

Usage:
    python prepare_fire_case.py \\
        --mtbs_shp /path/mtbs_perims_DD.shp \\
        --event_id ID4294111360220120713 \\
        --outdir ./case_trapper_cabin

    python prepare_fire_case.py ... --list_region -119.5 40.0 -114.5 43.5 \\
        --min_acres 3000 --max_acres 12000 --year_range 2001 2021
"""

import argparse
import json
import math
import os
import subprocess
import sys
import urllib.request

import numpy as np

# --- default data sources (curated server index) ------------------------------
MERIT_DIR = "/mnt/datasets/MERIT_DEM"
GLCFCS30_DIR = "/mnt/datasets/vegetation/GLCFCS30"
NASA_POWER_HOURLY = "https://power.larc.nasa.gov/api/temporal/hourly/point"

# GLC_FCS30 land-cover class -> Anderson (1982) fuel-model index.
# Anderson indices must exist in fuels.csv or the engine reads past the fuel
# table (triplet dt_009); convert_fuel_params --source anderson13 emits 0-13.
GLCFCS30_TO_ANDERSON = {
    10: 1, 11: 1, 12: 2, 20: 1,                     # cropland -> short grass / grass+shrub
    51: 2, 52: 9, 61: 2, 62: 9, 60: 9, 50: 9,       # broadleaf: open -> grass+understory, closed -> hardwood litter
    71: 10, 72: 8, 81: 10, 82: 8, 70: 8, 80: 10,    # needleleaf: closed -> timber litter, open -> litter+understory
    91: 2, 92: 9, 90: 9,                            # mixed leaf forest
    120: 5, 121: 5, 122: 5,                         # shrubland -> brush
    130: 3,                                         # grassland -> tall grass
    140: 1,                                         # lichens / mosses
    150: 1, 152: 1, 153: 1,                         # sparse vegetation -> short grass
    180: 0, 181: 0, 182: 0, 183: 0, 184: 0,         # wetlands: saturated, non-burnable
    185: 0, 186: 0, 187: 0,
    190: 0, 200: 0, 201: 0, 202: 0, 210: 0, 220: 0, 250: 0,  # urban / bare / water / ice / fill
}
DEFAULT_FUEL = 1        # unmapped vegetated class -> short grass
NONBURNABLE = 0


def sh(cmd, timeout=3600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr[-600:]}")
    return r


def utm_epsg(lon, lat):
    zone = int((lon + 180.0) // 6.0) + 1
    return (32600 if lat >= 0 else 32700) + zone


def merit_tiles(w, s, e, n):
    """MERIT DEM tiles are 5x5 deg named by their SOUTH-WEST corner."""
    out = []
    for lat0 in range(int(math.floor(s / 5.0) * 5), int(math.floor(n / 5.0) * 5) + 1, 5):
        for lon0 in range(int(math.floor(w / 5.0) * 5), int(math.floor(e / 5.0) * 5) + 1, 5):
            ns = f"n{lat0:02d}" if lat0 >= 0 else f"s{abs(lat0):02d}"
            ew = f"e{lon0:03d}" if lon0 >= 0 else f"w{abs(lon0):03d}"
            p = os.path.join(MERIT_DIR, f"{ns}{ew}_dem.tif")
            if os.path.isfile(p):
                out.append(p)
    return out


def glcfcs30_tiles(w, s, e, n):
    """GLC_FCS30 tiles are 5x5 deg named by their NORTH-WEST corner."""
    out = []
    for lat1 in range(int(math.ceil(s / 5.0) * 5), int(math.ceil(n / 5.0) * 5) + 1, 5):
        for lon0 in range(int(math.floor(w / 5.0) * 5), int(math.floor(e / 5.0) * 5) + 1, 5):
            ew = f"E{lon0}" if lon0 >= 0 else f"W{abs(lon0)}"
            p = os.path.join(GLCFCS30_DIR, f"GLCFCS30_{ew}N{lat1}.tif")
            if os.path.isfile(p):
                out.append(p)
    return out


# ---------------------------------------------------------------- observations
def load_mtbs_event(shp, event_id):
    import fiona
    with fiona.open(shp) as src:
        crs = src.crs
        for ftr in src:
            if ftr["properties"]["Event_ID"] == event_id:
                return ftr["geometry"], dict(ftr["properties"]), crs
    raise RuntimeError(f"Event_ID {event_id} not found in {shp}")


def list_region(shp, bbox, min_ac, max_ac, years):
    """Deterministic candidate listing — no model output is consulted."""
    import fiona
    from shapely.geometry import shape
    rows = []
    with fiona.open(shp) as src:
        for f in src.filter(bbox=tuple(bbox)):
            p = f["properties"]
            if p.get("Incid_Type") != "Wildfire":
                continue
            ac = p.get("BurnBndAc") or 0
            if not (min_ac <= ac <= max_ac):
                continue
            d = str(p.get("Ig_Date") or "")
            if len(d) < 4 or not (years[0] <= int(d[:4]) <= years[1]):
                continue
            g = shape(f["geometry"])
            if g.geom_type != "Polygon" or not g.is_valid:
                continue
            rows.append({"event_id": p["Event_ID"], "name": p.get("Incid_Name"),
                         "acres": int(ac), "ig_date": d[:10],
                         "lat": float(p["BurnBndLat"]), "lon": float(p["BurnBndLon"])})
    rows.sort(key=lambda r: r["event_id"])       # deterministic, blind to skill
    return rows


# ---------------------------------------------------------------------- forcing
def nasa_power_wind_vector(lat, lon, ig_date, hours=24, start_hour_utc=18):
    """Mean 10 m wind VECTOR over the assumed active-burning window.

    `ki_tools_common.load_forcing.load_hourly_forcing('nasa_power', ...)` is the
    documented KI forcing path and IS called here (it is the source of record for
    the wind-speed climatology written into the provenance), but it returns wind
    SPEED only, and from WS2M. A fire-spread model needs a 10 m wind VECTOR, so
    the direction (WD10M) and the 10 m speed (WS10M) are read from the same NASA
    POWER hourly endpoint that load_forcing itself uses.

    NASA POWER WD10M is METEOROLOGICAL (the direction the wind blows FROM), so
    u = -WS*sin(WD), v = -WS*cos(WD).
    """
    from datetime import datetime, timedelta
    t0 = datetime.strptime(ig_date[:10], "%Y-%m-%d").replace(hour=start_hour_utc)
    t1 = t0 + timedelta(hours=hours)
    url = (f"{NASA_POWER_HOURLY}?parameters=WS10M,WD10M&community=RE"
           f"&longitude={lon:.4f}&latitude={lat:.4f}"
           f"&start={t0:%Y%m%d}&end={t1:%Y%m%d}&format=JSON")
    # NASA POWER stalls through the local proxy — go direct (see NASA POWER notes).
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    d = json.load(opener.open(url, timeout=180))
    par = d["properties"]["parameter"]
    ws, wd = par["WS10M"], par["WD10M"]
    us, vs, sp = [], [], []
    for k in sorted(ws):
        t = datetime.strptime(k, "%Y%m%d%H")
        if not (t0 <= t <= t1):
            continue
        s, a = ws[k], wd[k]
        if s is None or a is None or s < -900 or a < -900:
            continue
        rad = math.radians(a)
        us.append(-s * math.sin(rad)); vs.append(-s * math.cos(rad)); sp.append(s)
    if not sp:
        raise RuntimeError("NASA POWER returned no valid WS10M/WD10M in the window")
    u, v = float(np.mean(us)), float(np.mean(vs))
    return {"u_ms": round(u, 3), "v_ms": round(v, 3),
            "vector_speed_ms": round(math.hypot(u, v), 3),
            "scalar_mean_speed_ms": round(float(np.mean(sp)), 3),
            "max_speed_ms": round(float(np.max(sp)), 3),
            "n_hours": len(sp),
            "window_utc": [t0.isoformat() + "Z", t1.isoformat() + "Z"],
            "source": "NASA POWER hourly WS10M/WD10M"}


def loadforcing_wind_record(lat, lon, year):
    """Documented ki_tools_common path — kept as the provenance source of record."""
    try:
        from ki_tools_common.load_forcing import load_hourly_forcing
        d = load_hourly_forcing("nasa_power", lat, lon, year, year)
        w = np.asarray(d["wind_ms"], float)
        w = w[np.isfinite(w)]
        return {"ki_tools_common_load_forcing": "nasa_power hourly",
                "annual_mean_wind_ms": round(float(w.mean()), 3),
                "annual_max_wind_ms": round(float(w.max()), 3),
                "note": "load_forcing exposes WIND SPEED only (WS2M for hourly); "
                        "the wind VECTOR needed by ForeFire is taken from WS10M/WD10M."}
    except Exception as e:                                   # never fail the case
        return {"ki_tools_common_load_forcing_error": str(e)[:200]}


# ----------------------------------------------------------------- raster build
def build_dem(bbox_utm, epsg, res, out, w, s, e, n):
    if os.path.isfile(out):
        return out
    tiles = merit_tiles(w, s, e, n)
    if not tiles:
        raise RuntimeError(f"no MERIT DEM tile covers {w},{s},{e},{n}")
    gw = _gdalwarp()
    sh([gw, "-overwrite", "-q", "-t_srs", f"EPSG:{epsg}",
        "-te", *[str(x) for x in bbox_utm], "-tr", str(res), str(res),
        "-r", "bilinear", *tiles, out])
    return out


def build_fuel(bbox_utm, epsg, res, out, w, s, e, n):
    if os.path.isfile(out):
        return out
    import rasterio
    tiles = glcfcs30_tiles(w, s, e, n)
    if not tiles:
        raise RuntimeError(f"no GLC_FCS30 tile covers {w},{s},{e},{n}")
    lc = out.replace(".tif", "_landcover.tif")
    gw = _gdalwarp()
    sh([gw, "-overwrite", "-q", "-t_srs", f"EPSG:{epsg}",
        "-te", *[str(x) for x in bbox_utm], "-tr", str(res), str(res),
        "-r", "near", *tiles, lc])
    with rasterio.open(lc) as src:
        a = src.read(1)
        prof = src.profile
    fuel = np.full(a.shape, DEFAULT_FUEL, dtype=np.int32)
    for cls, idx in GLCFCS30_TO_ANDERSON.items():
        fuel[a == cls] = idx
    fuel[a == 0] = NONBURNABLE                       # gdal nodata fill
    prof.update(dtype="int32", count=1, nodata=0, compress="lzw")
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(fuel, 1)
    return out


def _gdalwarp():
    for c in ("/home/server/.local/bin/gdalwarp", "gdalwarp"):
        if os.path.isfile(c):
            return c
    import shutil
    g = shutil.which("gdalwarp")
    if not g:
        raise RuntimeError("gdalwarp not found")
    return g


# ------------------------------------------------------------------------ main
def build_case(args):
    from shapely.geometry import shape, mapping, Point
    from shapely.ops import transform as shp_transform
    from pyproj import Transformer

    geom, props, crs = load_mtbs_event(args.mtbs_shp, args.event_id)
    g_ll = shape(geom)
    lon_c, lat_c = g_ll.centroid.x, g_ll.centroid.y
    epsg = args.epsg or utm_epsg(lon_c, lat_c)

    src_crs = (crs or {}).get("init") if isinstance(crs, dict) else None
    src_epsg = src_crs or "EPSG:4269"                # MTBS ships NAD83 geographic
    fwd = Transformer.from_crs(src_epsg, f"EPSG:{epsg}", always_xy=True).transform
    g_utm = shp_transform(lambda x, y, z=None: fwd(x, y), g_ll)

    # Domain = observed extent + margin. dt_021: a FireNode that leaves the
    # loaded grid segfaults the engine, so the grid must outrun the fire.
    xmin, ymin, xmax, ymax = g_utm.bounds
    m = args.margin_m
    r = args.resolution
    bbox_utm = (math.floor((xmin - m) / r) * r, math.floor((ymin - m) / r) * r,
                math.ceil((xmax + m) / r) * r, math.ceil((ymax + m) / r) * r)

    inv = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True).transform
    cs = [inv(bbox_utm[0], bbox_utm[1]), inv(bbox_utm[2], bbox_utm[1]),
          inv(bbox_utm[0], bbox_utm[3]), inv(bbox_utm[2], bbox_utm[3])]
    w = min(c[0] for c in cs) - 0.05; e = max(c[0] for c in cs) + 0.05
    s = min(c[1] for c in cs) - 0.05; n = max(c[1] for c in cs) + 0.05

    os.makedirs(args.outdir, exist_ok=True)
    dem = build_dem(bbox_utm, epsg, r, os.path.join(args.outdir, "dem_utm.tif"), w, s, e, n)
    fuel = build_fuel(bbox_utm, epsg, r, os.path.join(args.outdir, "fuel_utm.tif"), w, s, e, n)

    obs_path = os.path.join(args.outdir, "obs_perimeter.geojson")
    with open(obs_path, "w") as f:
        json.dump({"type": "FeatureCollection",
                   "crs": {"type": "name", "properties": {"name": f"EPSG:{epsg}"}},
                   "features": [{"type": "Feature", "properties": props,
                                 "geometry": mapping(g_utm)}]}, f, default=str)

    ig_date = str(props.get("Ig_Date"))[:10]
    wind = nasa_power_wind_vector(lat_c, lon_c, ig_date,
                                  hours=args.burn_hours, start_hour_utc=args.start_hour_utc)
    wind.update(loadforcing_wind_record(lat_c, lon_c, int(ig_date[:4])))

    # Ignition point. MTBS publishes a final perimeter, NOT an ignition point.
    # The convention here is the most UPWIND interior point of the observed
    # footprint: project the perimeter onto the wind vector and take the minimum,
    # then pull it inside the polygon. With zero/near-zero wind this degenerates
    # to the centroid (radial spread), which is the correct limiting case.
    u, v = wind["u_ms"], wind["v_ms"]
    if math.hypot(u, v) < 0.5:
        ip = g_utm.representative_point()
    else:
        ux, uy = u / math.hypot(u, v), v / math.hypot(u, v)
        pts = np.asarray(g_utm.exterior.coords)
        proj = pts[:, 0] * ux + pts[:, 1] * uy
        p0 = pts[int(np.argmin(proj))]
        # step 5 % of the along-wind extent into the polygon so the seed is interior
        span = float(proj.max() - proj.min())
        cand = Point(p0[0] + ux * 0.05 * span, p0[1] + uy * 0.05 * span)
        ip = cand if g_utm.contains(cand) else g_utm.representative_point()

    case = {
        "event_id": args.event_id,
        "incident_name": props.get("Incid_Name"),
        "ig_date": ig_date,
        "obs_acres": props.get("BurnBndAc"),
        "obs_area_ha": round(g_utm.area / 1e4, 2),
        "epsg": epsg,
        "resolution_m": r,
        "domain_utm": {"sw": [bbox_utm[0], bbox_utm[1]], "ne": [bbox_utm[2], bbox_utm[3]],
                       "nx": int((bbox_utm[2] - bbox_utm[0]) / r),
                       "ny": int((bbox_utm[3] - bbox_utm[1]) / r)},
        "domain_lonlat": {"w": round(w, 4), "s": round(s, 4),
                          "e": round(e, 4), "n": round(n, 4)},
        "centroid_lonlat": [round(lon_c, 5), round(lat_c, 5)],
        "ignition_utm": [round(ip.x, 1), round(ip.y, 1)],
        # ForeFire's domain frame is LOCAL metres with the origin at the SW
        # corner (convert_landscape_to_nc writes SWx=SWy=0). startFire[loc=]
        # therefore takes LOCAL metres; feeding it absolute UTM ignites nothing
        # and returns exit code 0 with empty isochrones -- triplet dt_022.
        "ignition_local_m": [round(ip.x - bbox_utm[0], 1), round(ip.y - bbox_utm[1], 1)],
        "ignition_lonlat": [round(v_, 6) for v_ in inv(ip.x, ip.y)],
        "ignition_rule": ("most-upwind interior point of the observed perimeter "
                          "(centroid/representative point when |wind| < 0.5 m/s)"),
        "wind": wind,
        "margin_m": m,
        "files": {"dem_tif": dem, "fuel_tif": fuel, "obs_perimeter": obs_path},
        "fuel_source": "GLC_FCS30 30 m -> Anderson(1982) index (GLCFCS30_TO_ANDERSON)",
        "dem_source": "MERIT DEM v1.0.2 90 m",
        "obs_source": "MTBS burned-area boundaries",
    }
    return case, fuel


def validate_outputs(case, fuel_tif, max_fuel_index=13):
    """Postflight: the checks that prevent dt_009 / dt_021 / CRS mismatches."""
    import rasterio
    problems = []
    with rasterio.open(fuel_tif) as src:
        a = src.read(1)
    if int(a.max()) > max_fuel_index:
        problems.append(f"fuel index {int(a.max())} exceeds fuels.csv max {max_fuel_index} "
                        "(triplet dt_009: engine reads past the fuel table)")
    burnable = float((a > 0).mean())
    if burnable < 0.05:
        problems.append(f"only {burnable:.1%} of the domain is burnable — fire cannot spread")
    d = case["domain_utm"]
    if d["nx"] < 50 or d["ny"] < 50:
        problems.append(f"domain is only {d['nx']}x{d['ny']} cells — too small")
    case["fuel_burnable_fraction"] = round(burnable, 4)
    case["fuel_index_max"] = int(a.max())
    for p in problems:
        print(f"POSTFLIGHT WARNING: {p}", file=sys.stderr)
    case["postflight_warnings"] = problems
    return case


def main():
    ap = argparse.ArgumentParser(description="Build a ForeFire case from an MTBS fire")
    ap.add_argument("--mtbs_shp", required=True)
    ap.add_argument("--event_id")
    ap.add_argument("--outdir")
    ap.add_argument("--resolution", type=float, default=30.0)
    ap.add_argument("--margin_m", type=float, default=3000.0,
                    help="domain margin around the observed perimeter (dt_021)")
    ap.add_argument("--burn_hours", type=int, default=24,
                    help="assumed active-burning window for the wind average")
    ap.add_argument("--start_hour_utc", type=int, default=18)
    ap.add_argument("--epsg", type=int, default=None)
    ap.add_argument("--output_json", default=None)
    ap.add_argument("--list_region", nargs=4, type=float, metavar=("W", "S", "E", "N"))
    ap.add_argument("--min_acres", type=float, default=0)
    ap.add_argument("--max_acres", type=float, default=1e9)
    ap.add_argument("--year_range", nargs=2, type=int, default=[1984, 2024])
    args = ap.parse_args()

    if args.list_region:
        rows = list_region(args.mtbs_shp, args.list_region, args.min_acres,
                           args.max_acres, args.year_range)
        out = {"n": len(rows), "fires": rows}
        print(json.dumps(out, indent=2) if not args.output_json else f"{len(rows)} fires")
        if args.output_json:
            json.dump(out, open(args.output_json, "w"), indent=2)
        return

    if not (args.event_id and args.outdir):
        sys.exit("--event_id and --outdir are required unless --list_region is used")

    case, fuel = build_case(args)
    case = validate_outputs(case, fuel)
    path = args.output_json or os.path.join(args.outdir, "case.json")
    json.dump(case, open(path, "w"), indent=2)
    print(f"Case written: {path}")
    print(f"  {case['incident_name']} {case['event_id']} {case['ig_date']}  "
          f"obs {case['obs_area_ha']} ha")
    print(f"  domain {case['domain_utm']['nx']}x{case['domain_utm']['ny']} @ "
          f"{case['resolution_m']} m  EPSG:{case['epsg']}")
    print(f"  wind vector ({case['wind']['u_ms']}, {case['wind']['v_ms']}) m/s; "
          f"burnable {case.get('fuel_burnable_fraction')}")


if __name__ == "__main__":
    main()
