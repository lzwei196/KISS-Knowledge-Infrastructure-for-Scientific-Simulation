#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
====================================================
Tool ID:      write_channel_geometry
Stage:        s2_hru_definition
Description:  Author hyd-sed-lte.cha (and correct hydrology.cha) from
              NETWORK-ACCUMULATED drainage area and Strahler order.

Why this tool exists
--------------------
No tool in the SWAT+ knowledge infrastructure wrote hyd-sed-lte.cha at all --
`grep -rln 'CHEROD|SHEAR_BNK' tools/` returned zero hits. The decks under
outputs/ inherited that file from a base deck whose builder no longer exists on
disk, so the channel order and hydraulic geometry were frozen artifacts that no
longer described the basin they were being used to route. In the Xixian deck
every one of the 33 channels was ORDER=first and the terminal channel -- the one
s9/extract_discharge auto-detects as the scored outlet -- was a 3.29 m wide,
0.34 m deep, 0.79 km long first-order stub asked to convey 9681 km2 at a mean of
91 m3/s and a peak of 2994 m3/s.

This tool sizes every channel from the area it actually CONVEYS, using the
topology JSON produced by tools/s1/build_channel_topology.py.

Inputs:
  --txtinout          : SWAT+ TxtInOut directory to write into.
  --channel_topology  : channel_topology.json from build_channel_topology.py.
  --name_format       : plain -> hydcha1 (matches hydrology.cha / channel.cha
                        written by generate_hru_from_global.py, default);
                        pad3 -> hydcha001.
  --write_hydrology_cha : Also rewrite hydrology.cha from accumulated area.
  --min_outlet_chw    : Sanity gate. The terminal channel's CHW must be at least
                        this many metres (default 0 = derive from basin area).

Which quantity sizes what (precise contract -- do not over-read it)
------------------------------------------------------------------
  wd (CHW) = 2.71 * A^0.557      [m]   A = NETWORK-ACCUMULATED area (km2)
  dp (CHD) = 0.349 * A^0.341     [m]   A = NETWORK-ACCUMULATED area (km2)
  len (CHL)                      [km]  = topology length_km, i.e. the length of
                                         stream network lying INSIDE that
                                         subbasin -- a LOCAL geometric property,
                                         NOT an accumulated-area regression.
  slp (CHS)                      [m/m] = local DEM relief over reach length.

Only WIDTH and DEPTH are accumulated-area functions, because only they scale
with conveyed discharge. Reach length is set by where the subbasin boundaries
cut the stream network: a headwater subbasin and a downstream subbasin of equal
size contain similar lengths of channel no matter what drains through them.
Deriving CHL from accumulated area would inflate every downstream reach and
double-count travel time down the cascade, so it is deliberately NOT done. Each
channel's length provenance is carried in the topology JSON as `length_source`
("stream_geometry" or "local_area_fallback") and is echoed in this tool's
result JSON so a reviewer can audit how many reaches used real geometry.

The wd/dp relations are the SAME inherited empirical regional constants already
used by generate_hru_from_global.py; the change is the AREA they are applied to,
not the exponents. They are inherited constants, NOT calibrated for this basin,
and are reported as such.

Which file actually routes the deck
-----------------------------------
hyd-sed-lte.cha only governs LTE ("lcha") channels. In the Xixian deck
object.cnt reports cha=33 / lcha=0 and channel.cha binds each cha{N} to
hydcha{N}, so the ACTIVE geometry file there is hydrology.cha, not
hyd-sed-lte.cha. Pass --write_hydrology_cha whenever the deck uses regular
channels, or the corrected geometry will be written to an inert file. Check
`object.cnt` (cha vs lcha) before deciding.

Sanity gates enforced before writing (exit 2 on failure)
--------------------------------------------------------
  - the topology must have exactly one terminal channel
  - the terminal channel must NOT be ORDER=first
  - the terminal channel's CHW must clear the minimum for its drainage area
    (~10^2 m for a ~10^4 km2 humid basin)

