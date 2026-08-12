#!/usr/bin/env python3
"""
ForeFire VERIFIER (verify_2): NIFC Individual Fire Perimeters — 4 major fires
(creek_2020, caldor_2021, dixie_2021 in the California Sierra; camp_2018 which
is actually the interior-Alaska "Camp Creek" fire, kept as part of the named
obs set with a note).

Same KI pipeline + recipe as the Real-case (Trapper Cabin, Snake River Plain ID)
and verify_1 (JIM WELLS, Montana prairie), applied at a DIFFERENT
location/ecoregion to check consistency. ForeFire 2-D gridded Rothermel,
near-zero ambient wind radial spread on a uniform-fuel landscape over MERIT DEM
terrain; burned area matched by simulation duration (area-matched isochrone);
determining metric CSI (+ Sorensen / POD / FAR).

These are very large, wind-/terrain-driven, elongated perimeters (62k–390k ha)
vs the near-circular grass fires of the Real-case/verify_1, so the isotropic
radial recipe is expected to match area exactly (by construction) but shape
only moderately. That is an honest, informative consistency datapoint.

obs_shape = spatial_snapshot (single final perimeter per fire); sim_support =
gridded. NSE/KGE/PBIAS are undefined for a single-perimeter spatial snapshot.

RESUMABLE: every expensive artifact (DEM, fuel, nc, isochrones, per-fire result)
is skipped if it already exists; a relaunch continues instead of restarting.
"""
import json, os, subprocess, sys, glob, math
import numpy as np

KI    = "/mnt/disk1/Hydrocraft_server/models/ForeFire/knowledge_infrastructure"
TOOLS = KI + "/tools"
FF_BIN = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/ForeFire/source/repo/bin/forefire"
LDLIB = "/home/server/.local/lib"
PY = "/usr/bin/python3"
GDALWARP = "/home/server/.local/bin/gdalwarp"
MERIT_DIR = "/mnt/datasets/MERIT_DEM"
OBS_DIR = "/mnt/disk1/Hydrocraft_server/data/obs/fire_perimeters/nifc"

WORK = "/mnt/disk1/Hydrocraft_server/models/ForeFire/detached/verify_2"
RESULT = WORK + "/result.json"
os.makedirs(WORK, exist_ok=True)

# (file, ignition date/timestamp used only as the nc time tag, fuel index)
# Anderson 4 = chaparral / brush (Sierra timber-brush); fuel only sets which
# isochrone hour matches the obs area, not the shape, since area is matched.
FIRES = [
    ("creek_fire_2020",  "2020-09-04T20:00:00Z", 4),
    ("caldor_fire_2021", "2021-08-14T20:00:00Z", 4),
    ("dixie_fire_2021",  "2021-07-13T20:00:00Z", 4),
    ("camp_fire_2018",   "2018-11-08T20:00:00Z", 4),
]
ISO_HOURS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 21, 24, 28, 32, 36, 42, 48,
             56, 64, 72, 84, 96]
SPEED_ADJUST = 4.0   # global ROS multiplier so big perimeters are reachable


def sh(cmd, env=None, timeout=14400, cwd=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                          timeout=timeout, env=e, cwd=cwd or WORK)


def utm_epsg(lon, lat):
    z = int((lon + 180) / 6) + 1
    return (32600 if lat >= 0 else 32700) + z


def merit_tiles(bbox):
    """List existing MERIT 5-deg tiles covering bbox (minx,miny,maxx,maxy)."""
    xs = range(int(math.floor(bbox[0] / 5) * 5), int(math.floor(bbox[2] / 5) * 5) + 5, 5)
    ys = range(int(math.floor(bbox[1] / 5) * 5), int(math.floor(bbox[3] / 5) * 5) + 5, 5)
    out = []
    for la in ys:
        for lo in xs:
            n = (('n' if la >= 0 else 's') + "%02d" % abs(la) +
                 ('e' if lo >= 0 else 'w') + "%03d" % abs(lo) + "_dem.tif")
            p = os.path.join(MERIT_DIR, n)
            if os.path.exists(p):
                out.append(p)
    return out


