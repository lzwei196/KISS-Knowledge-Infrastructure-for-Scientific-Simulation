#!/usr/bin/env python3
"""Generate HYPE LakeData.txt from HydroLAKES and GRanD databases.

Identifies outlet lakes (olake) within the basin subbasins by spatial
query against HydroLAKES and GRanD, then generates LakeData.txt with
proper column format for HYPE v5.35.0.

LakeData.txt columns (from HYPE source data.f90 load_lakedata):
  Required: lakedataid, ldtype
  Optional: area, lake_depth, lake_shape, w0ref, deltaw0, rate, exp,
            regvol, wamp, qprod1, qprod2, maxqprod, minflow, datum1,
            datum2, qamp, qpha, limqprod, lakeid

GeoData.txt must include:
  - lakedataid column: integer ID linking subbasin to LakeData row
  - lake_depth column: lake mean depth (m), read from GeoData or overridden by LakeData

GeoClass.txt must have an SLC with special=2 (olake class) and the
corresponding SLC fraction must be >0 in GeoData for subbasins with lakes.

Usage:
    python generate_lakedata.py \\
        --geodata modelfiles/GeoData.txt \\
        --geoclass modelfiles/GeoClass.txt \\
        --output modelfiles/LakeData.txt \\
        [--search_radius_km 50] \\
        [--min_lake_area_km2 1.0] \\
        [--update_geodata]

    # With explicit subbasin lat/lon for lumped setups:
    python generate_lakedata.py \\
        --geodata modelfiles/GeoData.txt \\
        --geoclass modelfiles/GeoClass.txt \\
        --output modelfiles/LakeData.txt \\
        --lat 32.4 --lon 115.7 --search_radius_km 200
"""

import argparse
import math
import os
import sys

# Data KI paths
HYDROLAKES_SHAPEFILE = (
    "KISSPATH_DATA/lakes/"
    "HydroLAKES_polys_v10_shp/HydroLAKES_polys_v10.shp"
)
GRAND_CSV = (
    "KISSPATH_BINARIES/cmf_v420_pkg/map/data/"
    "GRanD_allocated.csv"
)


def load_geodata(geodata_path):
    """Read GeoData.txt into list of dicts, skipping !! comment lines."""
    with open(geodata_path) as f:
        lines = f.readlines()

    # Skip comment lines
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


def load_geoclass(geoclass_path):
    """Read GeoClass.txt to find olake SLC class (special=2)."""
    with open(geoclass_path) as f:
        lines = f.readlines()

    data_start = 0
    for i, line in enumerate(lines):
        if not line.startswith('!!'):
            data_start = i
            break

    header = lines[data_start].strip().split('\t')
    # Normalize header: strip whitespace
    header = [h.strip() for h in header]

    olake_slc_ids = []
    for line in lines[data_start + 1:]:
        if line.strip():
            vals = line.strip().split('\t')
            vals = [v.strip() for v in vals]
            # GeoClass columns: SLC_ID landuse soil crop crop2 rotation vegtype special ...
            # special is column index 7 (0-based)
            if len(vals) > 7:
                slc_id = int(vals[0])
                special = int(vals[7])
                if special == 2:
                    olake_slc_ids.append(slc_id)

    return olake_slc_ids


def search_hydrolakes_near(lat, lon, radius_km, min_area_km2=1.0):
    """Search HydroLAKES for lakes near a point."""
    try:
        import geopandas as gpd
    except ImportError:
        print("WARNING: geopandas not available. Cannot query HydroLAKES shapefile.")
        return []

    # Bounding box from radius
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    bbox = (lon - dlon, lat - dlat, lon + dlon, lat + dlat)

    try:
        gdf = gpd.read_file(HYDROLAKES_SHAPEFILE, bbox=bbox)
    except Exception as e:
        print(f"WARNING: Could not read HydroLAKES: {e}")
        return []

    if len(gdf) == 0:
        return []

    # Filter by minimum area
    gdf = gdf[gdf["Lake_area"] >= min_area_km2]

    # Compute distance
    cos_lat = math.cos(math.radians(lat))
    gdf["_dist_km"] = (
        ((gdf["Pour_lat"] - lat) * 111.0) ** 2
        + ((gdf["Pour_long"] - lon) * 111.0 * cos_lat) ** 2
    ) ** 0.5

    # Filter by actual radius
    gdf = gdf[gdf["_dist_km"] <= radius_km]

    lakes = []
    for _, row in gdf.iterrows():
        lake = {
            "Hylak_id": int(row["Hylak_id"]),
            "Lake_name": str(row.get("Lake_name", "")),
            "Lake_area_km2": float(row["Lake_area"]),
            "Depth_avg_m": float(row["Depth_avg"]),
            "Vol_total_MCM": float(row["Vol_total"]),
            "Dis_avg_m3s": float(row["Dis_avg"]),
            "Pour_lat": float(row["Pour_lat"]),
            "Pour_long": float(row["Pour_long"]),
            "Elevation_m": float(row.get("Elevation", 0)),
            "Grand_id": int(row.get("Grand_id", 0)),
            "dist_km": float(row["_dist_km"]),
        }
        lakes.append(lake)

    lakes.sort(key=lambda x: -x["Lake_area_km2"])
    return lakes


