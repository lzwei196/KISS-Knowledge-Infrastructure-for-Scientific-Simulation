#!/usr/bin/env python3
"""
create_site_file.py — Generate SHAW site characteristics file (.sit)

Reads soil properties from HWSD global database and DEM-derived
slope/aspect to produce a complete SHAW .sit file.

Usage:
    python create_site_file.py \
        --lat 46.75 --lon -116.95 --elev 750.0 \
        --slope 15.0 --aspect 180.0 \
        --start_jday 1 --start_year 2005 \
        --end_jday 365 --end_year 2005 \
        --output trial.sit \
        [--nplant 0] [--ns 11] [--max_depth 4.0] \
        [--iwrc 1] [--title "My Site"]
"""

import argparse
import sys
import os
import math
from pathlib import Path

# HWSD soil adapter
HWSD_RASTER = Path(os.path.join(os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "data/soil/HWSD_RASTER/hwsd.bil"))
HWSD_MDB = Path(os.path.join(os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "data/forcing/huaihe_raw/soil/HWSD.mdb"))


def get_hwsd_soil(lat, lon):
    """
    Query HWSD database for soil properties at a given lat/lon.
    Returns dict with sand, silt, clay, bulk_density, organic_matter, gravel
    for top and sub soil.
    """
    try:
        sys.path.insert(0, str(Path("/mnt/disk1/Hydrocraft_server/skills/vic-auto-run/s1_soil")))
        from hwsd_soil_adapter import query_hwsd_point
        props = query_hwsd_point(lat, lon, str(HWSD_RASTER), str(HWSD_MDB))
        return props
    except ImportError:
        print("WARNING: hwsd_soil_adapter not found. Using default soil properties.")
        return None


def pedotransfer_campbell(sand, clay, bulk_density):
    """
    Estimate Campbell soil water retention parameters from texture.
    Returns: psi_e (m), theta_s (m3/m3), b (dimensionless)
    Based on Rawls et al. (1982) and Clapp & Hornberger (1978).
    """
    # Porosity from bulk density (assume particle density 2650 kg/m3)
    porosity = 1.0 - bulk_density / 2650.0
    theta_s = min(porosity, 0.60)

    # Campbell b parameter from texture
    # Clapp & Hornberger (1978) regression
    b = 3.10 + 0.157 * clay - 0.003 * sand
    b = max(2.0, min(b, 12.0))

    # Air-entry potential (m, negative = suction)
    # Cosby et al. (1984)
    psi_e = -0.01 * (10.0 ** (1.54 - 0.0095 * sand + 0.0063 * (100 - sand - clay)))
    psi_e = max(psi_e, -1.0)
    psi_e = min(psi_e, -0.05)

    return psi_e, theta_s, b


def pedotransfer_ksat(sand, clay):
    """
    Estimate saturated hydraulic conductivity (cm/hr) from texture.
    Cosby et al. (1984).
    """
    # log10(Ksat) in inches/hr
    log_ksat_inhr = -0.6 + 0.0126 * sand - 0.0064 * clay
    ksat_inhr = 10.0 ** log_ksat_inhr
    ksat_cmhr = ksat_inhr * 2.54  # inches to cm
    return max(ksat_cmhr, 0.001)


def generate_soil_layers(ns, max_depth):
    """
    Generate soil node depths (m) with finer spacing near surface.
    ZS(1) must be 0.0.
    """
    depths = [0.0]
    if ns <= 2:
        depths.append(max_depth)
        return depths

    # Logarithmic spacing: fine near surface, coarser at depth
    # First few layers very thin (for freeze-thaw resolution)
    thin_layers = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 0.70, 1.00]
    if ns >= len(thin_layers):
        depths = thin_layers[:min(ns, len(thin_layers))]
        remaining = ns + 1 - len(depths)
        if remaining > 0:
            last = depths[-1]
            step = (max_depth - last) / remaining
            for i in range(1, remaining + 1):
                depths.append(round(last + step * i, 3))
    else:
        step = max_depth / ns
        for i in range(1, ns + 1):
            depths.append(round(step * i, 3))

    # Ensure last depth matches max_depth
    depths[-1] = max_depth
    return depths


