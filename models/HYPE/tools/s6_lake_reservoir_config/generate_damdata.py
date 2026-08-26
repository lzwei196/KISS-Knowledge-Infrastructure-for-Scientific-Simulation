#!/usr/bin/env python3
"""Generate HYPE DamData.txt from GRanD database for regulated dams.

DamData.txt provides additional dam-specific regulation rules beyond what
LakeData.txt offers. It is used for dams with flood control, hydropower,
or irrigation purposes requiring monthly inflow-based regulation.

DamData.txt columns (from HYPE source data.f90 load_damdata):
  Required: subid
  Optional: lake_depth, lake_shape, purpose, regvol, rate, exp, w0ref,
            wamp, qprod1, qprod2, datum1, datum2, qamp, qpha, limqprod,
            qinfjan-qinfdec (12 monthly natural inflows), snowfrac,
            builddam, removedam

Purpose codes:
  1 = Irrigation
  2 = Water supply
  3 = Flood control
  4 = Hydroelectricity

Usage:
    python generate_damdata.py \\
        --geodata modelfiles/GeoData.txt \\
        --output modelfiles/DamData.txt \\
        --lat 32.4 --lon 115.7 \\
        [--search_radius_km 200] \\
        [--purpose 3]

    # Generate for specific dams by name:
    python generate_damdata.py \\
        --geodata modelfiles/GeoData.txt \\
        --output modelfiles/DamData.txt \\
        --dam_names "Meishan,Xianghongdian,Foziling"
"""

import argparse
import csv
import math
import os
import sys

GRAND_CSV = (
    "KISSPATH_BINARIES/cmf_v420_pkg/map/data/"
    "GRanD_allocated.csv"
)

# Default monthly flow fractions for East Asian monsoon climate
# Based on typical Huai River basin flow distribution
MONSOON_MONTHLY_FRACTIONS = [
    0.03, 0.03, 0.04, 0.06, 0.08, 0.12,
    0.18, 0.18, 0.12, 0.08, 0.05, 0.03
]

# Month names for qinf columns
MONTH_NAMES = [
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec"
]


def load_geodata(geodata_path):
    """Read GeoData.txt into list of dicts."""
    with open(geodata_path) as f:
        lines = f.readlines()

    data_start = 0
    for i, line in enumerate(lines):
        if not line.startswith('!!'):
            data_start = i
            break

    header = lines[data_start].strip().split('\t')
    rows = []
    for line in lines[data_start + 1:]:
        if line.strip():
            vals = line.strip().split('\t')
            row = {}
            for j, col in enumerate(header):
                if j < len(vals):
                    try:
                        row[col] = float(vals[j])
                    except (ValueError, TypeError):
                        row[col] = vals[j]
                else:
                    row[col] = 0
            rows.append(row)

    return header, rows