def search_grand_near(lat, lon, radius_km):
    """Search GRanD for dams near a point."""
    import csv

    if not os.path.exists(GRAND_CSV):
        print(f"WARNING: GRanD CSV not found at {GRAND_CSV}")
        return []

    dams = []
    cos_lat = math.cos(math.radians(lat))
    with open(GRAND_CSV, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dlat = (float(row["lat_ori"]) - lat) * 111.0
                dlon = (float(row["lon_ori"]) - lon) * 111.0 * cos_lat
                dist = math.sqrt(dlat**2 + dlon**2)
                if dist <= radius_km:
                    dams.append({
                        "ID": int(row["ID"]),
                        "DamName": row["DamName"],
                        "RiverName": row["RiverName"],
                        "lat": float(row["lat_ori"]),
                        "lon": float(row["lon_ori"]),
                        "CAP_MCM": float(row["CAP_MCM"]),
                        "DAM_HGT_M": float(row["DAM_HGT_M"]),
                        "YEAR": int(row["YEAR"]),
                        "area_km2": float(row["area_ori"]),
                        "dist_km": round(dist, 1),
                    })
            except (ValueError, KeyError):
                continue

    dams.sort(key=lambda x: x["dist_km"])
    return dams


def assign_lakes_to_subbasins(subbasins, lakes, dams, olake_slc_ids):
    """Assign HydroLAKES lakes to nearest subbasin with olake SLC fraction.

    Returns list of dicts with lake+subbasin info for LakeData generation.
    """
    assignments = []

    for lake in lakes:
        best_sub = None
        best_dist = float('inf')
        for sub in subbasins:
            lat = sub.get('latitude', sub.get('LATITUDE', 0))
            lon = sub.get('longitude', sub.get('LONGITUDE', 0))
            if lat == 0 and lon == 0:
                continue

            # Check if subbasin has olake SLC fraction > 0
            has_olake = False
            for slc_id in olake_slc_ids:
                col = f"SLC_{slc_id}"
                frac = float(sub.get(col, sub.get(col.lower(), 0)))
                if frac > 0:
                    has_olake = True
                    break

            if not has_olake:
                continue

            dlat = (lake["Pour_lat"] - lat) * 111.0
            cos_lat = math.cos(math.radians(lat))
            dlon = (lake["Pour_long"] - lon) * 111.0 * cos_lat
            dist = math.sqrt(dlat**2 + dlon**2)

            if dist < best_dist:
                best_dist = dist
                best_sub = sub

        if best_sub is not None:
            subid = int(best_sub.get('SUBID', best_sub.get('subid', 0)))

            # Check if dam exists for this lake (via Grand_id or proximity)
            matched_dam = None
            if lake.get("Grand_id", 0) > 0:
                for dam in dams:
                    if dam["ID"] == lake["Grand_id"]:
                        matched_dam = dam
                        break

            if matched_dam is None:
                # Try proximity match (within 5 km)
                for dam in dams:
                    dlat = (lake["Pour_lat"] - dam["lat"]) * 111.0
                    cos_lat = math.cos(math.radians(lake["Pour_lat"]))
                    dlon = (lake["Pour_long"] - dam["lon"]) * 111.0 * cos_lat
                    dist = math.sqrt(dlat**2 + dlon**2)
                    if dist < 5.0:
                        matched_dam = dam
                        break

            assignments.append({
                "subid": subid,
                "lake": lake,
                "dam": matched_dam,
                "dist_to_sub_km": best_dist,
            })

    # Deduplicate: one lake per subbasin (largest lake wins)
    sub_lakes = {}
    for a in assignments:
        sid = a["subid"]
        if sid not in sub_lakes or a["lake"]["Lake_area_km2"] > sub_lakes[sid]["lake"]["Lake_area_km2"]:
            sub_lakes[sid] = a

    return list(sub_lakes.values())


def estimate_rating_curve(lake_area_km2, depth_m, dis_avg_m3s):
    """Estimate rating curve parameters (rate, exp) for an outlet lake.

    Uses the simple relationship: Q = rate * (w - w0)^exp
    where w is water level above threshold w0.

    For natural lakes without regulation:
      rate = Q_avg / (0.1 * depth)^exp  (assume 10% of depth as typical head)
      exp = 1.5 (typical for broad-crested weir)
    """
    exp_val = 1.5  # typical rating curve exponent

    # Estimate typical head as fraction of depth
    typical_head_m = max(0.1 * depth_m, 0.5)

    if dis_avg_m3s > 0:
        rate = dis_avg_m3s / (typical_head_m ** exp_val)
    else:
        # Fallback: estimate from lake area
        # Q ~ 0.01 * Area_km2 m3/s is a rough estimate for small lakes
        q_est = max(0.01 * lake_area_km2, 0.1)
        rate = q_est / (typical_head_m ** exp_val)

    return max(rate, 0.01), exp_val


def generate_lakedata(geodata_path, geoclass_path, output_path,
                      lat=None, lon=None, search_radius_km=50,
                      min_lake_area_km2=1.0, update_geodata=False):
    """Generate LakeData.txt from HydroLAKES + GRanD data.

    LakeData.txt format (HYPE v5.35.0 data.f90):
      Tab-separated, !! comments allowed at top
      Required columns: lakedataid, ldtype
      Key columns: area, lake_depth, lake_shape, rate, exp, w0ref,
                   regvol, wamp, qprod1, qprod2, datum1, datum2,
                   minflow, maxqprod, qamp, qpha, limqprod

    ldtype values:
      1 = simple olake (single outlet)
      5 = outlet 1 (two-outlet lake)
      6 = outlet 2 (two-outlet lake)
      7 = lake basin (equal water level multi-basin)
    """
    header, subbasins = load_geodata(geodata_path)
    olake_slc_ids = load_geoclass(geoclass_path)

    if not olake_slc_ids:
        print("WARNING: No olake SLC class (special=2) found in GeoClass.txt.")
        print("Lake/reservoir simulation requires an SLC with special=2.")
        print("LakeData.txt NOT generated.")
        return

    # Determine search center
    if lat is not None and lon is not None:
        center_lat, center_lon = lat, lon
    else:
        # Use centroid of all subbasins
        lats = [float(s.get('latitude', s.get('LATITUDE', 0))) for s in subbasins]
        lons = [float(s.get('longitude', s.get('LONGITUDE', 0))) for s in subbasins]
        lats = [x for x in lats if x != 0]
        lons = [x for x in lons if x != 0]
        if not lats or not lons:
            print("ERROR: Cannot determine basin center. Provide --lat and --lon.")
            sys.exit(1)
        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)

    print(f"Searching for lakes/dams near ({center_lat:.2f}, {center_lon:.2f}), "
          f"radius={search_radius_km} km")

    # Search databases
    lakes = search_hydrolakes_near(center_lat, center_lon,
                                    search_radius_km, min_lake_area_km2)
    dams = search_grand_near(center_lat, center_lon, search_radius_km)

    print(f"  HydroLAKES: {len(lakes)} lake(s) >= {min_lake_area_km2} km^2")
    print(f"  GRanD: {len(dams)} dam(s)")

    if not lakes and not dams:
        print("No lakes or dams found in search area.")
        print("LakeData.txt NOT generated (not needed).")
        return

    # Assign lakes to subbasins
    assignments = assign_lakes_to_subbasins(subbasins, lakes, dams, olake_slc_ids)

    if not assignments:
        print("No lakes could be assigned to subbasins with olake SLC class.")
        print("Ensure GeoData has subbasins with SLC fraction > 0 for the water class,")
        print("and that GeoClass has special=2 on the water SLC.")
        print("LakeData.txt NOT generated.")
        return

    # Generate LakeData.txt
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    with open(output_path, 'w') as f:
        f.write("!! LakeData.txt generated by HYPE KI generate_lakedata.py\n")
        f.write("!! Sources: HydroLAKES v10, GRanD\n")
        f.write("!! WARNING: Rating curve parameters are estimated and should be calibrated\n")

        # Columns: lakedataid ldtype area lake_depth rate exp w0ref regvol wamp qprod1 qprod2 datum1 datum2 minflow
        cols = ["lakedataid", "ldtype", "area", "lake_depth", "lake_shape",
                "rate", "exp", "w0ref", "regvol", "wamp",
                "qprod1", "qprod2", "datum1", "datum2", "minflow"]
        f.write("\t".join(cols) + "\n")

        for i, a in enumerate(assignments, start=1):
            lake = a["lake"]
            dam = a["dam"]
            subid = a["subid"]

            # lakedataid = unique ID linking GeoData to LakeData
            lakedataid = subid  # Use SUBID as lakedataid for simple mapping

            # Lake properties from HydroLAKES
            lake_area_m2 = lake["Lake_area_km2"] * 1e6
            depth_m = lake["Depth_avg_m"]
            dis_avg = lake["Dis_avg_m3s"]

            # lake_shape (depth exponent): 1.0 for flat bottom, 2.0 for conical
            lake_shape = 1.0

            # Rating curve
            rate, exp_val = estimate_rating_curve(
                lake["Lake_area_km2"], depth_m, dis_avg
            )

            # w0ref (reference water level above which outflow occurs) = 0
            w0ref = 0.0

            # Regulation parameters
            if dam is not None:
                # Regulated lake/reservoir
                regvol = dam["CAP_MCM"]  # Regulation volume in Mm3
                # wamp: regulation amplitude (m) ~ regvol_m3 / area_m2
                if lake_area_m2 > 0:
                    wamp = regvol * 1e6 / lake_area_m2 * 0.5  # Half of max drawdown
                else:
                    wamp = 1.0

                # Production flow: estimate from mean discharge
                if dis_avg > 0:
                    qprod1 = dis_avg * 0.8  # 80% of mean flow for production
                    qprod2 = dis_avg * 0.5  # 50% of mean flow for low season
                else:
                    qprod1 = max(regvol * 1e6 / (365 * 86400) * 0.8, 1.0)
                    qprod2 = qprod1 * 0.5

                # Seasonal dates: datum1=high flow start, datum2=low flow start
                # For East Asian monsoon: high flow Jun-Sep
                datum1 = 601   # June 1 (MMDD format)
                datum2 = 1001  # October 1

                # Minimum environmental flow
                minflow = dis_avg * 0.1 if dis_avg > 0 else 0.5

                print(f"  SUBID {subid}: {lake.get('Lake_name', 'unnamed')} "
                      f"({lake['Lake_area_km2']:.1f} km^2) + dam '{dam['DamName']}' "
                      f"(CAP={dam['CAP_MCM']:.0f} MCM)")
            else:
                # Natural lake, no regulation
                regvol = -9999
                wamp = -9999
                qprod1 = -9999
                qprod2 = -9999
                datum1 = -9999
                datum2 = -9999
                minflow = -9999

                print(f"  SUBID {subid}: {lake.get('Lake_name', 'unnamed')} "
                      f"({lake['Lake_area_km2']:.1f} km^2, natural)")

            # Write row
            vals = [
                str(lakedataid),                    # lakedataid
                "1",                                # ldtype (simple olake)
                f"{lake_area_m2:.0f}",              # area (m^2)
                f"{depth_m:.1f}",                   # lake_depth (m)
                f"{lake_shape:.1f}",                # lake_shape
                f"{rate:.4f}",                       # rate
                f"{exp_val:.1f}",                    # exp
                f"{w0ref:.1f}",                      # w0ref
                f"{regvol:.1f}" if regvol != -9999 else "-9999",  # regvol (Mm3)
                f"{wamp:.2f}" if wamp != -9999 else "-9999",      # wamp (m)
                f"{qprod1:.2f}" if qprod1 != -9999 else "-9999",  # qprod1 (m3/s)
                f"{qprod2:.2f}" if qprod2 != -9999 else "-9999",  # qprod2 (m3/s)
                str(datum1),                         # datum1 (MMDD)
                str(datum2),                         # datum2 (MMDD)
                f"{minflow:.2f}" if minflow != -9999 else "-9999",  # minflow (m3/s)
            ]
            f.write("\t".join(vals) + "\n")

    print(f"\nGenerated LakeData.txt: {output_path}")
    print(f"  {len(assignments)} lake(s) configured")

    # Update GeoData.txt if requested
    if update_geodata:
        _update_geodata_lakedataid(geodata_path, assignments)

    # Print reminder about GeoData requirements
    print("\n--- IMPORTANT: GeoData.txt requirements for lakes ---")
    print("1. Add 'lakedataid' column to GeoData.txt header")
    print("   Set lakedataid = SUBID for subbasins with lakes, 0 for others")
    print("2. Ensure 'lake_depth' column has values > 0 for lake subbasins")
    print("3. Ensure GeoClass has special=2 for the water/olake SLC class")
    print("4. Ensure the olake SLC fraction > 0 in GeoData for lake subbasins")
    print("5. Add lake parameters to par.txt:")
    print("   gratk   0.5    !! General lake rating curve coefficient")
    print("   gratefk 1.5    !! General lake rating curve exponent factor")

    return assignments


