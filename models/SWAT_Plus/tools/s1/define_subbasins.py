#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      define_subbasins
Stage:        s1_watershed_delineation
Description:  Generate subbasin-level connectivity and channel definitions for SWAT+.

Inputs:
  - subbasin_shapefile: Subbasin boundaries from delineate_watershed
  - dem_path: Pit-filled DEM
  - stream_shapefile: Stream network
  - output_dir: TxtInOut directory

Outputs:
  - chandeg.con: Channel connectivity
  - rout_unit.con: Routing unit connectivity

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import logging
import json
from pathlib import Path

SUBBASIN_SHP = ""
DEM_PATH = ""
STREAM_SHP = ""
OUTPUT_DIR = ""
CHANNEL_TOPOLOGY = ""

if len(sys.argv) >= 5:
    SUBBASIN_SHP = sys.argv[1]
    DEM_PATH = sys.argv[2]
    STREAM_SHP = sys.argv[3]
    OUTPUT_DIR = sys.argv[4]
if len(sys.argv) >= 6:
    # Optional: channel_topology.json from tools/s1/build_channel_topology.py
    CHANNEL_TOPOLOGY = sys.argv[5]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    for path, name in [(SUBBASIN_SHP, "Subbasin shapefile"), (DEM_PATH, "DEM"), (STREAM_SHP, "Stream shapefile")]:
        if not path or not Path(path).exists():
            errors.append(f"{name} not found: {path}")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def load_topology(sub_ids):
    """Load the flow-network channel cascade, if one was supplied.

    Returns a dict {channel_id: downstream_id|None}, or None ONLY when no
    topology was requested at all (argv[5] absent) -- in which case the caller
    emits the loud unrouted-deck warning in process().

    FALLBACK DISCIPLINE (do not loosen): a topology that WAS supplied but is
    missing, unparseable, mismatched or misaligned is a hard failure (exit 2),
    never a silent degradation to hd_id=0. An operator who asked for a routed
    cascade must not be handed an unrouted deck that still exits 0.
    """
    if not CHANNEL_TOPOLOGY:
        return None

    def fatal(msg):
        logger.error(msg)
        logger.error(f"A channel topology WAS supplied ({CHANNEL_TOPOLOGY}), so "
                     "this is fatal: refusing to silently write hd_id=0 for every "
                     "channel. Rebuild it with tools/s1/build_channel_topology.py "
                     "from the SAME subbasin partition, or omit argv[5] if you "
                     "knowingly want an unrouted deck.")
        sys.exit(2)

    p = Path(CHANNEL_TOPOLOGY)
    if not p.exists():
        fatal(f"Channel topology not found: {p}")
    try:
        raw = json.loads(p.read_text())
    except Exception as e:
        fatal(f"Could not parse channel topology {p}: {e}")
    raw.pop("_meta", None)

    entries = {}
    for k, v in raw.items():
        try:
            entries[int(k)] = v
        except (TypeError, ValueError):
            continue

    n_sub = len(sub_ids)
    if len(entries) != n_sub:
        fatal(f"Channel topology has {len(entries)} channels but the subbasin "
              f"shapefile has {n_sub}.")
    if set(entries.keys()) != set(range(1, n_sub + 1)):
        fatal(f"Channel topology keys are not exactly 1..{n_sub} "
              f"(got {sorted(entries.keys())}).")

    # sub_id alignment: channel ids are POSITIONAL (cha{i+1} <-> sub_ids[i]).
    # A same-sized topology built from a different partition or a different sort
    # order would bind every channel's downstream target to the wrong subbasin
    # while passing all count checks. Verify identity, not cardinality.
    misaligned = []
    for idx, sid in enumerate(sub_ids):
        rec = entries[idx + 1]
        topo_sid = rec.get("sub_id") if isinstance(rec, dict) else None
        if topo_sid is None:
            fatal(f"Channel topology entry cha{idx+1} has no 'sub_id' field; "
                  "cannot verify alignment with the subbasin ordering.")
        if int(topo_sid) != int(sid):
            misaligned.append((idx + 1, int(topo_sid), int(sid)))
    if misaligned:
        preview = ", ".join(f"cha{c}: topology sub_id={t} vs shapefile sub_id={h}"
                            for c, t, h in misaligned[:5])
        fatal(f"Channel topology sub_id ordering does not match the subbasin "
              f"ordering for {len(misaligned)} of {n_sub} channels ({preview}"
              f"{', ...' if len(misaligned) > 5 else ''}).")

    topo = {cid: (rec.get("downstream_id") if isinstance(rec, dict) else None)
            for cid, rec in entries.items()}
    logger.info(f"Loaded channel topology: {len(topo)} channels, sub_id "
                f"alignment verified for all {n_sub}")
    return topo


