#!/usr/bin/env python3
"""
modify_soil_params.py
=====================
Modify RZWQM2 soil hydraulic parameters for calibration.

Applies multipliers to Ksat, ws (porosity), and fc33 (field capacity) across
ALL horizons in rzwqm.dat.  Automatically recalculates dependent parameters
(fc10, fc15, eps) via Brooks-Corey to maintain physical consistency.

Constraint enforcement:
    wr < fc15 < fc33 < fc10 < ws    (always maintained)
    Ksat > 0, lateral_ksat > 0

Usage:
    python modify_soil_params.py <scenario_dir> <ksat_factor> <ws_factor> <fc33_factor>

    All factors are multipliers (1.0 = no change, 1.2 = +20%, 0.8 = -20%).

    Optional: --backup  to save rzwqm.dat.bak before modifying.
              --restore to restore from rzwqm.dat.bak.

Exit codes: 0=success, 1=input error, 2=processing error
"""
import sys
import os
import json
import shutil
import math

# Add lib to path
LIB_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(LIB_DIR))

# Valid ranges for soil hydraulic parameters (physical limits)
PARAM_RANGES = {
    'ksat':  (0.01, 50.0),    # cm/hr — sand max ~21, but allow headroom
    'ws':    (0.30, 0.60),    # porosity fraction — physical bounds
    'fc33':  (0.03, 0.50),    # field capacity — sand to clay range
    'fc10':  (0.05, 0.55),    # 1/10 bar capacity
    'fc15':  (0.01, 0.40),    # wilting point
}


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def recalc_brooks_corey(ws, wr, bp, psd):
    """Recalculate fc33, fc10, fc15 from Brooks-Corey given ws, wr, bubbling pressure, pore size dist."""
    B1 = (ws - wr) * abs(bp) ** psd
    fc33 = B1 / (333.0 ** psd) + wr
    fc10 = B1 / (100.0 ** psd) + wr
    fc15 = B1 / (15000.0 ** psd) + wr
    return fc33, fc10, fc15


