#!/usr/bin/env python3
"""
lookup_dams.py -- Find dams in a basin using GRanD Data KI and return
reservoir properties in wflow-native units.

This tool bridges GRanD (Global Reservoir and Dam) data to the wflow
reservoir module. It performs the following:
  1. Searches GRanD for dams within a bounding box or radius of a point
  2. Converts units from GRanD native (MCM, km^2) to wflow native (m^3, m^2)
  3. Estimates missing parameters using empirical relationships
  4. Returns a JSON-serializable list suitable for configure_reservoirs.py

The "simple reservoir" (outflowfunc=4) approach is the default because it
requires only capacity, area, and demand -- all derivable from GRanD.

Usage:
    # Find dams near Wangjiaba/Bengbu (Huai River)
    python lookup_dams.py --lat 32.95 --lon 117.38 --radius_km 200

    # Find dams by river name
    python lookup_dams.py --river "HuaiHe"

    # Find dams within a bounding box (for a basin extent)
    python lookup_dams.py --bbox 31.0 33.5 115.0 118.0

    # Output as JSON for piping to configure_reservoirs.py
    python lookup_dams.py --lat 32.95 --lon 117.38 --radius_km 200 --json
"""

import argparse
import json
import math
import sys
import os

# GRanD Data KI path
GRAND_SEARCH = "/mnt/disk1/Hydrocraft_server/data_ki/GRanD/tools/search_dams.py"
GRAND_CSV = "/mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/map/data/GRanD_allocated.csv"


