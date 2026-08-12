#!/usr/bin/env python3
"""
init_carbon_pools.py — RHESSys worldfile carbon pool initializer.

Implements the lairead allometric equations (RHESSysWorkflows/lairead, Nairb 2013)
without requiring GRASS GIS. Reads a zero-carbon worldfile and writes a new worldfile
with vegetation carbon stores computed from LAI and veg-def parameters.

CRITICAL: Zero carbon pools → LAI=0, trans=0 for ALL runs with -g flag.
This tool must be run BEFORE the main simulation. See Stage 3 in 03_soil_vegetation_params.md.

Allometric equations (from util/GRASS/lairead/change_world.c):
  leafc           = LAI / proj_sla
  frootc          = leafc / alloc_frootc_leafc    (lr in lairead allom table)
  leafc_transfer  = max_lai / proj_sla            (full leaf expansion budget)
  leafc_store     = leafc                         (current-season storage)
  leafn_*         = leafc_* / leaf_cn
  frootn          = frootc / froot_cn

For TREE type only: live_stemc, dead_stemc, etc. are also set (ls>0).
For GRASS/C4GRASS: all stem/wood pools remain zero (ls=0).

Start-month semantics (critical for DECIDUOUS runs):
  - If start_month is IN growing season (day_leafon ≤ doy ≤ day_leafoff):
      Set cs.leafc = leafc (active leaves present)
  - If start_month is OUTSIDE growing season (dormant, e.g. January):
      Set cs.leafc = 0, cs.leafc_transfer = max_lai/proj_sla (ready for spring)
      This mirrors what lairead + 3-day spinup produces for a Jan 1 start.

Usage:
    python init_carbon_pools.py \\
        --world worldfiles/basin_v1.world \\
        --output worldfiles/basin_v1_init.world \\
        --lai 3.5 \\
        --proj-sla 20.0 \\
        --max-lai 4.0 \\
        --alloc-frootc-leafc 1.0 \\
        --leaf-cn 35.0 \\
        --froot-cn 60.0 \\
        --veg-type GRASS \\
        --phenology-type DECIDUOUS \\
        --day-leafon 91 \\
        --day-leafoff 270 \\
        --start-month 1

Reference: https://github.com/selimnairb/RHESSysWorkflows
"""

import argparse
import re
import sys


