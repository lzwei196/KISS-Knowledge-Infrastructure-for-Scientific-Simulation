#!/usr/bin/env python3
"""
vic_to_shaw_soil.py — Convert VIC soil parameters to SHAW site file soil layers.

VIC uses 3 soil layers with bulk properties. SHAW uses up to 50 soil nodes
with detailed per-node texture, Ksat, and water retention parameters.

This tool:
1. Reads VIC SOIL_PARAM file for a specific grid cell
2. Maps VIC 3-layer parameters to SHAW multi-node discretization
3. Generates the soil section (Lines J) for the SHAW .sit file

VIC soil params -> SHAW soil params mapping:
    VIC             SHAW            Units
    -----           -----           -----
    infilt (binfilt) -> N/A (SHAW computes infiltration from physics)
    Ds, Dsmax, Ws   -> N/A (SHAW doesn't use VIC baseflow params)
    depth(layer)     -> ZS(node)     m
    Ksat(layer)      -> KSAT         cm/hr  (VIC: mm/day ÷ 240 = cm/hr)
    bulk_density     -> RHOB         kg/m3
    Wcr(layer)       -> N/A (not directly used)
    Wpwp(layer)      -> N/A
    soil_density     -> particle density, used for porosity
    bubble          -> BCAP          m (VIC: cm / 100; -9999 → PTF from b)
    quartz          -> QUARTZ        fraction (VIC cols 30-32, HWSD-derived, 0-1)
    expt            -> BPAR (Campbell b)  (VIC expt = 2*b+3, so b = (expt-3)/2)

UNIT TRAPS:
    - VIC Ksat is mm/DAY (not mm/s). SHAW Ksat is cm/hr. Factor: mm/day ÷ 240
    - VIC bubble (air entry) is cm, often -9999. SHAW BCAP is m (negative).
      If bubble==-9999 use PTF: BCAP = -0.05 × sqrt(b_campbell)
    - VIC expt = 2*b+3 (Campbell b). SHAW BPAR = (expt-3)/2.
    - VIC bulk_density is kg/m3. SHAW RHOB is kg/m3. Same units.
    - VIC quartz (cols 30-32) is fraction 0-1. SHAW QUARTZ same. Use directly.

Usage:
    python vic_to_shaw_soil.py \
        --soil_param outputs/<run>/vic_temp/soil/SOIL_PARAM_COMPLETE.txt \
        --cell_id 1 \
        --ns 15 --max_depth 4.0 \
        --output shaw_soil_section.txt
"""

import argparse
import sys
from pathlib import Path