def search_grand(lat=None, lon=None, radius_km=200,
                 dam_names=None, river_name=None):
    """Search GRanD for dams matching criteria."""
    if not os.path.exists(GRAND_CSV):
        print(f"ERROR: GRanD CSV not found at {GRAND_CSV}")
        sys.exit(1)

    dams = []
    with open(GRAND_CSV, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dam = {
                    "ID": int(row["ID"]),
                    "DamName": row["DamName"],
                    "RiverName": row["RiverName"],
                    "lat": float(row["lat_ori"]),
                    "lon": float(row["lon_ori"]),
                    "CAP_MCM": float(row["CAP_MCM"]),
                    "DAM_HGT_M": float(row["DAM_HGT_M"]),
                    "ELEV_MASL": float(row["ELEV_MASL"]),
                    "YEAR": int(row["YEAR"]),
                    "area_km2": float(row["area_ori"]),
                }
            except (ValueError, KeyError):
                continue

            # Apply filters
            if dam_names is not None:
                names_lower = [n.strip().lower() for n in dam_names.split(',')]
                if not any(n in dam["DamName"].lower() for n in names_lower):
                    continue

            if river_name is not None:
                if river_name.lower() not in dam["RiverName"].lower():
                    continue

            if lat is not None and lon is not None:
                cos_lat = math.cos(math.radians(lat))
                dlat = (dam["lat"] - lat) * 111.0
                dlon = (dam["lon"] - lon) * 111.0 * cos_lat
                dist = math.sqrt(dlat**2 + dlon**2)
                if dist > radius_km:
                    continue
                dam["dist_km"] = round(dist, 1)

            dams.append(dam)

    if lat is not None:
        dams.sort(key=lambda x: x.get("dist_km", 0))

    return dams


def assign_dam_to_nearest_subbasin(dam, subbasins):
    """Find the nearest subbasin to a dam."""
    best_sub = None
    best_dist = float('inf')

    for sub in subbasins:
        slat = float(sub.get('latitude', sub.get('LATITUDE', 0)))
        slon = float(sub.get('longitude', sub.get('LONGITUDE', 0)))
        if slat == 0 and slon == 0:
            continue

        cos_lat = math.cos(math.radians(slat))
        dlat = (dam["lat"] - slat) * 111.0
        dlon = (dam["lon"] - slon) * 111.0 * cos_lat
        dist = math.sqrt(dlat**2 + dlon**2)

        if dist < best_dist:
            best_dist = dist
            best_sub = sub

    if best_sub is not None:
        subid = int(best_sub.get('SUBID', best_sub.get('subid', 0)))
        return subid, best_dist
    return None, None


def estimate_monthly_inflows(cap_mcm, dam_hgt_m, area_km2,
                              climate="monsoon"):
    """Estimate monthly natural inflows (m3/s) for a dam.

    Uses reservoir capacity and contributing area to estimate
    mean annual flow, then distributes using climate-appropriate
    monthly fractions.

    For more accurate results, run a natural (no-dam) simulation
    first and use simulated monthly flows.
    """
    # Rough estimate of mean annual runoff from area
    # For humid East Asian basins: ~400-600 mm/yr runoff
    # Q_mean = runoff_mm * area_km2 * 1e6 / (365 * 86400 * 1000)
    runoff_mm_yr = 500  # typical for Huai River basin
    q_mean_m3s = runoff_mm_yr * area_km2 * 1e6 / (365.25 * 86400 * 1000)

    # Alternatively, estimate from capacity (residence time ~ 0.5-2 years)
    # q_from_cap = CAP_MCM * 1e6 / (1.0 * 365 * 86400)  # 1 year residence
    q_from_cap = cap_mcm * 1e6 / (1.0 * 365.25 * 86400)

    # Use the larger estimate (capacity-based tends to be more reliable for large dams)
    q_mean = max(q_mean_m3s, q_from_cap)

    if climate == "monsoon":
        fractions = MONSOON_MONTHLY_FRACTIONS
    else:
        # Uniform distribution
        fractions = [1.0 / 12] * 12

    monthly_q = [q_mean * f * 12 for f in fractions]  # Scale so mean of 12 monthly values = q_mean
    return monthly_q


def estimate_purpose(dam):
    """Estimate dam purpose from name and height heuristics.

    Purpose codes: 1=Irrigation, 2=Water supply, 3=Flood control, 4=Hydropower

    GRanD does not have purpose in the allocated CSV, so we estimate:
    - Height > 50m: likely hydropower (4)
    - Large capacity relative to area: likely flood control/water supply (3)
    - Small-medium dams in agricultural areas: likely irrigation (1)
    """
    height = dam.get("DAM_HGT_M", 0)
    cap = dam.get("CAP_MCM", 0)

    if height > 60:
        return 4  # Hydropower
    elif cap > 500:
        return 3  # Flood control (large storage)
    elif height > 30:
        return 3  # Flood control
    else:
        return 1  # Irrigation


def generate_damdata(geodata_path, output_path,
                     lat=None, lon=None, search_radius_km=200,
                     dam_names=None, river_name=None,
                     purpose_filter=None, climate="monsoon"):
    """Generate DamData.txt from GRanD dam database.

    DamData.txt format (HYPE v5.35.0 data.f90 load_damdata):
      Tab-separated, !! comments allowed at top
      Required column: subid
      Key columns: purpose, regvol, rate, exp, w0ref, wamp,
                   qprod1, qprod2, datum1, datum2, lake_depth,
                   qinfjan-qinfdec (12 monthly natural inflows),
                   minflow
    """
    header, subbasins = load_geodata(geodata_path)

    # Search GRanD
    dams = search_grand(lat=lat, lon=lon, radius_km=search_radius_km,
                        dam_names=dam_names, river_name=river_name)

    if not dams:
        print("No dams found matching search criteria.")
        print("DamData.txt NOT generated.")
        return

    print(f"Found {len(dams)} dam(s) in GRanD")

    # Assign dams to subbasins and filter
    assignments = []
    for dam in dams:
        subid, dist = assign_dam_to_nearest_subbasin(dam, subbasins)
        if subid is None:
            print(f"  SKIP: {dam['DamName']} -- no matching subbasin")
            continue

        purpose = estimate_purpose(dam)
        if purpose_filter is not None and purpose != purpose_filter:
            continue

        assignments.append({
            "subid": subid,
            "dam": dam,
            "purpose": purpose,
            "dist_km": dist,
        })

    # Deduplicate: one dam per subbasin (largest capacity wins)
    sub_dams = {}
    for a in assignments:
        sid = a["subid"]
        if sid not in sub_dams or a["dam"]["CAP_MCM"] > sub_dams[sid]["dam"]["CAP_MCM"]:
            sub_dams[sid] = a
    assignments = list(sub_dams.values())

    if not assignments:
        print("No dams could be assigned to subbasins.")
        print("DamData.txt NOT generated.")
        return

    # Generate DamData.txt
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    # Build column list
    cols = ["subid", "purpose", "lake_depth", "regvol", "rate", "exp",
            "w0ref", "wamp", "qprod1", "qprod2", "datum1", "datum2",
            "minflow"]
    # Add monthly inflow columns
    for m in MONTH_NAMES:
        cols.append(f"qinf{m}")

    purpose_names = {1: "Irrigation", 2: "WaterSupply",
                     3: "FloodControl", 4: "Hydropower"}

    with open(output_path, 'w') as f:
        f.write("!! DamData.txt generated by HYPE KI generate_damdata.py\n")
        f.write("!! Source: GRanD (Global Reservoir and Dam Database)\n")
        f.write("!! Monthly inflows are estimated -- replace with natural simulation results\n")
        f.write("!! Purpose: 1=Irrigation, 2=WaterSupply, 3=FloodControl, 4=Hydropower\n")

        f.write("\t".join(cols) + "\n")

        for a in assignments:
            dam = a["dam"]
            subid = a["subid"]
            purpose = a["purpose"]

            # Lake depth from dam height (approximate)
            # Reservoir average depth ~ height * 0.4 (typical for valley dams)
            lake_depth = dam["DAM_HGT_M"] * 0.4

            # Regulation volume
            regvol = dam["CAP_MCM"]

            # Rating curve for spillway
            # rate: spillway coefficient
            # For flood control dams: high rate (fast release above threshold)
            if purpose == 3:  # Flood control
                rate = 5.0
                exp_val = 2.0
            elif purpose == 4:  # Hydropower
                rate = 2.0
                exp_val = 1.5
            else:
                rate = 3.0
                exp_val = 1.5

            # w0ref: reference level (0 = at top of regulation volume)
            w0ref = 0.0

            # wamp: regulation amplitude
            area_m2 = dam.get("area_km2", 1) * 1e6
            if area_m2 > 0 and regvol > 0:
                wamp = regvol * 1e6 / area_m2 * 0.5
            else:
                wamp = lake_depth * 0.3

            # Monthly inflows
            monthly_q = estimate_monthly_inflows(
                dam["CAP_MCM"], dam["DAM_HGT_M"],
                dam.get("area_km2", 100), climate
            )

            # Production flow (qprod1, qprod2)
            q_mean = sum(monthly_q) / 12
            if purpose == 4:  # Hydropower
                qprod1 = q_mean * 0.9   # High season: 90% of mean
                qprod2 = q_mean * 0.7   # Low season: 70% of mean
            elif purpose == 3:  # Flood control
                qprod1 = q_mean * 0.6   # Conservative release during flood season
                qprod2 = q_mean * 0.8   # Higher release during dry season
            else:
                qprod1 = q_mean * 0.5
                qprod2 = q_mean * 0.3

            # Seasonal dates
            if climate == "monsoon":
                datum1 = 501   # May 1 (flood season start)
                datum2 = 1001  # Oct 1 (dry season start)
            else:
                datum1 = 401
                datum2 = 1001

            # Minimum environmental flow (10% of mean)
            minflow = q_mean * 0.1

            print(f"  SUBID {subid}: {dam['DamName']} "
                  f"(CAP={regvol:.0f} MCM, H={dam['DAM_HGT_M']:.0f} m, "
                  f"purpose={purpose_names.get(purpose, '?')}, "
                  f"Q_mean={q_mean:.1f} m3/s)")

            # Write row
            vals = [
                str(subid),                    # subid
                str(purpose),                  # purpose
                f"{lake_depth:.1f}",           # lake_depth
                f"{regvol:.1f}",               # regvol (Mm3)
                f"{rate:.2f}",                 # rate
                f"{exp_val:.1f}",              # exp
                f"{w0ref:.1f}",                # w0ref
                f"{wamp:.2f}",                 # wamp (m)
                f"{qprod1:.2f}",               # qprod1 (m3/s)
                f"{qprod2:.2f}",               # qprod2 (m3/s)
                str(datum1),                   # datum1 (MMDD)
                str(datum2),                   # datum2 (MMDD)
                f"{minflow:.2f}",              # minflow (m3/s)
            ]
            # Monthly inflows
            for q in monthly_q:
                vals.append(f"{q:.2f}")

            f.write("\t".join(vals) + "\n")

    print(f"\nGenerated DamData.txt: {output_path}")
    print(f"  {len(assignments)} dam(s) configured")

    # Reminders
    print("\n--- IMPORTANT: DamData.txt requirements ---")
    print("1. DamData subid values MUST match SUBID values in GeoData.txt")
    print("2. Each dam subbasin must have an olake SLC class (GeoClass special=2)")
    print("3. The olake SLC fraction must be > 0 for dam subbasins in GeoData")
    print("4. Monthly inflows (qinfjan-qinfdec) are estimates -- for accurate")
    print("   regulation, first run a natural (no-dam) simulation and use those flows")
    print("5. If using both LakeData.txt and DamData.txt, DamData overrides")
    print("   LakeData for the same subbasin")
    print("6. DamData.txt goes in modeldir/ (same directory as GeoData.txt)")

    return assignments


def main():
    parser = argparse.ArgumentParser(
        description="Generate HYPE DamData.txt from GRanD"
    )
    parser.add_argument('--geodata', required=True,
                        help='Path to GeoData.txt')
    parser.add_argument('--output', required=True,
                        help='Output DamData.txt path')
    parser.add_argument('--lat', type=float, default=None,
                        help='Center latitude for dam search')
    parser.add_argument('--lon', type=float, default=None,
                        help='Center longitude for dam search')
    parser.add_argument('--search_radius_km', type=float, default=200,
                        help='Search radius in km (default: 200)')
    parser.add_argument('--dam_names', type=str, default=None,
                        help='Comma-separated dam names to include')
    parser.add_argument('--river', type=str, default=None,
                        help='River name filter')
    parser.add_argument('--purpose', type=int, default=None,
                        help='Purpose filter: 1=Irrigation, 2=WaterSupply, '
                             '3=FloodControl, 4=Hydropower')
    parser.add_argument('--climate', type=str, default="monsoon",
                        choices=["monsoon", "uniform"],
                        help='Climate type for monthly flow estimation')

    args = parser.parse_args()

    generate_damdata(
        geodata_path=args.geodata,
        output_path=args.output,
        lat=args.lat,
        lon=args.lon,
        search_radius_km=args.search_radius_km,
        dam_names=args.dam_names,
        river_name=args.river,
        purpose_filter=args.purpose,
        climate=args.climate,
    )


if __name__ == '__main__':
    main()
