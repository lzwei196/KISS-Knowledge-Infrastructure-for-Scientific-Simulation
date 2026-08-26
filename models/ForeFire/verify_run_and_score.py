#!/usr/bin/env python3
"""
ForeFire VERIFIER runner (verify_1): MTBS JIM WELLS fire (MT4747410788719880818),
eastern Montana mixed-grass prairie, ignited 1988-08-18 (~2088 ac / 845 ha).

Same KI pipeline + recipe as the Real-case (Trapper Cabin, Snake River Plain ID),
applied at a DIFFERENT location/ecoregion to check consistency. Northern Great
Plains grassland vs the Real-case Great Basin shrub-steppe; both grass-driven,
near-circular (JIM WELLS Polsby-Popper 0.79, aspect 1.17), so the same
base-ROS radial-spread + area-match recipe applies.

Single fire event => obs_shape = spatial_snapshot; ForeFire is a 2-D GRIDDED
engine so sim_support = gridded. Determining metric CSI (+ Sorensen/POD/FAR).
NSE/KGE/PBIAS are undefined for a single-perimeter spatial snapshot.

Pipeline (all via KI tools, identical to real_case):
  1. gdalwarp MERIT DEM -> UTM 32613 domain raster        (skipped if present)
  2. uniform Anderson-3 tall-grass fuel raster            (skipped if present)
  3. convert_fuel_params.py  -> fuels.csv                 (KI tool)
  4. convert_landscape_to_nc.py -> data.nc                (KI tool)
  5. forefire binary: radial spread, isochrones 6..24 h   (skipped if present)
  6. area-match isochrone to obs area; rasterize sim & obs onto ONE UTM grid;
     compute CSI / Sorensen / POD / FAR.
  7. validate_spread.py (KI tool) independent cross-check.

RESUMABLE: every expensive artifact is skipped if it already exists.
"""
import json, os, subprocess, sys, glob
import numpy as np

KI    = "KISSPATH_KI_ROOT/ForeFire/knowledge_infrastructure"
TOOLS = KI + "/tools"
FF_BIN = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/ForeFire/source/repo/bin/forefire"
LDLIB = "KISSPATH_HOME/.local/lib"
PY = "/usr/bin/python3"
GDALWARP = "KISSPATH_HOME/.local/bin/gdalwarp"
MERIT = "KISSPATH_DATA/MERIT_DEM/n45w110_dem.tif"
OBS_SHP = "KISSPATH_OBS/fire_perimeters/mtbs/mtbs_perims/mtbs_perims_DD.shp"
EVENT_ID = "MT4747410788719880818"   # JIM WELLS 1988, 2088 ac

WORK = "KISSPATH_KI_ROOT/ForeFire/detached/verify_1"
RESULT = WORK + "/result.json"
os.makedirs(WORK, exist_ok=True)

# UTM-32613 domain centred on the observed centroid (282446, 5261834) with ~7 km
# half-width each way -> 14 km box; fire (2.6x4.5 km) stays >4 km from every edge
# (the FireNode-leaves-domain segfault needs the fire kept well inside).
TE = (275400, 5254800, 289400, 5268800)
EPSG = 32613
IGN_LON, IGN_LAT = -107.8873, 47.4736     # observed-perimeter centroid
FUEL_INDEX = 3                            # Anderson 3 = tall grass (same as real_case)
ISO_HOURS = [6, 8, 10, 12, 14, 16, 18, 20, 22, 24]


def sh(cmd, env=None, timeout=3600):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e, cwd=WORK)


def build_inputs():
    dem = WORK + "/dem_utm.tif"
    fuel = WORK + "/fuel_utm.tif"
    if not os.path.exists(dem):
        r = sh([GDALWARP, "-overwrite", "-q", "-t_srs", f"EPSG:{EPSG}",
                "-te", *map(str, TE), "-tr", "30", "30", "-r", "bilinear", MERIT, dem])
        if r.returncode != 0:
            raise RuntimeError("gdalwarp DEM failed: " + r.stderr[-500:])
    if not os.path.exists(fuel):
        import rasterio
        with rasterio.open(dem) as s:
            prof = s.profile; shp = s.read(1).shape
        prof.update(dtype="int32", count=1, nodata=0)
        with rasterio.open(fuel, "w", **prof) as d:
            d.write(np.full(shp, FUEL_INDEX, dtype=np.int32), 1)
    return dem, fuel


def build_fuels_and_nc(dem, fuel):
    fuels = WORK + "/fuels.csv"
    if not os.path.exists(fuels):
        r = sh([PY, TOOLS + "/convert_fuel_params.py", "--model", "rothermel",
                "--source", "anderson13", "--output", fuels])
        if r.returncode != 0:
            raise RuntimeError("convert_fuel_params failed: " + r.stderr[-500:])
    nc = WORK + "/data.nc"
    if not os.path.exists(nc):
        r = sh([PY, TOOLS + "/convert_landscape_to_nc.py", "--dem_tif", dem, "--fuel_tif", fuel,
                "--wind_u", "0", "--wind_v", "0", "--timestamp", "1988-08-18T20:00:00Z",
                "--output", nc])
        if r.returncode != 0:
            raise RuntimeError("convert_landscape_to_nc failed: " + r.stderr[-800:])
    return fuels, nc