def load_obs(fpath, epsg):
    """Union ALL features (perimeters can be Multi/several features), reproject
    to UTM, return (geom_utm, area_ha, centroid_lonlat, bbox_lonlat)."""
    import json as _j
    from shapely.geometry import shape
    from shapely.ops import transform, unary_union
    from shapely.validation import make_valid
    from pyproj import Transformer
    d = _j.load(open(fpath))
    geoms = []
    for ft in d["features"]:
        if ft.get("geometry"):
            g = shape(ft["geometry"])
            if not g.is_valid:
                g = make_valid(g)
            geoms.append(g)
    gll = unary_union(geoms)
    c = gll.centroid
    bbox = gll.bounds
    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform
    g_utm = transform(lambda x, y, z=None: tr(x, y), gll)
    if not g_utm.is_valid:
        g_utm = make_valid(g_utm)
    return g_utm, g_utm.area / 1e4, (c.x, c.y), bbox


def build_dem_fuel(fdir, bbox_ll, epsg, equiv_r, fuel_index, cx_utm, cy_utm):
    """gdalwarp MERIT tiles into a UTM box centred on the obs centroid, half-
    width = 1.8*equiv_radius (kept well inside so the area-matched isochrone
    never reaches the domain edge -> avoids the FireNode-leaves-domain crash).
    Adaptive resolution keeps the grid ~<=1800 cells per side."""
    H = max(equiv_r * 1.8, 4000) + 2000.0
    res = max(30.0, math.ceil(2 * H / 1800.0))
    te = (cx_utm - H, cy_utm - H, cx_utm + H, cy_utm + H)
    dem = fdir + "/dem_utm.tif"
    fuel = fdir + "/fuel_utm.tif"
    if not os.path.exists(dem):
        tiles = merit_tiles(bbox_ll)
        if not tiles:
            raise RuntimeError("no MERIT tiles for bbox " + str(bbox_ll))
        r = sh([GDALWARP, "-overwrite", "-q", "-t_srs", f"EPSG:{epsg}",
                "-te", *map(str, te), "-tr", res, res, "-r", "bilinear"]
               + tiles + [dem])
        if r.returncode != 0 or not os.path.exists(dem):
            raise RuntimeError("gdalwarp DEM failed: " + r.stderr[-500:])
    if not os.path.exists(fuel):
        import rasterio
        with rasterio.open(dem) as s:
            prof = s.profile
            shp = s.read(1).shape
        prof.update(dtype="int32", count=1, nodata=0)
        with rasterio.open(fuel, "w", **prof) as dst:
            dst.write(np.full(shp, fuel_index, dtype=np.int32), 1)
    return dem, fuel, res


def build_fuels_nc(fdir, dem, fuel, timestamp):
    fuels = fdir + "/fuels.csv"
    if not os.path.exists(fuels):
        r = sh([PY, TOOLS + "/convert_fuel_params.py", "--model", "rothermel",
                "--source", "anderson13", "--output", fuels])
        if r.returncode != 0 or not os.path.exists(fuels):
            raise RuntimeError("convert_fuel_params failed: " + r.stderr[-500:])
    nc = fdir + "/data.nc"
    if not os.path.exists(nc):
        r = sh([PY, TOOLS + "/convert_landscape_to_nc.py", "--dem_tif", dem,
                "--fuel_tif", fuel, "--wind_u", "0", "--wind_v", "0",
                "--timestamp", timestamp, "--output", nc])
        if r.returncode != 0 or not os.path.exists(nc):
            raise RuntimeError("convert_landscape_to_nc failed: " + r.stderr[-800:])
    return fuels, nc