def load_grand_csv():
    """Load the full GRanD CSV into a list of dicts with proper types."""
    import csv

    dams = []
    with open(GRAND_CSV, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for key in ["ID", "YEAR", "ALT_YEAR", "REM_YEAR"]:
                row[key] = int(row[key])
            for key in [
                "lat_alloc", "lon_alloc", "area_alloc", "CAP_MCM",
                "ELEV_MASL", "DAM_HGT_M", "lat_ori", "lon_ori", "area_ori",
            ]:
                row[key] = float(row[key])
            dams.append(row)
    return dams


def search_by_bbox(dams, lat_min, lat_max, lon_min, lon_max):
    """Search dams within a bounding box using original coordinates."""
    results = []
    for d in dams:
        if (lat_min <= d["lat_ori"] <= lat_max and
                lon_min <= d["lon_ori"] <= lon_max):
            results.append(d)
    # Sort by capacity descending (largest dams first)
    results.sort(key=lambda x: x["CAP_MCM"], reverse=True)
    return results


def search_by_radius(dams, lat, lon, radius_km):
    """Search dams within radius_km of lat/lon using original coordinates."""
    results = []
    cos_lat = math.cos(math.radians(lat))
    for d in dams:
        dlat = (d["lat_ori"] - lat) * 111.0
        dlon = (d["lon_ori"] - lon) * 111.0 * cos_lat
        dist = math.sqrt(dlat ** 2 + dlon ** 2)
        if dist <= radius_km:
            d["_dist_km"] = round(dist, 1)
            results.append(d)
    results.sort(key=lambda x: x["CAP_MCM"], reverse=True)
    return results


def search_by_river(dams, river_name):
    """Search dams by river name (case-insensitive substring)."""
    river_lower = river_name.lower()
    results = [d for d in dams if river_lower in d["RiverName"].lower()]
    results.sort(key=lambda x: x["CAP_MCM"], reverse=True)
    return results


def convert_to_wflow_params(dam, reservoir_index):
    """Convert a GRanD dam record to wflow reservoir parameters.

    wflow SimpleReservoir (outflowfunc=4) requires:
      - area:            m^2   (GRanD gives km^2)
      - maxstorage:      m^3   (GRanD gives MCM = 10^6 m^3)
      - demand:          m^3/s (estimated from capacity and purpose)
      - maxrelease:      m^3/s (estimated from capacity)
      - targetfullfrac:  -     (fraction, default 0.8)
      - targetminfrac:   -     (fraction, default 0.2)
      - waterlevel_init: m     (estimated from dam height or elevation)
      - storfunc:        int   (1=linear S=AH, 2=S-H interpolation)
      - outflowfunc:     int   (4=simple for GRanD-derived reservoirs)

    UNIT CONVERSIONS (CRITICAL -- dt_w031):
      - GRanD CAP_MCM (million cubic meters) -> wflow maxstorage (m^3): * 1e6
      - GRanD area_alloc (km^2)              -> wflow area (m^2):       * 1e6
      - GRanD area_ori (km^2)                -> wflow area (m^2):       * 1e6

    PARAMETER ESTIMATION (when GRanD lacks data):
      - demand: estimated as 5% of maxstorage / (365.25 * 86400), i.e.,
        annual demand = 5% of capacity, converted to m^3/s
      - maxrelease: estimated from dam height using broad-crested weir:
        Q = C * L * H^1.5, with C=1.7, L estimated from sqrt(area),
        capped at maxstorage/(30*86400) (empty in 30 days)
      - targetfullfrac: 0.8 (keep 80% full as default target)
      - targetminfrac: 0.2 (minimum 20% for environmental flow)
      - initial waterlevel: dam_height * targetfullfrac if dam_height known,
        else maxstorage * targetfullfrac / area
    """
    cap_mcm = dam["CAP_MCM"]
    area_km2 = dam["area_ori"] if dam["area_ori"] > 0 else dam["area_alloc"]
    dam_height = dam["DAM_HGT_M"]
    elev = dam["ELEV_MASL"]

    # Convert units
    maxstorage_m3 = cap_mcm * 1e6  # MCM -> m^3
    area_m2 = area_km2 * 1e6       # km^2 -> m^2

    # Estimate demand: 5% of capacity per year as base environmental flow
    demand_m3s = 0.05 * maxstorage_m3 / (365.25 * 86400.0)

    # Estimate max release
    if dam_height > 0:
        # Broad-crested weir estimate: Q = 1.7 * L * H^1.5
        # L estimated as spillway width ~ sqrt(area_m2) * 0.01 (rough)
        spillway_width = max(math.sqrt(area_m2) * 0.01, 10.0)
        maxrelease = 1.7 * spillway_width * (dam_height ** 1.5)
        # Cap: can empty reservoir in 30 days minimum
        maxrelease = min(maxrelease, maxstorage_m3 / (30.0 * 86400.0))
        # Floor: at least 2x demand
        maxrelease = max(maxrelease, 2.0 * demand_m3s)
    else:
        # No dam height: empty in 90 days as rough estimate
        maxrelease = maxstorage_m3 / (90.0 * 86400.0)
        maxrelease = max(maxrelease, 2.0 * demand_m3s)

    # Target fractions
    targetfullfrac = 0.8
    targetminfrac = 0.2

    # Initial water level
    if dam_height > 0:
        waterlevel_init = dam_height * targetfullfrac
    else:
        # Estimate from storage / area = average depth
        if area_m2 > 0:
            waterlevel_init = (maxstorage_m3 * targetfullfrac) / area_m2
        else:
            waterlevel_init = 10.0  # fallback

    wflow_params = {
        "grand_id": dam["ID"],
        "name": dam["DamName"],
        "river": dam["RiverName"],
        "lat": dam["lat_ori"],
        "lon": dam["lon_ori"],
        "year": dam["YEAR"] if dam["YEAR"] != -99 else None,
        "reservoir_index": reservoir_index,
        # wflow parameters (all in SI units)
        "area_m2": round(area_m2, 1),
        "maxstorage_m3": round(maxstorage_m3, 1),
        "demand_m3s": round(demand_m3s, 4),
        "maxrelease_m3s": round(maxrelease, 4),
        "targetfullfrac": targetfullfrac,
        "targetminfrac": targetminfrac,
        "waterlevel_init_m": round(waterlevel_init, 2),
        "storfunc": 1,    # 1 = linear S = A*H
        "outflowfunc": 4, # 4 = simple reservoir
        # Original GRanD values for reference
        "grand_cap_mcm": cap_mcm,
        "grand_area_km2": area_km2,
        "grand_dam_height_m": dam_height if dam_height > 0 else None,
        "grand_elev_masl": elev if elev > 0 else None,
    }

    if "_dist_km" in dam:
        wflow_params["dist_km"] = dam["_dist_km"]

    return wflow_params


def print_human_readable(reservoirs):
    """Print reservoir list in human-readable format."""
    if not reservoirs:
        print("No dams found.")
        return

    print(f"\n{'='*70}")
    print(f"Found {len(reservoirs)} dam(s) -- wflow reservoir parameters")
    print(f"{'='*70}")

    for r in reservoirs:
        print(f"\n  [{r['reservoir_index']}] {r['name']} ({r['river']})")
        print(f"      GRanD ID:       {r['grand_id']}")
        print(f"      Location:       ({r['lat']:.3f}, {r['lon']:.3f})")
        if r.get("dist_km") is not None:
            print(f"      Distance:       {r['dist_km']} km from search point")
        if r["year"]:
            print(f"      Built:          {r['year']}")
        print(f"      -- GRanD values --")
        print(f"      Capacity:       {r['grand_cap_mcm']} MCM")
        print(f"      Area:           {r['grand_area_km2']} km^2")
        if r["grand_dam_height_m"]:
            print(f"      Dam height:     {r['grand_dam_height_m']} m")
        print(f"      -- wflow parameters (SI units) --")
        print(f"      area:           {r['area_m2']:.0f} m^2")
        print(f"      maxstorage:     {r['maxstorage_m3']:.0f} m^3")
        print(f"      demand:         {r['demand_m3s']:.4f} m^3/s")
        print(f"      maxrelease:     {r['maxrelease_m3s']:.4f} m^3/s")
        print(f"      targetfullfrac: {r['targetfullfrac']}")
        print(f"      targetminfrac:  {r['targetminfrac']}")
        print(f"      waterlevel(0):  {r['waterlevel_init_m']:.2f} m")
        print(f"      storfunc:       {r['storfunc']} (linear)")
        print(f"      outflowfunc:    {r['outflowfunc']} (simple)")

    print(f"\n{'='*70}")
    print(f"NOTE: demand and maxrelease are ESTIMATES from empirical formulas.")
    print(f"      Calibrate these against observed outflow if available.")
    print(f"      Use --json flag to pipe output to configure_reservoirs.py.")
    print(f"{'='*70}")


def main():
    parser = argparse.ArgumentParser(
        description="Find dams in a basin using GRanD and return wflow reservoir params"
    )
    # Search modes
    parser.add_argument("--lat", type=float,
                        help="Center latitude for radius search")
    parser.add_argument("--lon", type=float,
                        help="Center longitude for radius search")
    parser.add_argument("--radius_km", type=float, default=100,
                        help="Search radius in km (default: 100)")
    parser.add_argument("--bbox", type=float, nargs=4,
                        metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"),
                        help="Bounding box: lat_min lat_max lon_min lon_max")
    parser.add_argument("--river", type=str,
                        help="Search by river name (substring match)")

    # Filtering
    parser.add_argument("--min_capacity_mcm", type=float, default=0,
                        help="Minimum reservoir capacity in MCM (default: 0)")
    parser.add_argument("--max_results", type=int, default=50,
                        help="Maximum results (default: 50)")

    # Output
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON (for piping to configure_reservoirs.py)")
    parser.add_argument("--output", type=str, default="",
                        help="Write JSON output to file")

    args = parser.parse_args()

    # Validate inputs
    if not (args.lat is not None and args.lon is not None) and \
       args.bbox is None and args.river is None:
        parser.print_help()
        print("\nERROR: Provide --lat/--lon, --bbox, or --river", file=sys.stderr)
        sys.exit(1)

    # Load GRanD data
    if not os.path.exists(GRAND_CSV):
        print(f"ERROR: GRanD CSV not found at {GRAND_CSV}", file=sys.stderr)
        print("Ensure GRanD Data KI is installed.", file=sys.stderr)
        sys.exit(1)

    dams = load_grand_csv()

    # Search
    if args.bbox:
        lat_min, lat_max, lon_min, lon_max = args.bbox
        results = search_by_bbox(dams, lat_min, lat_max, lon_min, lon_max)
    elif args.river:
        results = search_by_river(dams, args.river)
    else:
        results = search_by_radius(dams, args.lat, args.lon, args.radius_km)

    # Filter by capacity
    if args.min_capacity_mcm > 0:
        results = [d for d in results if d["CAP_MCM"] >= args.min_capacity_mcm]

    # Limit results
    results = results[:args.max_results]

    # Convert to wflow parameters
    reservoirs = []
    for i, dam in enumerate(results, start=1):
        wflow_params = convert_to_wflow_params(dam, reservoir_index=i)
        reservoirs.append(wflow_params)

    # Output
    if args.json or args.output:
        output_data = {
            "status": "success",
            "count": len(reservoirs),
            "search_params": {
                "lat": args.lat, "lon": args.lon,
                "radius_km": args.radius_km if args.lat else None,
                "bbox": args.bbox,
                "river": args.river,
                "min_capacity_mcm": args.min_capacity_mcm,
            },
            "reservoirs": reservoirs,
        }
        json_str = json.dumps(output_data, indent=2)

        if args.output:
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w") as f:
                f.write(json_str)
            print(f"Written {len(reservoirs)} reservoir(s) to {args.output}")
        else:
            print(json_str)
    else:
        print_human_readable(reservoirs)


if __name__ == "__main__":
    main()