Exit codes: 0=success, 1=input error, 2=validation error, 3=output error
"""

import sys
import os
import json
import logging
import argparse
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Strahler order -> SWAT+ lte ORDER token
ORDER_TOKENS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}
MAX_ORDER_TOKEN = "fifth"

# Non-geometric lte defaults, carried from the SWAT+ rev59 shipped example.
LTE_DEFAULTS = {
    "CHN": 0.075, "CHK": 0.000, "CHEROD": 0.01, "CHCOV": 0.005,
    "HC_COV": 0.005, "CHSEQ": 0.001, "D50": 12.0, "CLAY": 30.0,
    "CARBON": 0.4, "BD": 1.5, "CHSS": 0.5, "BEDLD": 0.50, "TC": 120.0,
    "SHEAR_BNK": 0.75, "HC_KH": 0.05, "HC_HGT": 0.5, "HC_INI": 0.0,
}


def parse_args():
    p = argparse.ArgumentParser(
        description="Write hyd-sed-lte.cha / hydrology.cha from accumulated area.")
    p.add_argument("--txtinout", required=True)
    p.add_argument("--channel_topology", required=True)
    p.add_argument("--name_format", default="plain", choices=["plain", "pad3"])
    p.add_argument("--write_hydrology_cha", action="store_true")
    p.add_argument("--min_outlet_chw", type=float, default=0.0)
    return p.parse_args()


def validate_inputs(args):
    errors = []
    if not Path(args.txtinout).is_dir():
        errors.append(f"TxtInOut directory not found: {args.txtinout}")
    if not Path(args.channel_topology).exists():
        errors.append(f"Channel topology not found: {args.channel_topology}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def load_topology(path):
    raw = json.loads(Path(path).read_text())
    meta = raw.pop("_meta", {})
    topo = {}
    for k, v in raw.items():
        try:
            topo[int(k)] = v
        except (TypeError, ValueError):
            continue
    if not topo:
        logger.error("Channel topology %s contains no channels", path)
        sys.exit(1)
    return topo, meta


def channel_geometry(area_km2):
    """Regional hydraulic geometry from accumulated drainage area (km2)."""
    wd = max(1.0, 2.71 * (area_km2 ** 0.557))
    dp = max(0.1, 0.349 * (area_km2 ** 0.341))
    return wd, dp


def order_token(strahler):
    return ORDER_TOKENS.get(int(strahler), MAX_ORDER_TOKEN)


def run_sanity_gates(topo, args):
    """Fail loudly rather than write a deck whose outlet is a first-order stub."""
    terminals = [cid for cid, v in topo.items() if v.get("downstream_id") is None]
    if len(terminals) != 1:
        logger.error("Topology has %d terminal channels (%s); exactly one is "
                     "required. s9/extract_discharge auto-detects the scored "
                     "outlet as the channel with out_tot==0, so an ambiguous "
                     "terminal means an arbitrary gauge.", len(terminals), terminals)
        sys.exit(2)
    outlet = terminals[0]
    rec = topo[outlet]

    area_km2 = float(rec["upstream_accumulated_area_ha"]) / 100.0
    strahler = int(rec.get("strahler_order", 1))
    wd, dp = channel_geometry(area_km2)

    logger.info("Outlet gate: cha%d  accum_area=%.1f km2  order=%s  "
                "CHW=%.1f m  CHD=%.2f m", outlet, area_km2,
                order_token(strahler), wd, dp)

    if strahler <= 1:
        logger.error(
            "SANITY GATE FAILED: the terminal channel cha%d is ORDER=first while "
            "draining %.0f km2. A first-order outlet means the network never "
            "cascades and the deck is a lumped water-yield proxy. Refusing to "
            "write.", outlet, area_km2)
        sys.exit(2)

    min_chw = args.min_outlet_chw
    if min_chw <= 0:
        # Expect O(10^2) m for O(10^4) km2. Gate at half the regional relation,
        # floored so small basins are not spuriously rejected.
        min_chw = max(5.0, 0.5 * 2.71 * (area_km2 ** 0.557))
    if wd < min_chw:
        logger.error(
            "SANITY GATE FAILED: terminal channel CHW=%.2f m is below the minimum "
            "%.2f m for a %.0f km2 drainage area. The outlet is sized as a "
            "rivulet. Refusing to write.", wd, min_chw, area_km2)
        sys.exit(2)

    logger.info("Sanity gates passed for outlet cha%d", outlet)
    return outlet


def warn_if_geometry_target_is_inert(args):
    """hyd-sed-lte.cha is inert when the deck has no LTE channels.

    object.cnt carries per-object counts; 'cha' is regular channels and 'lcha' is
    LTE channels. A deck with lcha=0 routes through channel.cha -> hydrology.cha,
    so writing only hyd-sed-lte.cha would correct a file SWAT+ never reads while
    the rivulet geometry stays live in hydrology.cha.
    """
    if args.write_hydrology_cha:
        return
    cnt = Path(args.txtinout) / "object.cnt"
    if not cnt.exists():
        return
    try:
        lines = cnt.read_text().splitlines()
        header = lines[1].split()
        values = lines[2].split()
        counts = dict(zip(header, values))
        n_cha = float(counts.get("cha", 0))
        n_lcha = float(counts.get("lcha", 0))
    except Exception as e:
        logger.warning("Could not parse object.cnt (%s) -- skipping the "
                       "inert-target check.", e)
        return

    if n_lcha == 0 and n_cha > 0:
        logger.warning("=" * 78)
        logger.warning("WARNING: object.cnt reports cha=%g and lcha=%g, so this "
                       "deck has NO LTE channels and hyd-sed-lte.cha is INERT.",
                       n_cha, n_lcha)
        logger.warning("WARNING: the geometry SWAT+ actually routes with lives in "
                       "hydrology.cha (channel.cha binds cha{N} -> hydcha{N}).")
        logger.warning("WARNING: re-run with --write_hydrology_cha, or the "
                       "mis-sized outlet stays live.")
        logger.warning("=" * 78)


def write_lte(topo, txtinout, name_format, outlet):
    path = Path(txtinout) / "hyd-sed-lte.cha"
    cids = sorted(topo.keys())

    def name(cid):
        return f"hydcha{cid:03d}" if name_format == "pad3" else f"hydcha{cid}"

    d = LTE_DEFAULTS
    with open(path, "w") as f:
        f.write("hyd-sed-lte.cha: written by write_channel_geometry "
                "(HydroCraft KI) from network-accumulated drainage area\n")
        f.write(f"{'NAME':<14}{'ORDER':>6}{'CHW':>12}{'CHD':>11}{'CHS':>11}"
                f"{'CHL':>11}{'CHN':>11}{'CHK':>11}{'CHEROD':>8}{'CHCOV':>8}"
                f"{'HC_COV':>8}{'CHSEQ':>7}{'D50':>11}{'CLAY':>7}{'CARBON':>9}"
                f"{'BD':>7}{'CHSS':>8}{'BEDLD':>10}{'TC':>8}{'SHEAR_BNK':>12}"
                f"{'HC_KH':>8}{'HC_HGT':>10}{'HC_INI':>9}\n")
        for cid in cids:
            rec = topo[cid]
            area_km2 = float(rec["upstream_accumulated_area_ha"]) / 100.0
            wd, dp = channel_geometry(area_km2)
            chl = max(0.1, float(rec.get("length_km", 1.0)))
            chs = max(0.0001, float(rec.get("slope", 0.001)))
            tok = order_token(rec.get("strahler_order", 1))
            f.write(f"{name(cid):<14}{tok:>6}{wd:>12.3f}{dp:>11.3f}{chs:>11.3f}"
                    f"{chl:>11.3f}{d['CHN']:>11.3f}{d['CHK']:>11.3f}"
                    f"{d['CHEROD']:>8.2f}{d['CHCOV']:>8.3f}{d['HC_COV']:>8.3f}"
                    f"{d['CHSEQ']:>7.3f}{d['D50']:>11.1f}{d['CLAY']:>7.1f}"
                    f"{d['CARBON']:>9.1f}{d['BD']:>7.1f}{d['CHSS']:>8.1f}"
                    f"{d['BEDLD']:>10.2f}{d['TC']:>8.1f}{d['SHEAR_BNK']:>12.2f}"
                    f"{d['HC_KH']:>8.2f}{d['HC_HGT']:>10.1f}{d['HC_INI']:>9.1f}\n")
    logger.info("Wrote %s (%d channels, outlet cha%d is ORDER=%s)",
                path, len(cids), outlet,
                order_token(topo[outlet].get("strahler_order", 1)))
    return path


def write_hydrology_cha(topo, txtinout):
    path = Path(txtinout) / "hydrology.cha"
    cids = sorted(topo.keys())
    with open(path, "w") as f:
        f.write("hydrology.cha: written by write_channel_geometry "
                "(HydroCraft KI) from network-accumulated drainage area\n")
        f.write(f"{'name':<20}{'wd':>14}{'dp':>14}{'slp':>14}"
                f"{'len':>14}{'mann':>14}{'k':>14}"
                f"{'wdr':>14}{'alpha_bnk':>14}{'side_slp':>14}  description\n")
        for cid in cids:
            rec = topo[cid]
            area_km2 = float(rec["upstream_accumulated_area_ha"]) / 100.0
            wd, dp = channel_geometry(area_km2)
            chl = max(0.1, float(rec.get("length_km", 1.0)))
            chs = max(0.0001, float(rec.get("slope", 0.001)))
            wdr = max(3.0, wd / dp if dp > 0 else 10.0)
            f.write(f"{f'hydcha{cid}':<20}"
                    f"{wd:>14.5f}{dp:>14.5f}{chs:>14.5f}"
                    f"{chl:>14.5f}{0.05:>14.5f}{0.0:>14.5f}"
                    f"{wdr:>14.5f}{0.0:>14.5f}{0.0:>14.5f}  \n")
    logger.info("Wrote %s (%d channels)", path, len(cids))
    return path


def main():
    args = parse_args()
    logger.info("Running tool: %s", os.path.basename(__file__))
    validate_inputs(args)

    topo, meta = load_topology(args.channel_topology)
    outlet = run_sanity_gates(topo, args)
    warn_if_geometry_target_is_inert(args)

    written = []
    try:
        written.append(str(write_lte(topo, args.txtinout, args.name_format, outlet)))
        if args.write_hydrology_cha:
            written.append(str(write_hydrology_cha(topo, args.txtinout)))
    except Exception as e:
        logger.exception("Write failed: %s", e)
        sys.exit(3)

    for pth in written:
        if not Path(pth).exists():
            logger.error("Expected output not created: %s", pth)
            sys.exit(3)

    orec = topo[outlet]
    oarea = float(orec["upstream_accumulated_area_ha"]) / 100.0
    owd, odp = channel_geometry(oarea)
    result = {
        "status": "success",
        "files_written": written,
        "n_channels": len(topo),
        "outlet_channel_id": outlet,
        "outlet_order": order_token(orec.get("strahler_order", 1)),
        "outlet_accum_area_km2": round(oarea, 2),
        "outlet_chw_m": round(owd, 2),
        "outlet_chd_m": round(odp, 3),
        "geometry_relations": "wd=2.71*A^0.557, dp=0.349*A^0.341 with A = "
                              "network-accumulated area (inherited empirical "
                              "constants, NOT calibrated for this basin); CHL "
                              "from local in-subbasin stream length; CHS from "
                              "local DEM relief",
        "n_length_from_stream_geometry": sum(
            1 for v in topo.values()
            if v.get("length_source") == "stream_geometry"),
        "n_length_from_local_area_fallback": sum(
            1 for v in topo.values()
            if v.get("length_source") == "local_area_fallback"),
        "hydrology_cha_written": bool(args.write_hydrology_cha),
    }
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