def parse_vic_soil_param(filepath, cell_id=None, lat=None, lon=None):
    """
    Parse VIC SOIL_PARAM file for a specific grid cell.

    VIC soil param columns (standard HydroCraft format):
    0: run_cell, 1: gridcel, 2: lat, 3: lon, 4: infilt,
    5: Ds, 6: Dsmax, 7: Ws, 8: c,
    9: expt_1, 10: expt_2, 11: expt_3,
    12: Ksat_1, 13: Ksat_2, 14: Ksat_3,
    15: phi_s_1, 16: phi_s_2, 17: phi_s_3 (= -999 typically),
    18: init_moist_1, 19: init_moist_2, 20: init_moist_3,
    21: elev, 22: depth_1, 23: depth_2, 24: depth_3,
    25: avg_T, 26: dp (damping depth),
    27: bubble_1, 28: bubble_2, 29: bubble_3,
    30: quartz_1, 31: quartz_2, 32: quartz_3,
    33: bulk_density_1, 34: bulk_density_2, 35: bulk_density_3,
    36: soil_density_1, 37: soil_density_2, 38: soil_density_3,
    39: off_gmt, 40: Wcr_FRACT_1, 41: Wcr_FRACT_2, 42: Wcr_FRACT_3,
    43: Wpwp_FRACT_1, 44: Wpwp_FRACT_2, 45: Wpwp_FRACT_3,
    46: rough, 47: snow_rough,
    48+: Nveg, etc.
    """
    with open(filepath, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 39:
                continue

            try:
                cid = int(parts[1])
                clat = float(parts[2])
                clon = float(parts[3])
            except (ValueError, IndexError):
                continue

            # Match by cell_id or lat/lon
            match = False
            if cell_id is not None and cid == cell_id:
                match = True
            elif lat is not None and lon is not None:
                if abs(clat - lat) < 0.01 and abs(clon - lon) < 0.01:
                    match = True

            if not match:
                continue

            # Extract parameters
            params = {
                'lat': clat,
                'lon': clon,
                'elev': float(parts[21]),
                'avg_T': float(parts[25]),
                'layers': [],
            }

            for i in range(3):
                layer = {
                    'depth': float(parts[22 + i]),           # m
                    'expt': float(parts[9 + i]),             # VIC exponent
                    'ksat_mm_day': float(parts[12 + i]),     # mm/day (NOT mm/s)
                    'bubble_cm': float(parts[27 + i]),       # cm (often -9999 = missing)
                    'quartz': float(parts[30 + i]),          # 0-1 fraction from HWSD
                    'bulk_density': float(parts[33 + i]),    # kg/m3
                    'soil_density': float(parts[36 + i]),    # kg/m3
                    'init_moist': float(parts[18 + i]),      # mm
                }
                # Ksat: VIC stores mm/day; SHAW needs cm/hr → divide by 240
                layer['ksat_cm_hr'] = layer['ksat_mm_day'] / 240.0
                # Campbell b from VIC expt (expt = 2b+3)
                b = (layer['expt'] - 3.0) / 2.0
                layer['b_campbell'] = b
                # Air entry pressure: VIC bubble is cm, SHAW BCAP is m (negative).
                # -9999 = missing → use PTF: BCAP ≈ -0.05 × sqrt(b) m
                bub = layer['bubble_cm']
                if bub <= 0 or bub == -9999:
                    layer['psi_e_m'] = -0.05 * (b ** 0.5)
                else:
                    layer['psi_e_m'] = -bub / 100.0  # cm → m, keep negative
                layer['porosity'] = 1.0 - layer['bulk_density'] / layer['soil_density']
                layer['theta_s'] = min(layer['porosity'], 0.60)
                layer['bd_raw'] = layer['bulk_density']  # store original before correction

                params['layers'].append(layer)

            return params

    print(f"ERROR: Cell not found in {filepath}")
    return None


def apply_mollisol_bd_correction(vic_params):
    """
    Correct HWSD bulk density for NE China Mollisols (Black Soil).

    HWSD reports BD ≈ 1400–1600 kg/m³ for Songnen/Sanjiang Plain Black Soil,
    but field measurements show BD = 1050–1250 kg/m³ (topsoil) due to high
    organic matter content (T_OC ≈ 3–8%) that HWSD mapping underweights.

    Correction: for layers where BD > 1250 kg/m³, scale by 0.82 (18% reduction).
    This brings the typical 1448 → 1187 kg/m³, increasing theta_s from 0.46 → 0.56.
    Surface layer (layer 0) gets the full reduction; deeper layers proportionally less
    because HWSD subsoil BD is somewhat more reliable.
    """
    scale = [0.82, 0.88, 0.94]   # layer 1 (topsoil), layer 2 (subsoil), layer 3 (deep)
    for i, layer in enumerate(vic_params['layers']):
        if layer['bulk_density'] > 1250:
            layer['bulk_density'] = layer['bulk_density'] * scale[i]
            layer['porosity'] = 1.0 - layer['bulk_density'] / layer['soil_density']
            layer['theta_s'] = min(layer['porosity'], 0.60)
    return vic_params


def distribute_to_shaw_nodes(vic_params, ns, max_depth):
    """
    Distribute VIC 3-layer parameters to SHAW multi-node discretization.

    VIC layers are thick (e.g., 0.1m, 0.5m, 1.5m).
    SHAW needs finer nodes for freeze-thaw resolution.
    """
    # VIC layer boundaries
    vic_depths = [0.0]
    for layer in vic_params['layers']:
        vic_depths.append(vic_depths[-1] + layer['depth'])

    # Generate SHAW node depths (finer near surface)
    shaw_depths = [0.0]
    # Fine near surface: 5cm intervals to 30cm
    fine_depths = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
    # Medium: 20cm intervals to 1m
    med_depths = [0.50, 0.70, 1.00]
    # Coarse: fill remaining
    all_candidate = fine_depths + med_depths

    for d in all_candidate:
        if d < max_depth and len(shaw_depths) < ns:
            shaw_depths.append(d)

    # Fill remaining nodes
    if len(shaw_depths) < ns:
        last = shaw_depths[-1]
        remaining = ns - len(shaw_depths)
        step = (max_depth - last) / remaining
        for i in range(1, remaining + 1):
            shaw_depths.append(round(last + step * i, 3))

    shaw_depths = shaw_depths[:ns]
    shaw_depths[-1] = max_depth

    # Map each SHAW node to VIC layer
    nodes = []
    for zs in shaw_depths:
        # Find which VIC layer this depth falls in
        vic_layer_idx = 0
        for i in range(len(vic_depths) - 1):
            if vic_depths[i] <= zs < vic_depths[i + 1]:
                vic_layer_idx = i
                break
        else:
            vic_layer_idx = len(vic_params['layers']) - 1

        layer = vic_params['layers'][min(vic_layer_idx, len(vic_params['layers']) - 1)]

        nodes.append({
            'zs': zs,
            'ksat_cm_hr': layer['ksat_cm_hr'],
            'psi_e_m': layer['psi_e_m'],
            'theta_s': layer['theta_s'],
            'b_campbell': layer['b_campbell'],
            'bulk_density': layer['bulk_density'],
            'porosity': layer['porosity'],
            'quartz': layer['quartz'],
        })

    return nodes


def write_shaw_soil_section(nodes, iwrc=1, output_path=None):
    """
    Write SHAW soil section (Lines J3) from VIC-derived nodes.

    Column order for IWRC=1 (Campbell):
    DEPTH  SAND  SILT  CLAY  OM    KSAT    BD    THETA   TINIT  BCAP    QUARTZ  BPAR
      m     %     %     %    %   cm/hr  kg/m³  m³/m³    °C      m      0-1     b

    Sand/silt/clay are estimated from Campbell b (inverse Clapp & Hornberger PTF),
    since VIC doesn't store per-layer texture directly.
    QUARTZ is taken directly from VIC soil params (columns 30-32, derived from HWSD).
    KSAT is VIC mm/day ÷ 240 → cm/hr.
    BCAP is negative m (-9999 handled by PTF in parse step).
    """
    lines = []

    for node in nodes:
        b = node['b_campbell']
        # Inverse Clapp & Hornberger PTF: b = 3.10 + 0.157*clay - 0.003*sand
        clay = max(5, min(60, (b - 3.1 + 0.003 * 40) / 0.157))
        sand = max(5, min(80, 100 - 2.5 * clay))
        silt = max(0, 100 - sand - clay)

        rhob = node['bulk_density']
        ksat = node['ksat_cm_hr']
        om = 2.0 if node['zs'] < 0.3 else 0.5   # NE China: ~2% surface OM
        theta = node['theta_s']                   # saturated VWC (used as initial)
        tinit = 0.0                               # initial temperature °C
        bcap = node['psi_e_m']                   # air entry pressure, negative m
        quartz = node['quartz']                   # HWSD-derived fraction, 0-1

        if iwrc == 1:
            line = (
                f" {node['zs']:.3f}  {sand:.0f}. {silt:.0f}. {clay:.0f}. "
                f"{om:.1f}  {ksat:.3f}  {rhob:.0f}.  {theta:.3f}  "
                f"{tinit:.1f}  {bcap:.3f}  {quartz:.3f}  {b:.2f}"
            )
        else:
            line = f"  # IWRC={iwrc} not yet implemented for VIC coupling"

        lines.append(line)

    text = '\n'.join(lines) + '\n'

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(text)
        print(f"SHAW soil section written: {output_path}")
    else:
        print(text)

    return lines


def main():
    parser = argparse.ArgumentParser(description="Convert VIC soil params to SHAW format")
    parser.add_argument("--soil_param", type=str, required=True,
                        help="VIC SOIL_PARAM file")
    parser.add_argument("--cell_id", type=int, default=None, help="Grid cell ID")
    parser.add_argument("--lat", type=float, default=None, help="Grid cell latitude")
    parser.add_argument("--lon", type=float, default=None, help="Grid cell longitude")
    parser.add_argument("--ns", type=int, default=15, help="Number of SHAW soil nodes")
    parser.add_argument("--max_depth", type=float, default=4.0, help="Max depth (m)")
    parser.add_argument("--iwrc", type=int, default=1, help="Water retention: 1=Campbell")
    parser.add_argument("--output", type=str, default=None, help="Output file")
    parser.add_argument("--mollisol_bd", action="store_true",
                        help="Apply Mollisol BD correction for NE China Black Soil "
                             "(HWSD overestimates BD; corrects >1250 kg/m³ by layer scale 0.82/0.88/0.94)")

    args = parser.parse_args()

    if args.cell_id is None and args.lat is None:
        print("ERROR: Must specify either --cell_id or --lat/--lon")
        sys.exit(1)

    # Parse VIC soil params
    vic_params = parse_vic_soil_param(
        args.soil_param, cell_id=args.cell_id, lat=args.lat, lon=args.lon)

    if vic_params is None:
        sys.exit(1)

    print(f"VIC cell: ({vic_params['lat']:.4f}, {vic_params['lon']:.4f})")
    print(f"VIC layers: {[l['depth'] for l in vic_params['layers']]} m")
    ksat_mmd = [round(l['ksat_mm_day'], 1) for l in vic_params['layers']]
    ksat_cmh = [round(l['ksat_cm_hr'], 3) for l in vic_params['layers']]
    qz_list  = [round(l['quartz'], 3)     for l in vic_params['layers']]
    bcap_list = [round(l['psi_e_m'], 4)   for l in vic_params['layers']]
    print(f"VIC Ksat: {ksat_mmd} mm/day  →  {ksat_cmh} cm/hr")
    print(f"VIC quartz: {qz_list}")
    print(f"VIC BCAP: {bcap_list} m")
    bd_raw = [round(l['bd_raw'], 0) for l in vic_params['layers']]
    b_list = [round(l['b_campbell'], 2) for l in vic_params['layers']]
    print(f"VIC BD (raw): {bd_raw} kg/m³")
    print(f"VIC Campbell b: {b_list}")

    if args.mollisol_bd:
        vic_params = apply_mollisol_bd_correction(vic_params)
        bd_corr = [round(l['bulk_density'], 0) for l in vic_params['layers']]
        ts_corr = [round(l['theta_s'], 3) for l in vic_params['layers']]
        print(f"VIC BD (Mollisol-corrected): {bd_corr} kg/m³")
        print(f"VIC theta_s (corrected): {ts_corr}")

    # Distribute to SHAW nodes
    nodes = distribute_to_shaw_nodes(vic_params, args.ns, args.max_depth)

    print(f"\nSHAW nodes: {args.ns}")
    print(f"SHAW depths: {[n['zs'] for n in nodes]} m")

    # Write output
    write_shaw_soil_section(nodes, args.iwrc, args.output)


if __name__ == "__main__":
    main()