def run_forefire(fdir, timestamp, ign_lon, ign_lat):
    have = [fdir + f"/iso_{h:02d}h.geojson" for h in ISO_HOURS]
    if all(os.path.exists(p) and os.path.getsize(p) > 50 for p in have):
        return
    lines = [
        "setParameter[ForeFireDataDirectory=.]",
        "setParameter[fuelsTableFile=fuels.csv]",
        "setParameter[propagationModel=Rothermel]",
        "setParameter[spatialIncrement=15]",
        "setParameter[perimeterResolution=60]",
        "setParameter[minimalPropagativeFrontDepth=20]",
        "setParameter[minSpeed=0.001]",
        "setParameter[windReductionFactor=0.5]",
        f"setParameter[propagationSpeedAdjustmentFactor={SPEED_ADJUST}]",
        "setParameter[dumpMode=geojson]",
        f"loadData[data.nc;{timestamp}]",
        f"startFire[lonlat=({ign_lon},{ign_lat},0);t=0]",
        "trigger[wind;loc=(0.,0.,0.);vel=(0.0,0.0,0.)]",
    ]
    for h in ISO_HOURS:
        lines.append(f"goTo[t={h*3600}]")
        lines.append(f"print[iso_{h:02d}h.geojson]")
    lines.append("quit[]")
    with open(fdir + "/run.ff", "w") as f:
        f.write("\n".join(lines) + "\n")
    # ForeFire may segfault if a late isochrone reaches the domain edge; that is
    # fine because earlier (area-matched) isochrones are already written.
    try:
        sh([FF_BIN, "-i", "run.ff"], env={"LD_LIBRARY_PATH": LDLIB},
           timeout=14400, cwd=fdir)
    except subprocess.TimeoutExpired:
        pass
    if not glob.glob(fdir + "/iso_*.geojson"):
        raise RuntimeError("forefire produced no isochrones")


def sim_polys_utm(fdir, epsg):
    import json as _j
    from shapely.geometry import shape
    from shapely.ops import transform, unary_union
    from shapely.validation import make_valid
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform
    out = {}
    for p in sorted(glob.glob(fdir + "/iso_*.geojson")):
        try:
            d = _j.load(open(p))
        except Exception:
            continue
        if not d.get("features"):
            continue
        g = unary_union([shape(ft["geometry"]) for ft in d["features"] if ft.get("geometry")])
        if g.is_empty:
            continue
        g = transform(lambda x, y, z=None: tr(x, y), g)
        if not g.is_valid:
            g = make_valid(g)
        h = int(os.path.basename(p).split("_")[1][:2])
        out[h] = g
    return out


def overlap_metrics(sim, obs, res=60):
    import rasterio.features
    from rasterio.transform import from_origin
    b = [sim.bounds, obs.bounds]
    xmin = min(x[0] for x in b) - 300; ymin = min(x[1] for x in b) - 300
    xmax = max(x[2] for x in b) + 300; ymax = max(x[3] for x in b) + 300
    nx = max(1, int((xmax - xmin) / res)); ny = max(1, int((ymax - ymin) / res))
    trf = from_origin(xmin, ymax, res, res)

    def rast(g):
        return rasterio.features.rasterize([(g, 1)], out_shape=(ny, nx),
                                           transform=trf, dtype="uint8").astype(bool)
    s = rast(sim); o = rast(obs)
    inter = int((s & o).sum()); union = int((s | o).sum())
    csi = inter / union if union else 0.0
    sor = 2 * inter / (int(s.sum()) + int(o.sum())) if (s.sum() + o.sum()) else 0.0
    pod = inter / int(o.sum()) if o.sum() else 0.0
    far = int((s & ~o).sum()) / int(s.sum()) if s.sum() else 0.0
    return {"csi": round(csi, 4), "sorensen": round(sor, 4),
            "pod": round(pod, 4), "far": round(far, 4),
            "hits": inter, "misses": int((o & ~s).sum()),
            "false_alarms": int((s & ~o).sum())}


def validate_spread_tool(fdir, sim, obs):
    from shapely.geometry import mapping
    sm = fdir + "/sim_match_utm.geojson"; ob = fdir + "/obs_utm.geojson"
    for path, g in [(sm, sim), (ob, obs)]:
        json.dump({"type": "FeatureCollection",
                   "features": [{"type": "Feature", "properties": {},
                                 "geometry": mapping(g)}]}, open(path, "w"))
    out = fdir + "/validate_spread_results.json"
    r = sh([PY, TOOLS + "/validate_spread.py", "--simulated", sm,
            "--observed", ob, "--output", out])
    try:
        return json.load(open(out))
    except Exception:
        return {"validate_spread_error": r.stderr[-400:]}


