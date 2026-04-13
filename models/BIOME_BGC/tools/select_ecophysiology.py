#!/usr/bin/env python3
"""
select_ecophysiology.py
Select and generate BIOME-BGC .epc file based on AVHRR land cover class.

Maps AVHRR class -> PFT -> default .epc parameters from the bundled parameter
library. Optionally applies user overrides to specific parameters.

The .epc file format is STRICTLY line-order-based: each line after the
ECOPHYS keyword corresponds to a specific parameter in the exact order
read by epc_init.c. This tool guarantees correct line ordering.

Usage:
    python select_ecophysiology.py \\
        --avhrr_class 1 --lat 46.8 \\
        --output epc/site_enf.epc

    # Or by PFT code directly:
    python select_ecophysiology.py \\
        --pft ENF --output epc/site_enf.epc

    # With parameter overrides:
    python select_ecophysiology.py \\
        --pft DBF --override sla=35.0 --override leaf_cn=22.0 \\
        --output epc/site_dbf.epc

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import argparse
from pathlib import Path

LIB_DIR = os.path.join(os.path.dirname(__file__), '..', 'lib')
sys.path.insert(0, LIB_DIR)
from bgc_utils import EPC_DEFAULTS, avhrr_to_pft


def generate_epc_content(pft_code: str, overrides: dict = None) -> str:
    """
    Generate .epc file content for the given PFT.

    Parameters
    ----------
    pft_code : str
        PFT code: ENF, EBF, DNF, DBF, SHRUB, C3GRASS, C4GRASS
    overrides : dict
        Optional parameter overrides {param_name: value}

    Returns
    -------
    str
        Complete .epc file content.
    """
    if pft_code not in EPC_DEFAULTS:
        raise ValueError(f"Unknown PFT: {pft_code}. "
                         f"Valid: {list(EPC_DEFAULTS.keys())}")

    p = dict(EPC_DEFAULTS[pft_code])
    if overrides:
        for k, v in overrides.items():
            if k in p:
                p[k] = v
            else:
                raise ValueError(f"Unknown EPC parameter: {k}. "
                                 f"Valid: {[k for k in p if k != 'name']}")

    # Validate litter fractions sum to 1.0
    for prefix, label in [("ll_", "leaf litter"), ("fr_", "fine root")]:
        lab = p[f"{prefix}labile"]
        cel = p[f"{prefix}cellulose"]
        lig = p[f"{prefix}lignin"]
        total = lab + cel + lig
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"{label} fractions sum to {total}, must be 1.0")

    dw_total = p["dw_cellulose"] + p["dw_lignin"]
    if abs(dw_total - 1.0) > 0.01:
        raise ValueError(f"Dead wood fractions sum to {dw_total}, must be 1.0")

    # Build the .epc file in exact line order matching epc_init.c
    # Mark lines with * where value is not used (non-woody / evergreen etc.)
    w = p["woody"]
    eg = p["evergreen"]
    phen = p["phenology_flag"]

    lines = []
    lines.append(f"ECOPHYS       {pft_code} ({p['name']})")
    lines.append(f"{p['woody']}             (flag)    1 = WOODY             0 = NON-WOODY")
    lines.append(f"{p['evergreen']}             (flag)    1 = EVERGREEN         0 = DECIDUOUS")
    lines.append(f"{p['c3_flag']}             (flag)    1 = C3 PSN            0 = C4 PSN")
    lines.append(f"{p['phenology_flag']}             (flag)    1 = MODEL PHENOLOGY   0 = USER-SPECIFIED PHENOLOGY")

    star1 = "*" if phen == 1 else ""
    lines.append(f"{p['onday']}            {star1}(yday)    yearday to start new growth  (when phenology flag = 0)")
    lines.append(f"{p['offday']}            {star1}(yday)    yearday to end litterfall  (when phenology flag = 0)")

    star2 = "*" if eg == 1 else ""
    lines.append(f"{p['transfer_pdays']}          {star2}(prop.)   transfer growth period as fraction of growing season")
    lines.append(f"{p['litfall_pdays']}          {star2}(prop.)   litterfall as fraction of growing season")
    lines.append(f"{p['leaf_turnover']}          (1/yr)    annual leaf and fine root turnover fraction")

    star3 = "*" if w == 0 else ""
    lines.append(f"{p['livewood_turnover']}          {star3}(1/yr)    annual live wood turnover fraction")
    lines.append(f"{p['mortality']}         (1/yr)    annual whole-plant mortality fraction")
    lines.append(f"{p['fire_mortality']}         (1/yr)    annual fire mortality fraction")
    lines.append(f"{p['froot_leaf']}           (ratio)   (ALLOCATION) new fine root C : new leaf C")

    star4 = "*" if w == 0 else ""
    lines.append(f"{p['stem_leaf']}          {star4}(ratio)   (ALLOCATION) new stem C : new leaf C")
    lines.append(f"{p['livewood_wood']}          {star4}(ratio)   (ALLOCATION) new live wood C : new total wood C")
    lines.append(f"{p['croot_stem']}          {star4}(ratio)   (ALLOCATION) new croot C : new stem C")
    lines.append(f"{p['current_growth_prop']}           (prop.)   (ALLOCATION) current growth proportion")
    lines.append(f"{p['leaf_cn']}          (kgC/kgN) C:N of leaves")
    lines.append(f"{p['leaflitter_cn']}          (kgC/kgN) C:N of leaf litter, after retranslocation")
    lines.append(f"{p['froot_cn']}          (kgC/kgN) C:N of fine roots")

    star5 = "*" if w == 0 else ""
    lines.append(f"{p['livewood_cn']}          {star5}(kgC/kgN) C:N of live wood")
    lines.append(f"{p['deadwood_cn']}         {star5}(kgC/kgN) C:N of dead wood")
    lines.append(f"{p['ll_labile']}          (DIM)     leaf litter labile proportion")
    lines.append(f"{p['ll_cellulose']}          (DIM)     leaf litter cellulose proportion")
    lines.append(f"{p['ll_lignin']}          (DIM)     leaf litter lignin proportion")
    lines.append(f"{p['fr_labile']}          (DIM)     fine root labile proportion")
    lines.append(f"{p['fr_cellulose']}          (DIM)     fine root cellulose proportion")
    lines.append(f"{p['fr_lignin']}          (DIM)     fine root lignin proportion")

    star6 = "*" if w == 0 else ""
    lines.append(f"{p['dw_cellulose']}          {star6}(DIM)     dead wood cellulose proportion")
    lines.append(f"{p['dw_lignin']}          {star6}(DIM)     dead wood lignin proportion")
    lines.append(f"{p['int_coef']}         (1/LAI/d) canopy water interception coefficient")
    lines.append(f"{p['ext_coef']}           (DIM)     canopy light extinction coefficient")
    lines.append(f"{p['lai_ratio']}           (DIM)     all-sided to projected leaf area ratio")
    lines.append(f"{p['sla']}          (m2/kgC)  canopy average specific leaf area (projected area basis)")
    lines.append(f"{p['sla_ratio']}           (DIM)     ratio of shaded SLA:sunlit SLA")
    lines.append(f"{p['flnr']}          (DIM)     fraction of leaf N in Rubisco")
    lines.append(f"{p['gl_smax']}         (m/s)     maximum stomatal conductance (projected area basis)")
    lines.append(f"{p['gl_c']}       (m/s)     cuticular conductance (projected area basis)")
    lines.append(f"{p['gl_bl']}          (m/s)     boundary layer conductance (projected area basis)")
    lines.append(f"{p['psi_open']}          (MPa)     leaf water potential: start of conductance reduction")
    lines.append(f"{p['psi_close']}          (MPa)     leaf water potential: complete conductance reduction")
    lines.append(f"{p['vpd_open']}        (Pa)      vapor pressure deficit: start of conductance reduction")
    lines.append(f"{p['vpd_close']}       (Pa)      vapor pressure deficit: complete conductance reduction")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Select and generate BIOME-BGC .epc file")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--avhrr_class", type=int,
                       help="AVHRR land cover class (1-13)")
    group.add_argument("--pft", type=str,
                       help="PFT code: ENF, EBF, DNF, DBF, SHRUB, C3GRASS, C4GRASS")
    parser.add_argument("--lat", type=float, default=45.0,
                        help="Latitude (for grassland C3/C4 decision)")
    parser.add_argument("--override", action="append", default=[],
                        help="Parameter override in key=value format")
    parser.add_argument("--output", required=True, help="Output .epc file path")

    args = parser.parse_args()

    # Determine PFT
    if args.avhrr_class is not None:
        pft_code = avhrr_to_pft(args.avhrr_class, args.lat)
        if pft_code is None:
            result = {"status": "error", "stage": "input_validation",
                      "message": f"AVHRR class {args.avhrr_class} is not a "
                                 "natural vegetation type (cropland/bare/urban). "
                                 "Use LDNDC or DSSAT for cropland."}
            print(json.dumps(result, indent=2))
            sys.exit(1)
    else:
        pft_code = args.pft.upper()

    # Parse overrides
    overrides = {}
    for ov in args.override:
        if "=" not in ov:
            result = {"status": "error", "stage": "input_validation",
                      "message": f"Override must be key=value, got: {ov}"}
            print(json.dumps(result, indent=2))
            sys.exit(1)
        k, v = ov.split("=", 1)
        try:
            overrides[k] = float(v)
        except ValueError:
            overrides[k] = v

    # Generate
    try:
        content = generate_epc_content(pft_code, overrides if overrides else None)
    except ValueError as e:
        result = {"status": "error", "stage": "generation",
                  "message": str(e)}
        print(json.dumps(result, indent=2))
        sys.exit(2)

    # Write
    try:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content)
    except Exception as e:
        result = {"status": "error", "stage": "output",
                  "message": str(e)}
        print(json.dumps(result, indent=2))
        sys.exit(3)

    p = EPC_DEFAULTS[pft_code]
    result = {
        "status": "success",
        "output_file": str(out_path),
        "pft_code": pft_code,
        "pft_name": p["name"],
        "avhrr_class": args.avhrr_class,
        "key_params": {
            "woody": p["woody"],
            "evergreen": p["evergreen"],
            "c3_flag": p["c3_flag"],
            "sla": overrides.get("sla", p["sla"]),
            "leaf_cn": overrides.get("leaf_cn", p["leaf_cn"]),
            "gl_smax": overrides.get("gl_smax", p["gl_smax"]),
        },
        "overrides_applied": len(overrides),
    }
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