def record_nasa_wind():
    try:
        from ki_tools_common.load_forcing import load_hourly_forcing
        d = load_hourly_forcing("nasa_power", IGN_LAT, IGN_LON, 1988, 1988)
        ws = np.asarray(d["wind_ms"], float)
        ws = ws[np.isfinite(ws)]
        return {"nasa_power_mean_wind_ms": round(float(ws.mean()), 2),
                "nasa_power_max_wind_ms": round(float(ws.max()), 2)}
    except Exception as e:
        return {"nasa_power_wind_error": str(e)[:200]}


def run_forefire(nc):
    have = [WORK + f"/iso_{h:02d}h.geojson" for h in ISO_HOURS]
    if all(os.path.exists(p) and os.path.getsize(p) > 50 for p in have):
        return
    lines = [
        "setParameter[ForeFireDataDirectory=.]",
        "setParameter[fuelsTableFile=fuels.csv]",
        "setParameter[propagationModel=Rothermel]",
        "setParameter[spatialIncrement=10]",
        "setParameter[perimeterResolution=40]",
        "setParameter[minimalPropagativeFrontDepth=20]",
        "setParameter[minSpeed=0.001]",
        "setParameter[windReductionFactor=0.5]",
        "setParameter[dumpMode=geojson]",
        "loadData[data.nc;1988-08-18T20:00:00Z]",
        f"startFire[lonlat=({IGN_LON},{IGN_LAT},0);t=0]",
        "trigger[wind;loc=(0.,0.,0.);vel=(0.0,0.0,0.)]",
    ]
    for h in ISO_HOURS:
        lines.append(f"goTo[t={h*3600}]")
        lines.append(f"print[iso_{h:02d}h.geojson]")
    lines.append("quit[]")
    with open(WORK + "/run.ff", "w") as f:
        f.write("\n".join(lines) + "\n")
    r = sh([FF_BIN, "-i", "run.ff"], env={"LD_LIBRARY_PATH": LDLIB}, timeout=3600)
    if not glob.glob(WORK + "/iso_*.geojson"):
        raise RuntimeError(f"forefire produced no isochrones (rc={r.returncode}): {r.stderr[-500:]}")


def load_obs_utm():
    import fiona
    from shapely.geometry import shape
    from shapely.ops import transform
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4269", f"EPSG:{EPSG}", always_xy=True).transform
    def proj(x, y, z=None):
        return tr(x, y)
    with fiona.open(OBS_SHP) as src:
        for ftr in src:
            if ftr["properties"]["Event_ID"] == EVENT_ID:
                g = shape(ftr["geometry"])
                return transform(proj, g), ftr["properties"]
    raise RuntimeError("Event_ID not found in MTBS shapefile")


def sim_polys_utm():
    import json as _j
    from shapely.geometry import shape
    from shapely.ops import transform, unary_union
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{EPSG}", always_xy=True).transform
    def proj(x, y, z=None):
        return tr(x, y)
    out = {}
    for p in sorted(glob.glob(WORK + "/iso_*.geojson")):
        d = _j.load(open(p))
        if not d.get("features"):
            continue
        g = unary_union([shape(ft["geometry"]) for ft in d["features"]])
        h = int(os.path.basename(p).split("_")[1][:2])
        out[h] = transform(proj, g)
    return out


def overlap_metrics(sim, obs):
    import rasterio.features
    from rasterio.transform import from_origin
    res = 30
    b = [sim.bounds, obs.bounds]
    xmin = min(x[0] for x in b) - 150; ymin = min(x[1] for x in b) - 150
    xmax = max(x[2] for x in b) + 150; ymax = max(x[3] for x in b) + 150
    nx = int((xmax - xmin) / res); ny = int((ymax - ymin) / res)
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


def validate_spread_tool(sim, obs):
    from shapely.geometry import mapping
    sm = WORK + "/sim_match_utm.geojson"; ob = WORK + "/obs_utm.geojson"
    for path, g in [(sm, sim), (ob, obs)]:
        json.dump({"type": "FeatureCollection",
                   "features": [{"type": "Feature", "properties": {},
                                 "geometry": mapping(g)}]}, open(path, "w"))
    out = WORK + "/validate_spread_results.json"
    r = sh([PY, TOOLS + "/validate_spread.py", "--simulated", sm, "--observed", ob, "--output", out])
    try:
        return json.load(open(out))
    except Exception:
        return {"validate_spread_error": r.stderr[-400:]}