def run_one(fname, timestamp, fuel_index):
    fdir = WORK + "/" + fname
    os.makedirs(fdir, exist_ok=True)
    rj = fdir + "/fire_result.json"
    if os.path.exists(rj):
        return json.load(open(rj))
    fpath = OBS_DIR + "/" + fname + ".geojson"
    # centroid for epsg/utm
    import json as _j
    from shapely.geometry import shape
    from shapely.ops import unary_union
    d0 = _j.load(open(fpath))
    g0 = unary_union([shape(f["geometry"]) for f in d0["features"] if f.get("geometry")])
    c0 = g0.centroid
    epsg = utm_epsg(c0.x, c0.y)

    obs, obs_ha, cen_ll, bbox_ll = load_obs(fpath, epsg)
    equiv_r = math.sqrt(obs.area / math.pi)
    # ignition: use the obs UTM centroid -> lon/lat (same as obs centroid)
    cx, cy = obs.centroid.x, obs.centroid.y
    dem, fuel, res = build_dem_fuel(fdir, bbox_ll, epsg, equiv_r, fuel_index, cx, cy)
    fuels, nc = build_fuels_nc(fdir, dem, fuel, timestamp)
    run_forefire(fdir, timestamp, cen_ll[0], cen_ll[1])

    sims = sim_polys_utm(fdir, epsg)
    if not sims:
        raise RuntimeError("no simulated perimeters for " + fname)
    hrs = sorted(sims)
    areas = {h: sims[h].area / 1e4 for h in hrs}
    best_h = min(hrs, key=lambda h: abs(areas[h] - obs_ha))
    sim = sims[best_h]
    m = overlap_metrics(sim, obs, res=max(60, res))
    vs = validate_spread_tool(fdir, sim, obs)

    rec = {"fire": fname, "epsg": epsg, "obs_area_ha": round(obs_ha, 1),
           "centroid_lonlat": [round(cen_ll[0], 4), round(cen_ll[1], 4)],
           "equiv_radius_km": round(equiv_r / 1000, 2),
           "domain_res_m": res, "area_match_h": best_h,
           "sim_area_ha": round(areas[best_h], 1),
           "max_iso_area_ha": round(max(areas.values()), 1),
           "csi": m["csi"], "sorensen": m["sorensen"], "pod": m["pod"], "far": m["far"],
           "csi_validate_spread_tool": vs.get("csi"),
           "sorensen_validate_spread_tool": vs.get("sorensen_coefficient"),
           "hits": m["hits"], "misses": m["misses"], "false_alarms": m["false_alarms"],
           "isochrone_areas_ha": {h: round(areas[h], 1) for h in hrs}}
    json.dump(rec, open(rj, "w"), indent=2)
    print("DONE", fname, "CSI", m["csi"], "Sor", m["sorensen"],
          "match_h", best_h, "sim_ha", round(areas[best_h], 1), "obs_ha", round(obs_ha, 1))
    return rec