def station_for(subbasins, i):
    """Per-subbasin weather station. Falls back to wst001 only if unbound."""
    for col in ("wst", "wst_name", "station", "sta"):
        if col in subbasins.columns:
            val = subbasins[col].iloc[i]
            if val is not None and str(val).strip():
                return str(val).strip()
    return f"wst{i+1:03d}"


def process():
    """Generate SWAT+ connectivity files from spatial data."""
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    import geopandas as gpd

    subbasins = gpd.read_file(SUBBASIN_SHP)
    streams = gpd.read_file(STREAM_SHP)

    # Channel ids are positional, so the subbasin ORDER here must be the same
    # order build_channel_topology.py and generate_hru_from_global.py use:
    # sorted by sub_id, emitting cha{idx+1}. Reading in raw file order would
    # desynchronize channels from the topology (and from the HRU grouping)
    # whenever the shapefile is not already stored in sub_id order.
    if "sub_id" in subbasins.columns:
        subbasins = subbasins.sort_values("sub_id").reset_index(drop=True)
        sub_ids = [int(v) for v in subbasins["sub_id"].tolist()]
    else:
        logger.warning("No 'sub_id' column in %s -- assuming 1..N in file order. "
                       "This MUST match the ordering used by "
                       "build_channel_topology.py and generate_hru_from_global.py.",
                       SUBBASIN_SHP)
        sub_ids = list(range(1, len(subbasins) + 1))
    n_sub = len(subbasins)

    topo = load_topology(sub_ids)
    if topo is None:
        logger.warning("=" * 78)
        logger.warning("WARNING: no channel topology supplied -- hd_id will be "
                       "written as 0 for every channel.")
        logger.warning("WARNING: that is NOT a stream cascade. A deck built this "
                       "way routes as a lumped water-yield proxy, not a routed "
                       "hydrograph, and its NSE/KGE is not a model verdict.")
        logger.warning("WARNING: build one with tools/s1/build_channel_topology.py "
                       "and pass it as argv[5].")
        logger.warning("=" * 78)

    # Generate chandeg.con (channel connectivity)
    chandeg_path = output_dir / "chandeg.con"
    with open(chandeg_path, 'w') as f:
        f.write("chandeg.con: written by SWAT+ knowledge infrastructure\n")
        f.write(f"  gis_id       name             area       lat         lon         elev        "
                f"wst            obj_typ    obj_id     hd_typ     hd_id\n")
        for i in range(n_sub):
            centroid = subbasins.geometry.iloc[i].centroid
            # hd_id is the DOWNSTREAM channel this one discharges into. Writing
            # the constant 0 for every channel produces no cascade at all.
            hd_id = 0 if topo is None else (topo.get(i + 1) or 0)
            f.write(f"  {i+1:<12d} cha{i+1:03d}           "
                    f"{subbasins.geometry.iloc[i].area/1e6:10.3f} "
                    f"{centroid.y:10.5f} {centroid.x:10.5f} "
                    f"{'0.0':>10s} {station_for(subbasins, i):>15s} "
                    f"{'sdc':>10s} {i+1:>10d} {'tot':>10s} {hd_id:>10d}\n")
    logger.info(f"Wrote {chandeg_path} with {n_sub} channels")

    # Generate rout_unit.con (routing unit connectivity)
    rout_path = output_dir / "rout_unit.con"
    with open(rout_path, 'w') as f:
        f.write("rout_unit.con: written by SWAT+ knowledge infrastructure\n")
        f.write(f"  gis_id       name             area       lat         lon         elev        "
                f"wst            obj_typ    obj_id     hd_typ     hd_id\n")
        for i in range(n_sub):
            centroid = subbasins.geometry.iloc[i].centroid
            f.write(f"  {i+1:<12d} ru{i+1:04d}            "
                    f"{subbasins.geometry.iloc[i].area/1e6:10.3f} "
                    f"{centroid.y:10.5f} {centroid.x:10.5f} "
                    f"{'0.0':>10s} {station_for(subbasins, i):>15s} "
                    f"{'sdc':>10s} {i+1:>10d} {'tot':>10s} {i+1:>10d}\n")
    logger.info(f"Wrote {rout_path} with {n_sub} routing units")

    return {
        "status": "success",
        "chandeg_con": str(chandeg_path),
        "rout_unit_con": str(rout_path),
        "n_subbasins": n_sub
    }


def validate_outputs(result):
    errors = []
    for key in ["chandeg_con", "rout_unit_con"]:
        if not Path(result[key]).exists():
            errors.append(f"Expected output not created: {result[key]}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)