def _update_geodata_lakedataid(geodata_path, assignments):
    """Add or update lakedataid and lake_depth columns in GeoData.txt."""
    with open(geodata_path) as f:
        lines = f.readlines()

    # Find header
    data_start = 0
    for i, line in enumerate(lines):
        if not line.startswith('!!'):
            data_start = i
            break

    header = lines[data_start].strip().split('\t')
    header_lower = [h.lower().strip() for h in header]

    # Build assignment lookup
    lakedataid_map = {}
    depth_map = {}
    for a in assignments:
        lakedataid_map[a["subid"]] = a["subid"]
        depth_map[a["subid"]] = a["lake"]["Depth_avg_m"]

    # Check if columns exist
    has_lakedataid = 'lakedataid' in header_lower
    has_lake_depth = 'lake_depth' in header_lower

    needs_update = False

    if not has_lakedataid:
        header.append('lakedataid')
        needs_update = True
        print("  Adding 'lakedataid' column to GeoData.txt")

    if not has_lake_depth:
        header.append('lake_depth')
        needs_update = True
        print("  Adding 'lake_depth' column to GeoData.txt")

    # Rebuild file
    new_lines = lines[:data_start]
    new_lines.append('\t'.join(header) + '\n')

    # Get SUBID column index
    subid_idx = None
    for j, h in enumerate(header_lower):
        if h == 'subid':
            subid_idx = j
            break

    lakedataid_idx = None
    lake_depth_idx = None
    for j, h in enumerate([x.lower().strip() for x in header]):
        if h == 'lakedataid':
            lakedataid_idx = j
        if h == 'lake_depth':
            lake_depth_idx = j

    for line in lines[data_start + 1:]:
        if not line.strip():
            new_lines.append(line)
            continue
        vals = line.strip().split('\t')

        # Extend vals if needed
        while len(vals) < len(header):
            vals.append('0')

        if subid_idx is not None:
            try:
                subid = int(float(vals[subid_idx]))
            except (ValueError, IndexError):
                subid = 0

            if lakedataid_idx is not None:
                vals[lakedataid_idx] = str(lakedataid_map.get(subid, 0))
            if lake_depth_idx is not None and subid in depth_map:
                vals[lake_depth_idx] = f"{depth_map[subid]:.1f}"

        new_lines.append('\t'.join(vals) + '\n')

    with open(geodata_path, 'w') as f:
        f.writelines(new_lines)

    print(f"  Updated GeoData.txt: {geodata_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate HYPE LakeData.txt from HydroLAKES + GRanD"
    )
    parser.add_argument('--geodata', required=True,
                        help='Path to GeoData.txt')
    parser.add_argument('--geoclass', required=True,
                        help='Path to GeoClass.txt')
    parser.add_argument('--output', required=True,
                        help='Output LakeData.txt path')
    parser.add_argument('--lat', type=float, default=None,
                        help='Center latitude for lake search')
    parser.add_argument('--lon', type=float, default=None,
                        help='Center longitude for lake search')
    parser.add_argument('--search_radius_km', type=float, default=50,
                        help='Search radius in km (default: 50)')
    parser.add_argument('--min_lake_area_km2', type=float, default=1.0,
                        help='Minimum lake area in km^2 (default: 1.0)')
    parser.add_argument('--update_geodata', action='store_true',
                        help='Add lakedataid + lake_depth columns to GeoData.txt')

    args = parser.parse_args()

    generate_lakedata(
        geodata_path=args.geodata,
        geoclass_path=args.geoclass,
        output_path=args.output,
        lat=args.lat,
        lon=args.lon,
        search_radius_km=args.search_radius_km,
        min_lake_area_km2=args.min_lake_area_km2,
        update_geodata=args.update_geodata,
    )


if __name__ == '__main__':
    main()