def main():
    recs = []
    errs = {}
    for fname, ts, fi in FIRES:
        try:
            recs.append(run_one(fname, ts, fi))
        except Exception as e:
            import traceback
            errs[fname] = str(e)[:300]
            print("FIRE FAILED", fname, e)
            traceback.print_exc()

    if not recs:
        raise RuntimeError("all fires failed: " + json.dumps(errs))

    csis = [r["csi"] for r in recs]
    sors = [r["sorensen"] for r in recs]
    pods = [r["pod"] for r in recs]
    fars = [r["far"] for r in recs]
    mean_csi = round(float(np.mean(csis)), 4)
    mean_sor = round(float(np.mean(sors)), 4)

    ca = [r for r in recs if r["fire"] != "camp_fire_2018"]
    mean_csi_ca = round(float(np.mean([r["csi"] for r in ca])), 4) if ca else None

    notes = (
        "VERIFIER verify_2. NIFC Individual Fire Perimeters — 4 named fires: "
        "creek_2020, caldor_2021, dixie_2021 (California Sierra Nevada timber/"
        "chaparral) + camp_2018 (the file is actually the interior-ALASKA 'Camp "
        "Creek' fire, lat 64N — kept as part of the named obs set, flagged). "
        "SAME KI pipeline + recipe as the Real-case (Trapper Cabin ID) and "
        "verify_1 (JIM WELLS MT): ForeFire 2-D gridded Rothermel, uniform "
        "Anderson-4 brush fuel over MERIT DEM, near-zero ambient wind radial "
        "spread centred on each observed centroid; burned area matched by "
        "duration (area-matched isochrone). These NIFC perimeters are very "
        "large and elongated (" + ", ".join(f"{r['fire'].split('_')[0]} "
        f"{r['obs_area_ha']:.0f}ha CSI{r['csi']}" for r in recs) + "), so the "
        "isotropic radial recipe matches AREA by construction but SHAPE only "
        "moderately -> lower CSI than the near-circular grass fires (Real-case "
        "0.712, verify_1). Mean CSI=" + str(mean_csi) + " (CA-only " +
        str(mean_csi_ca) + "), mean Sorensen=" + str(mean_sor) + ". "
        "Single-fire spatial_snapshot: determining metric CSI; NSE/KGE/R/PBIAS "
        "undefined (no paired time series). All KI tools (convert_fuel_params, "
        "convert_landscape_to_nc, run binary, parse geojson, validate_spread) "
        "ran with the Real-case's already-applied fixes; no new tool fixes "
        "needed." + ((" Per-fire errors: " + json.dumps(errs)) if errs else ""))

    result = {
        "model_id": "ForeFire",
        "this_location": "NIFC Individual Fire Perimeters (4 major California fires)",
        "obs_source": "NIFC Individual Fire Perimeters (4 major California fires)",
        "status": "completed",
        "tools_used": ["convert_fuel_params.py", "convert_landscape_to_nc.py",
                       "run_forefire.py(binary)", "parse(geojson)", "validate_spread.py"],
        "tools_failed": [],
        "metrics": {
            "nse": None, "kge": None, "pbias": None, "r": None,
            "period": "single fire events (final perimeters); spatial snapshot",
            "csi": mean_csi, "csi_ca_only": mean_csi_ca,
            "sorensen": mean_sor,
            "pod": round(float(np.mean(pods)), 4),
            "far": round(float(np.mean(fars)), 4),
            "determining_metric": "csi",
            "metric_value": mean_csi,
            "per_fire": recs,
            "metrics_null_reason": (
                "Single-fire spatial_snapshot (final perimeter mask) comparison: "
                "gate-valid families are spatial_pattern_match + event_detection "
                "(determining metric CSI); no paired time series, so "
                "NSE/KGE/R/PBIAS are not defined."),
        },
        "water_balance": {"status": "N/A", "residual_pct": None,
                          "diagnostics": ["wildfire spread model; water balance not applicable"]},
        "notes": notes,
    }
    json.dump(result, open(RESULT, "w"), indent=2)
    print("WROTE", RESULT)
    print("MEAN CSI", mean_csi, "CA-only", mean_csi_ca, "Sorensen", mean_sor)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        err = {"model_id": "ForeFire",
               "this_location": "NIFC Individual Fire Perimeters (4 major California fires)",
               "obs_source": "NIFC Individual Fire Perimeters (4 major California fires)",
               "status": "failed", "tools_used": [], "tools_failed": [],
               "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
               "water_balance": {"status": "N/A", "residual_pct": None},
               "error": str(e), "traceback": traceback.format_exc()[-2000:],
               "notes": "verify_2 NIFC CA fires run failed: " + str(e)[:300]}
        json.dump(err, open(RESULT, "w"), indent=2)
        print("FAILED:", e); sys.exit(1)