def day_of_year(month: int) -> int:
    """Approximate day-of-year for the first of each month."""
    days = [0, 1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    return days[month]


def in_growing_season(start_month: int, day_leafon: int, day_leafoff: int) -> bool:
    doy = day_of_year(start_month)
    if day_leafon <= day_leafoff:
        return day_leafon <= doy <= day_leafoff
    else:
        return doy >= day_leafon or doy <= day_leafoff


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--world', required=True, help='Input zero-carbon worldfile')
    p.add_argument('--output', required=True, help='Output worldfile with initialized carbon')
    p.add_argument('--lai', type=float, required=True,
                   help='Representative LAI (m²/m²) — use worldfile lai value or MODIS mean')
    p.add_argument('--proj-sla', type=float, required=True,
                   help='epc.proj_sla from veg def (m²/kg C)')
    p.add_argument('--max-lai', type=float, required=True,
                   help='epc.max_lai from veg def (m²/m²)')
    p.add_argument('--alloc-frootc-leafc', type=float, required=True,
                   help='epc.alloc_frootc_leafc from veg def (fine root : leaf C ratio)')
    p.add_argument('--leaf-cn', type=float, required=True,
                   help='epc.leaf_cn from veg def')
    p.add_argument('--froot-cn', type=float, required=True,
                   help='epc.froot_cn from veg def')
    p.add_argument('--veg-type', required=True, choices=['TREE', 'GRASS', 'C4GRASS', 'NON_VEG'],
                   help='epc.veg.type from veg def')
    p.add_argument('--phenology-type', default='DECIDUOUS', choices=['DECIDUOUS', 'EVERGREEN'],
                   help='epc.phenology.type from veg def')
    p.add_argument('--day-leafon', type=int, default=91,
                   help='epc.day_leafon from veg def (day of year, 1-365)')
    p.add_argument('--day-leafoff', type=int, default=270,
                   help='epc.day_leafoff from veg def (day of year, 1-365)')
    p.add_argument('--start-month', type=int, default=1,
                   help='Simulation start month (1=Jan ... 12=Dec)')
    args = p.parse_args()

    # --- Compute carbon pools ---
    sla = args.proj_sla
    if sla < 0.01:
        sla = 0.01  # lairead guard

    leafc     = args.lai / sla                         # current LAI → C
    frootc    = leafc / args.alloc_frootc_leafc        # fine root C
    leafc_max = args.max_lai / sla                     # full expansion budget

    if args.phenology_type == 'EVERGREEN' or args.veg_type == 'NON_VEG':
        # Leaves present year-round or no veg
        active_leafc   = leafc
        leafc_transfer = 0.0
        leafc_store    = leafc
    elif in_growing_season(args.start_month, args.day_leafon, args.day_leafoff):
        # Start during growing season: active leaves present
        active_leafc   = leafc
        leafc_transfer = 0.0
        leafc_store    = leafc
    else:
        # Start outside growing season (dormant): no active leaves
        # leafc_transfer = full expansion budget (consumed during leaf-out)
        # leafc_store    = current-year allocation (for subsequent year's allocation)
        active_leafc   = 0.0
        leafc_transfer = leafc_max
        leafc_store    = leafc

    leafn         = active_leafc / args.leaf_cn
    leafn_store   = leafc_store  / args.leaf_cn
    leafn_transfer = leafc_transfer / args.leaf_cn
    frootn        = frootc       / args.froot_cn

    print(f"Carbon pool values (kg C or N / m²):")
    print(f"  cs.leafc           = {active_leafc:.6f}  (active leaves)")
    print(f"  cs.leafc_store     = {leafc_store:.6f}  (storage)")
    print(f"  cs.leafc_transfer  = {leafc_transfer:.6f}  (ready for leaf-out)")
    print(f"  cs.frootc          = {frootc:.6f}")
    print(f"  ns.leafn           = {leafn:.6f}")
    print(f"  ns.leafn_store     = {leafn_store:.6f}")
    print(f"  ns.leafn_transfer  = {leafn_transfer:.6f}")
    print(f"  ns.frootn          = {frootn:.6f}")
    print()

    with open(args.world, 'r') as f:
        content = f.read()

    # Count existing stratum blocks for validation
    n_strata = content.count('cs.leafc\n')
    print(f"Found {n_strata} stratum blocks in worldfile.")

    def replace_val(text, varname, new_val):
        """Replace '0.00000000   <varname>' with formatted new value."""
        pattern = r'(\s+)0\.00000000(\s+' + re.escape(varname) + r')'
        repl = rf'\g<1>{new_val:.8f}\g<2>'
        return re.sub(pattern, repl, text)

    def insert_after(text, anchor_varname, new_lines):
        """Insert new_lines text immediately after all lines matching anchor_varname."""
        pattern = r'([ \t]+0\.00000000[ \t]+' + re.escape(anchor_varname) + r'\n)'
        repl = r'\1' + new_lines
        return re.sub(pattern, repl, text)

    # 1. Set active leafc and leafn
    content = replace_val(content, 'cs.leafc', active_leafc)
    content = replace_val(content, 'ns.leafn', leafn)

    # 2. After cs.dead_leafc, insert cs.leafc_store + ns.leafn_store + cs.leafc_transfer + ns.leafn_transfer
    insert_block = (
        f'             {leafc_store:.8f}                          cs.leafc_store\n'
        f'             {leafn_store:.8f}                          ns.leafn_store\n'
        f'             {leafc_transfer:.8f}                          cs.leafc_transfer\n'
        f'             {leafn_transfer:.8f}                          ns.leafn_transfer\n'
    )
    content = insert_after(content, 'cs.dead_leafc', insert_block)

    # 3. Set frootc and frootn
    content = replace_val(content, 'cs.frootc', frootc)
    content = replace_val(content, 'ns.frootn', frootn)

    with open(args.output, 'w') as f:
        f.write(content)

    # Validate
    n_out = content.count('cs.leafc_store')
    print(f"Wrote {n_out} cs.leafc_store entries (expected {n_strata}).")
    if n_out != n_strata:
        print("WARNING: count mismatch — check worldfile structure.", file=sys.stderr)
        sys.exit(1)
    print(f"Output: {args.output}")


if __name__ == '__main__':
    main()