def write_site_file(args):
    """Generate the SHAW .sit file."""

    # Get soil properties from HWSD
    hwsd = get_hwsd_soil(args.lat, args.lon)

    # Default soil properties if HWSD fails
    if hwsd is None:
        # Default: silt loam
        top_sand, top_silt, top_clay = 30.0, 50.0, 20.0
        sub_sand, sub_silt, sub_clay = 30.0, 50.0, 20.0
        bulk_density = 1400.0  # kg/m3
        organic_matter = 2.0  # percent
        gravel = 0.0
    else:
        top_sand = hwsd.get('t_sand', 30.0)
        top_silt = hwsd.get('t_silt', 50.0)
        top_clay = hwsd.get('t_clay', 20.0)
        sub_sand = hwsd.get('s_sand', 30.0)
        sub_silt = hwsd.get('s_silt', 50.0)
        sub_clay = hwsd.get('s_clay', 20.0)
        bulk_density = hwsd.get('t_bulk_density', 1400.0)
        if bulk_density is None or bulk_density < 500:
            bulk_density = 1400.0
        organic_matter = hwsd.get('t_oc', 1.0) * 1.724  # OC to OM
        gravel = hwsd.get('t_gravel', 0.0) or 0.0

    # Generate soil layer depths
    depths = generate_soil_layers(args.ns, args.max_depth)
    ns = len(depths) - 1  # Number of layers = nodes - 1... wait, NS = number of soil nodes
    # Actually in SHAW, NS = number of soil nodes, and depths has NS entries
    # But generate_soil_layers returns NS+1 entries (including surface=0)
    # Let's adjust: NS = args.ns, depths should have args.ns entries
    depths = generate_soil_layers(args.ns - 1, args.max_depth)
    if len(depths) < args.ns:
        # Pad to reach NS nodes
        while len(depths) < args.ns:
            last = depths[-1]
            depths.append(round(last + (args.max_depth - last) / (args.ns - len(depths) + 1), 3))
    depths = depths[:args.ns]
    depths[0] = 0.0
    depths[-1] = args.max_depth

    # Compute latitude degrees and minutes
    lat_deg = int(abs(args.lat))
    lat_min = (abs(args.lat) - lat_deg) * 60.0
    if args.lat < 0:
        lat_deg = -lat_deg

    # Compute soil hydraulic properties
    psi_e_top, theta_s_top, b_top = pedotransfer_campbell(top_sand, top_clay, bulk_density)
    ksat_top = pedotransfer_ksat(top_sand, top_clay)
    psi_e_sub, theta_s_sub, b_sub = pedotransfer_campbell(sub_sand, sub_clay, bulk_density)
    ksat_sub = pedotransfer_ksat(sub_sand, sub_clay)

    title = args.title or f"SHAW site at ({args.lat:.2f}, {args.lon:.2f})"

    lines = []

    # LINE A: Title
    lines.append(title)

    # LINE B: JSTART HRSTAR YRSTAR JEND YREND
    lines.append(f" {args.start_jday}  {args.start_hour}  {args.start_year}  {args.end_jday}  {args.end_year}")

    # LINE C: ALTDEG ALTMIN SLP ASPEC HRNOON ELEV
    lines.append(f" {lat_deg} {lat_min:.1f}  {args.slope:.1f} {args.aspect:.1f} {args.hrnoon:.1f} {args.elev:.1f}")

    # LINE D: NPLANT NSP NR NS NSALT TOLER NHRPDT LEVEL(1-6)
    lines.append(f" {args.nplant} {args.nsp} {args.nr} {args.ns} {args.nsalt} {args.toler}  {args.nhrpdt}  0 0 0 0 0 0")

    # LINE E: ZMCM HEIGHT PONDMX
    zmcm = 0.6 if args.nplant == 0 else 2.0
    height = args.meas_height
    lines.append(f" {zmcm}  {height:.1f}  {args.pondmx:.2f}")

    # LINE F: Plant canopy parameters (skip if NPLANT=0)
    if args.nplant > 0:
        # MCANFLG ISTOMATE CANMA CANMB WCANDT
        lines.append(f" 0  1  -53.72  1.32  0.0")
        # Lines F0-1 to F0-NPLANT (for each plant species)
        for j in range(args.nplant):
            # ITYPE PINTRCP XANGLE CANALB TCCRIT RSTOMO RSTEXP PLEAF0 RLEAF0 RROOT0
            lines.append(f" 1  0.25  1.0  100.  5.0  -300.  1.7E05  3.3E05")
            # Lines F0: PLTHGT DCHAR CLUMPNG PLTWGT PLTLAI ROOTDP
            lines.append(f" {args.plant_height}  {args.leaf_dim}  1.0  {args.plant_biomass}  {args.plant_lai}  {args.root_depth}")

    # LINE G: Snow parameters
    # ISNOTMP SNOTMP ZMSPCM ISNOPARM
    lines.append(f" 1  {args.snotmp:.1f}  0.15  0")

    # Lines G1 (snow layers) - skip if NSP=0
    if args.nsp > 0:
        for i in range(args.nsp):
            lines.append(f" 0.10  -2.0  0.0  200.0")

    # LINE H: Residue parameters (skip if NR=0)
    if args.nr > 0:
        lines.append(f" 0  0.00")  # NRCHANG GMCDT
        # LINE H1: ZRTHIK RLOAD COVER ALBRES RESCOF RESTKB
        lines.append(f" {args.residue_thick:.1f}  {args.residue_load:.0f}.  {args.residue_cover:.2f}  0.25  {args.residue_rescof:.0f}.  4.0")

    # LINES I: Solute parameters (skip if NSALT=0)
    # Not implemented for default case

    # LINE J1: Boundary conditions
    # IVLCBC ITMPBC ALBDRY ALBEXP IWRC IPHANTOM
    lines.append(f" {args.ivlcbc}  {args.itmpbc}  {args.albdry:.2f}  {args.albexp:.1f}  {args.iwrc}  0")

    # LINE J2: TSAVG (only if ITMPBC=1)
    if args.itmpbc == 1:
        lines.append(f" {args.tsavg:.1f}")

    # LINES J3: Soil layer properties
    for i, zs in enumerate(depths):
        # Determine if top or sub soil (top = first 30 cm)
        if zs <= 0.30:
            sand, silt, clay = top_sand, top_silt, top_clay
            rhob = bulk_density
            om = organic_matter
            ksat = ksat_top
            psi_e, theta_s, b = psi_e_top, theta_s_top, b_top
        else:
            sand, silt, clay = sub_sand, sub_silt, sub_clay
            rhob = bulk_density * 1.05  # sub typically denser
            om = max(organic_matter * 0.3, 0.1)  # less OM at depth
            ksat = ksat_sub
            psi_e, theta_s, b = psi_e_sub, theta_s_sub, b_sub

        rock = gravel
        satkl = 0.0  # No lateral flow by default

        if args.iwrc == 1:
            # Campbell: ZS SAND SILT CLAY ROCK OM RHOB SATCON SATKL psi_e theta_s b
            lines.append(
                f" {zs:.3f}  {sand:.0f}. {silt:.0f}. {clay:.0f}. {rock:.0f}. {om:.1f}  "
                f"{rhob:.0f}.  {ksat:.2f}  {satkl:.1f}  {psi_e:.2f}  {theta_s:.2f}  {b:.2f}"
            )
        elif args.iwrc == 2:
            # Brooks-Corey: + lambda, theta_r, l
            lam = 1.0 / b  # approximate
            theta_r = 0.01 + 0.001 * clay
            l_param = 2.0
            lines.append(
                f" {zs:.3f}  {sand:.0f}. {silt:.0f}. {clay:.0f}. {rock:.0f}. {om:.1f}  "
                f"{rhob:.0f}.  {ksat:.2f}  {satkl:.1f}  {psi_e:.2f}  {theta_s:.2f}  "
                f"{lam:.2f}  {theta_r:.3f}  {l_param:.1f}"
            )
        elif args.iwrc == 3:
            # Van Genuchten: psi_e=0, theta_s, n, theta_r, l, alpha
            # Convert Campbell to VG approximately
            n_vg = 1.0 + b / 2.0
            n_vg = max(1.1, min(n_vg, 5.0))
            theta_r = 0.01 + 0.001 * clay
            l_vg = 0.5
            alpha = 1.0 / abs(psi_e) if abs(psi_e) > 0.01 else 5.0
            lines.append(
                f" {zs:.3f}  {sand:.0f}. {silt:.0f}. {clay:.0f}. {rock:.0f}. {om:.1f}  "
                f"{rhob:.0f}.  {ksat:.2f}  {satkl:.1f}  0.0  {theta_s:.2f}  "
                f"{n_vg:.2f}  {theta_r:.3f}  {l_vg:.1f}  {alpha:.2f}"
            )

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    print(f"Site file written to: {output_path}")
    print(f"  Soil nodes: {args.ns}")
    print(f"  Max depth: {args.max_depth} m")
    print(f"  Texture (top): sand={top_sand:.0f}% silt={top_silt:.0f}% clay={top_clay:.0f}%")
    print(f"  Ksat (top): {ksat_top:.3f} cm/hr")
    print(f"  Water retention: IWRC={args.iwrc} ({'Campbell' if args.iwrc==1 else 'Brooks-Corey' if args.iwrc==2 else 'Van Genuchten'})")

    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description="Generate SHAW site characteristics file")
    parser.add_argument("--lat", type=float, required=True, help="Latitude (degrees)")
    parser.add_argument("--lon", type=float, required=True, help="Longitude (degrees)")
    parser.add_argument("--elev", type=float, default=500.0, help="Elevation (m)")
    parser.add_argument("--slope", type=float, default=0.0, help="Slope (%%)")
    parser.add_argument("--aspect", type=float, default=0.0, help="Aspect (degrees from N)")
    parser.add_argument("--start_jday", type=int, required=True, help="Start day of year")
    parser.add_argument("--start_year", type=int, required=True, help="Start year")
    parser.add_argument("--start_hour", type=int, default=0, help="Start hour")
    parser.add_argument("--end_jday", type=int, required=True, help="End day of year")
    parser.add_argument("--end_year", type=int, required=True, help="End year")
    parser.add_argument("--output", type=str, required=True, help="Output .sit file path")
    parser.add_argument("--title", type=str, default=None, help="Simulation title")
    parser.add_argument("--ns", type=int, default=11, help="Number of soil nodes (2-50)")
    parser.add_argument("--max_depth", type=float, default=4.0, help="Maximum soil depth (m)")
    parser.add_argument("--nplant", type=int, default=0, help="Number of plant species")
    parser.add_argument("--plant_height", type=float, default=0.5, help="Plant height (m)")
    parser.add_argument("--plant_lai", type=float, default=2.0, help="Plant LAI")
    parser.add_argument("--plant_biomass", type=float, default=0.5, help="Plant biomass (kg/m2)")
    parser.add_argument("--leaf_dim", type=float, default=3.0, help="Leaf dimension (cm)")
    parser.add_argument("--root_depth", type=float, default=0.5, help="Root depth (m)")
    parser.add_argument("--nsp", type=int, default=0, help="Initial snow layers")
    parser.add_argument("--nr", type=int, default=0, help="Residue nodes (0=none)")
    parser.add_argument("--nsalt", type=int, default=0, help="Number of solute types")
    parser.add_argument("--toler", type=float, default=0.01, help="Convergence tolerance")
    parser.add_argument("--nhrpdt", type=int, default=1, help="Hours per time step")
    parser.add_argument("--meas_height", type=float, default=3.0, help="Measurement height (m)")
    parser.add_argument("--pondmx", type=float, default=0.0, help="Max ponding depth (cm)")
    parser.add_argument("--snotmp", type=float, default=1.5, help="Snow threshold temp (C)")
    parser.add_argument("--residue_thick", type=float, default=2.0, help="Residue thickness (cm)")
    parser.add_argument("--residue_load", type=float, default=6000.0, help="Residue load (kg/ha)")
    parser.add_argument("--residue_cover", type=float, default=0.90, help="Residue cover fraction")
    parser.add_argument("--residue_rescof", type=float, default=50000.0, help="Residue resistance (s/m)")
    parser.add_argument("--iwrc", type=int, default=1, choices=[1, 2, 3],
                        help="Water retention: 1=Campbell, 2=Brooks-Corey, 3=Van Genuchten")
    parser.add_argument("--ivlcbc", type=int, default=1, help="Lower BC: 0=water content, 1=unit gradient")
    parser.add_argument("--itmpbc", type=int, default=1, help="Temp BC: 0=track data, 1=estimated, 2=no flux")
    parser.add_argument("--tsavg", type=float, default=8.0, help="Average annual soil temp (C)")
    parser.add_argument("--albdry", type=float, default=0.25, help="Dry soil albedo")
    parser.add_argument("--albexp", type=float, default=2.0, help="Albedo exponent")
    parser.add_argument("--hrnoon", type=float, default=12.0, help="Solar noon hour")

    args = parser.parse_args()

    if args.ns < 2 or args.ns > 50:
        print("ERROR: NS must be between 2 and 50")
        sys.exit(1)

    write_site_file(args)


if __name__ == "__main__":
    main()