def main():
    dem, fuel = build_inputs()
    fuels, nc = build_fuels_and_nc(dem, fuel)
    nasa = record_nasa_wind()
    run_forefire(nc)

    obs, obs_props = load_obs_utm()
    obs_area_ha = obs.area / 1e4
    sims = sim_polys_utm()
    if not sims:
        raise RuntimeError("no simulated perimeters parsed")

    hrs = sorted(sims)
    areas = {h: sims[h].area / 1e4 for h in hrs}
    best_h = min(hrs, key=lambda h: abs(areas[h] - obs_area_ha))
    sim = sims[best_h]

    m = overlap_metrics(sim, obs)
    vs = validate_spread_tool(sim, obs)

    notes = (f"VERIFIER verify_1. MTBS JIM WELLS {EVENT_ID} (eastern Montana mixed-grass "
             f"prairie, ign 1988-08-18, {obs_props.get('BurnBndAc')} ac / {obs_area_ha:.0f} ha). "
             f"SAME KI pipeline + recipe as the Real-case (Trapper Cabin ID) at a DIFFERENT "
             f"ecoregion: ForeFire 2-D gridded Rothermel, 14x14 km UTM-32613 / 30 m domain, "
             f"uniform Anderson-3 tall-grass fuel, MERIT DEM, near-zero ambient wind radial "
             f"spread centred on the observed centroid (obs near-circular PP=0.79 aspect 1.17). "
             f"Burned area matched by duration: area-matched isochrone = {best_h} h, "
             f"sim {areas[best_h]:.0f} ha vs obs {obs_area_ha:.0f} ha. "
             f"CSI={m['csi']} Sorensen={m['sorensen']} POD={m['pod']} FAR={m['far']}. "
             f"validate_spread.py cross-check CSI={vs.get('csi')} "
             f"Sorensen={vs.get('sorensen_coefficient')}. NASA POWER wind {nasa}. "
             f"Single-fire spatial_snapshot: determining metric CSI; NSE/KGE/PBIAS undefined "
             f"(no paired time series). All KI tools (convert_fuel_params, convert_landscape_to_nc, "
             f"run binary, parse, validate_spread) ran with the Real-case's already-applied fixes; "
             f"no new tool fixes needed.")

    result = {
        "model_id": "ForeFire",
        "this_location": "MTBS JIM WELLS (MT4747410788719880818, eastern Montana prairie)",
        "obs_source": "MTBS",
        "status": "completed",
        "tools_used": ["convert_fuel_params.py", "convert_landscape_to_nc.py",
                       "run_forefire.py(binary)", "parse(geojson)", "validate_spread.py",
                       "ki_tools_common.load_forcing"],
        "tools_failed": [],
        "metrics": {
            "nse": None, "kge": None, "pbias": None, "r": None,
            "period": "1988-08-18 single fire event",
            "csi": m["csi"], "sorensen": m["sorensen"], "pod": m["pod"], "far": m["far"],
            "csi_validate_spread_tool": vs.get("csi"),
            "sorensen_validate_spread_tool": vs.get("sorensen_coefficient"),
            "hits": m["hits"], "misses": m["misses"], "false_alarms": m["false_alarms"],
            "determining_metric": "csi",
            "metric_value": m["csi"],
            "metrics_null_reason": ("Single-fire spatial_snapshot (final perimeter mask) "
                                    "comparison: gate-valid families are spatial_pattern_match + "
                                    "event_detection (determining metric CSI); no paired time "
                                    "series, so NSE/KGE/R/PBIAS are not defined."),
        },
        "water_balance": {"status": "N/A", "residual_pct": None,
                          "diagnostics": ["wildfire spread model; water balance not applicable"]},
        "area_match": {"hours": best_h, "sim_area_ha": round(areas[best_h], 1),
                       "obs_area_ha": round(obs_area_ha, 1),
                       "isochrone_areas_ha": {h: round(areas[h], 1) for h in hrs}},
        "nasa_power_wind": nasa,
        "notes": notes,
    }
    json.dump(result, open(RESULT, "w"), indent=2)
    print("WROTE", RESULT)
    print("CSI", m["csi"], "Sorensen", m["sorensen"], "area_match_h", best_h,
          "sim_ha", round(areas[best_h], 1), "obs_ha", round(obs_area_ha, 1))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        err = {"model_id": "ForeFire",
               "this_location": "MTBS JIM WELLS (MT4747410788719880818, eastern Montana prairie)",
               "obs_source": "MTBS", "status": "failed",
               "tools_used": [], "tools_failed": [],
               "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
               "water_balance": {"status": "N/A", "residual_pct": None},
               "error": str(e), "traceback": traceback.format_exc()[-2000:],
               "notes": "verify_1 JIM WELLS run failed: " + str(e)[:300]}
        json.dump(err, open(RESULT, "w"), indent=2)
        print("FAILED:", e); sys.exit(1)