def apply_factors(scenario_dir, ksat_factor, ws_factor, fc33_factor,
                   lateral_ksat=None, drain_spacing=None, field_sat=None):
    """Apply multiplier factors to all soil horizons and write back.

    Core params (multipliers applied to ALL horizons):
        ksat_factor, ws_factor, fc33_factor

    Extended params (absolute values, optional):
        lateral_ksat:   cm/hr — lateral Ksat for all horizons (e.g., 3.0)
        drain_spacing:  cm — tile drain spacing (e.g., 1500)
        field_sat:      fraction — field saturation fraction (e.g., 0.9)

    Returns dict with before/after values for logging.
    """
    from rzwqm_file import RZWQM, soil_hydraulic_properties_each_horizon

    # Find the scenario subdirectory name (last component of path)
    scenario_dir = os.path.abspath(scenario_dir)
    project_path = os.path.dirname(scenario_dir) + '/'
    station = os.path.basename(scenario_dir)

    rz = RZWQM(project_path, station)
    if not rz.check_if_dat_exist():
        return None, f"rzwqm.dat not found in {scenario_dir}"

    props = rz.return_the_soil_properties_class()
    n_horizons = len(props)

    changes = []
    new_props = {}

    for h_num in sorted(props.keys()):
        h = props[h_num]

        # Original values
        orig = {
            'ksat': h.ksat,
            'ws': h.saturated_water_content,
            'wr': h.residual_water_content,
            'fc33': h.fc33,
            'fc10': h.fc10,
            'fc15': h.fc15,
            'bp': h.bubbling_pressure,
            'psd': h.pore_size_dist,
        }

        # Apply multipliers
        new_ksat = clamp(h.ksat * ksat_factor, *PARAM_RANGES['ksat'])
        new_ws = clamp(h.saturated_water_content * ws_factor, *PARAM_RANGES['ws'])
        new_fc33 = clamp(h.fc33 * fc33_factor, *PARAM_RANGES['fc33'])

        wr = h.residual_water_content
        bp = h.bubbling_pressure
        psd = h.pore_size_dist

        # Enforce: fc33 < ws (with margin)
        if new_fc33 >= new_ws - 0.02:
            new_fc33 = new_ws - 0.03

        # Recalculate fc10, fc15 from Brooks-Corey using original bp and psd
        # but with new ws
        new_fc33_bc, new_fc10, new_fc15 = recalc_brooks_corey(new_ws, wr, bp, psd)

        # Scale fc10/fc15 proportionally to how much fc33 changed vs B-C prediction
        if new_fc33_bc > wr + 0.001:
            fc33_ratio = new_fc33 / new_fc33_bc
            new_fc10 = wr + (new_fc10 - wr) * fc33_ratio
            new_fc15 = wr + (new_fc15 - wr) * fc33_ratio
        else:
            # Fallback: use direct Brooks-Corey with existing bp/psd
            new_fc10 = new_fc33 + 0.03
            new_fc15 = wr + (new_fc33 - wr) * 0.5

        # Clamp to valid ranges
        new_fc10 = clamp(new_fc10, *PARAM_RANGES['fc10'])
        new_fc15 = clamp(new_fc15, *PARAM_RANGES['fc15'])

        # Enforce strict ordering: wr < fc15 < fc33 < fc10 < ws
        if new_fc15 <= wr:
            new_fc15 = wr + 0.005
        if new_fc33 <= new_fc15:
            new_fc33 = new_fc15 + 0.01
        if new_fc10 <= new_fc33:
            new_fc10 = new_fc33 + 0.01
        if new_ws <= new_fc10:
            new_ws = new_fc10 + 0.01

        # Lateral Ksat: use explicit value if given, else scale with vertical Ksat
        if lateral_ksat is not None:
            new_lateral_ksat = lateral_ksat
        else:
            new_lateral_ksat = max(0.01, h.lateral_ksat * ksat_factor)

        # eps = 2 + 3*psd (keep psd unchanged)
        new_eps = h.eps

        new_h = soil_hydraulic_properties_each_horizon(
            pore_size_dist=round(psd, 5),
            saturated_water_content=round(new_ws, 6),
            residual_water_content=round(wr, 4),
            bubbling_pressure=round(bp, 4),
            constant_for_oh=0,
            lateral_ksat=round(new_lateral_ksat, 5),
            ksat=round(new_ksat, 5),
            eps=round(new_eps, 5),
            second_intercept_c2=round(h.second_intercept_c2, 2),
            horizon_num=h_num,
            fc33=round(new_fc33, 6),
            fc10=round(new_fc10, 6),
            fc15=round(new_fc15, 6),
        )
        new_props[h_num] = new_h

        changes.append({
            'horizon': h_num,
            'ksat': f"{orig['ksat']:.4f} -> {new_ksat:.4f}",
            'ws': f"{orig['ws']:.4f} -> {new_ws:.4f}",
            'fc33': f"{orig['fc33']:.4f} -> {new_fc33:.4f}",
            'fc10': f"{orig['fc10']:.4f} -> {new_fc10:.4f}",
            'fc15': f"{orig['fc15']:.4f} -> {new_fc15:.4f}",
        })

    # Write back hydraulic properties
    rz.write_new_hydraulic_properties_to_dat(new_props)

    # Modify infiltration line if drain_spacing or field_sat given
    if drain_spacing is not None or field_sat is not None:
        rz2 = RZWQM(project_path, station)
        dat = rz2.dat_data
        for i, line in enumerate(dat):
            parts = line.strip().split()
            if len(parts) == 19:
                try:
                    if float(parts[4]) < 0.01 and float(parts[5]) >= 1000:
                        if drain_spacing is not None:
                            parts[12] = str(round(drain_spacing, 1))
                        if field_sat is not None:
                            parts[3] = str(round(field_sat, 3))
                        dat[i] = '  '.join(parts)
                        break
                except (ValueError, IndexError):
                    continue
        with open(rz2.dat_path, 'w', encoding='ISO-8859-1') as f:
            for line in dat:
                f.write(line + '\n')

    return {
        'n_horizons': n_horizons,
        'factors': {'ksat': ksat_factor, 'ws': ws_factor, 'fc33': fc33_factor},
        'extended': {'lateral_ksat': lateral_ksat, 'drain_spacing': drain_spacing, 'field_sat': field_sat},
        'changes': changes,
    }, None


def main():
    scenario_dir = sys.argv[1] if len(sys.argv) > 1 else ""

    if not scenario_dir:
        print(json.dumps({"status": "INPUT_ERROR",
                          "message": "Usage: modify_soil_params.py <scenario_dir> <ksat_factor> <ws_factor> <fc33_factor>"}))
        sys.exit(1)

    # Handle --backup / --restore flags BEFORE parsing numeric args
    dat_path = None
    for name in ('rzwqm.dat', 'RZWQM.dat'):
        p = os.path.join(scenario_dir, name)
        if os.path.isfile(p):
            dat_path = p
            break

    if '--restore' in sys.argv:
        bak = dat_path + '.cali_bak' if dat_path else None
        if bak and os.path.isfile(bak):
            shutil.copy2(bak, dat_path)
            print(json.dumps({"status": "SUCCESS", "message": f"Restored from {bak}"}))
            sys.exit(0)
        else:
            print(json.dumps({"status": "INPUT_ERROR", "message": "No backup found to restore"}))
            sys.exit(1)

    if '--backup' in sys.argv and dat_path:
        bak = dat_path + '.cali_bak'
        if not os.path.isfile(bak):
            shutil.copy2(dat_path, bak)

    # Parse numeric arguments (skip flags)
    numeric_args = [a for a in sys.argv[2:] if not a.startswith('--')]
    ksat_factor = float(numeric_args[0]) if len(numeric_args) > 0 else 1.0
    ws_factor = float(numeric_args[1]) if len(numeric_args) > 1 else 1.0
    fc33_factor = float(numeric_args[2]) if len(numeric_args) > 2 else 1.0

    # Apply factors
    result, err = apply_factors(scenario_dir, ksat_factor, ws_factor, fc33_factor)
    if err:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    print(json.dumps({"status": "SUCCESS", "result": result}))
    sys.exit(0)


if __name__ == '__main__':
    main()
