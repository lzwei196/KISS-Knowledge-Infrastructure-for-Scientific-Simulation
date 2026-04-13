#!/usr/bin/env python3
"""
HEC-HMS Core Simulation Engine (Python implementation).

Implements the core HEC-HMS algorithms:
  1. SCS Curve Number (loss/infiltration)
  2. SCS Unit Hydrograph (direct runoff transform)
  3. Linear Reservoir (baseflow)
  4. Muskingum (channel routing, optional)

This is a Python implementation of the public-domain USDA/USACE algorithms
used internally by HEC-HMS. It produces equivalent results for lumped basins.

Usage:
  python3 run_hec_hms.py \
    --forcing_csv ./forcing_out/basin_avg_forcing.csv \
    --soil_params ./soil_params.json \
    --basin_area_km2 121330 \
    --start_date 1980-01-01 --end_date 1990-12-31 \
    --output_csv ./sim_discharge.csv
"""

import argparse
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# SCS Dimensionless Unit Hydrograph
# ---------------------------------------------------------------------------
# t/Tp and Q/Qp pairs from USDA NEH Chapter 16
SCS_UH_T_RATIO = np.array([
    0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0,
    1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0,
    2.2, 2.4, 2.6, 2.8, 3.0, 3.5, 4.0, 4.5, 5.0
])
SCS_UH_Q_RATIO = np.array([
    0.000, 0.030, 0.100, 0.190, 0.310, 0.470, 0.660, 0.820, 0.930, 0.990, 1.000,
    0.990, 0.930, 0.860, 0.780, 0.680, 0.560, 0.460, 0.390, 0.330, 0.280,
    0.207, 0.147, 0.107, 0.077, 0.055, 0.025, 0.011, 0.005, 0.000
])


# ---------------------------------------------------------------------------
# Validate inputs
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check all inputs are valid."""
    errors = []
    if not os.path.isfile(args.forcing_csv):
        errors.append(f"Forcing CSV not found: {args.forcing_csv}")
    if args.soil_params and not os.path.isfile(args.soil_params):
        errors.append(f"Soil params file not found: {args.soil_params}")
    if args.basin_area_km2 <= 0:
        errors.append(f"Basin area must be positive: {args.basin_area_km2}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print("[validate_inputs] All inputs valid.")


# ---------------------------------------------------------------------------
# SCS Curve Number Loss Method
# ---------------------------------------------------------------------------
def scs_cn_loss(precip_mm, cn, ia_ratio=0.05):
    """
    SCS Curve Number method for computing runoff depth.

    Parameters:
        precip_mm: array of daily precipitation (mm)
        cn: Curve Number (30-100)
        ia_ratio: Initial abstraction ratio (0.05 recommended, 0.2 classic)

    Returns:
        runoff_mm: array of direct runoff depth (mm)
        loss_mm: array of infiltration loss (mm)

    Algorithm:
        S = 25400/CN - 254            (max retention, mm)
        Ia = ia_ratio * S             (initial abstraction, mm)
        if P <= Ia: Q = 0
        else:       Q = (P - Ia)² / (P - Ia + S)
    """
    # Validate CN range (dt_103)
    if cn < 30 or cn > 100:
        print(f"  WARNING: CN={cn} outside valid range [30, 100]")
        cn = np.clip(cn, 30, 100)

    S = 25400.0 / cn - 254.0  # Maximum retention (mm)
    Ia = ia_ratio * S          # Initial abstraction (mm)

    print(f"[scs_cn_loss] CN={cn:.1f}, S={S:.1f} mm, Ia={Ia:.1f} mm (ratio={ia_ratio})")

    runoff_mm = np.zeros_like(precip_mm, dtype=float)
    for i in range(len(precip_mm)):
        P = precip_mm[i]
        if P > Ia:
            runoff_mm[i] = (P - Ia) ** 2 / (P - Ia + S)
        else:
            runoff_mm[i] = 0.0

    loss_mm = precip_mm - runoff_mm

    # Statistics
    total_precip = np.sum(precip_mm)
    total_runoff = np.sum(runoff_mm)
    runoff_coeff = total_runoff / total_precip if total_precip > 0 else 0
    print(f"  Total precip: {total_precip:.0f} mm, Total runoff: {total_runoff:.0f} mm, "
          f"Runoff coefficient: {runoff_coeff:.3f}")

    return runoff_mm, loss_mm


# ---------------------------------------------------------------------------
# SCS Unit Hydrograph Transform
# ---------------------------------------------------------------------------
def scs_unit_hydrograph(runoff_mm, basin_area_km2, tp_hr, dt_hr=24.0):
    """
    Apply SCS Unit Hydrograph to convert excess precipitation to direct runoff.

    Parameters:
        runoff_mm: array of excess precipitation depth per timestep (mm)
        basin_area_km2: basin area (km²)
        tp_hr: time to peak (hours)
        dt_hr: timestep (hours), default 24 for daily

    Returns:
        q_direct_m3s: array of direct runoff discharge (m³/s)
    """
    # Check D vs Tp (dt_105)
    D = dt_hr
    if D > 0.29 * tp_hr:
        print(f"  WARNING: Timestep D={D:.1f}hr > 0.29*Tp={0.29*tp_hr:.1f}hr — "
              f"UH peak may be poorly resolved (dt_105)")

    # Peak discharge per unit excess rain (m³/s per mm)
    # Qp = 2.08 * A / Tp (A in km², Tp in hours)
    Qp = 2.08 * basin_area_km2 / tp_hr
    print(f"[scs_uh] Tp={tp_hr:.1f} hr, Qp={Qp:.1f} m³/s per mm, dt={dt_hr:.1f} hr")

    # Build discrete UH ordinates at model timestep
    t_uh = SCS_UH_T_RATIO * tp_hr  # Time in hours
    q_uh = SCS_UH_Q_RATIO * Qp     # Discharge in m³/s per mm

    # Resample UH to model timestep
    n_uh = int(np.ceil(t_uh[-1] / dt_hr)) + 1
    t_discrete = np.arange(n_uh) * dt_hr
    q_discrete = np.interp(t_discrete, t_uh, q_uh, right=0.0)

    # Normalize to preserve volume: sum(q_discrete * dt) should equal 1 mm over basin
    # Volume per mm = A * 1000 m³ (1 mm on 1 km² = 1000 m³)
    vol_per_mm = basin_area_km2 * 1000.0  # m³
    vol_uh = np.sum(q_discrete) * dt_hr * 3600.0  # m³
    if vol_uh > 0:
        q_discrete *= vol_per_mm / vol_uh

    # Convolve: direct runoff = sum of shifted UH for each rainfall pulse
    n_total = len(runoff_mm) + len(q_discrete) - 1
    q_direct = np.convolve(runoff_mm, q_discrete)[:len(runoff_mm)]

    print(f"  UH ordinates: {len(q_discrete)}, Peak direct Q: {np.max(q_direct):.1f} m³/s")
    return q_direct


# ---------------------------------------------------------------------------
# Linear Reservoir Baseflow
# ---------------------------------------------------------------------------
def linear_reservoir_baseflow(precip_mm, runoff_mm, basin_area_km2,
                               k_recession=0.95, q_init_m3s=50.0,
                               recharge_fraction=0.05):
    """
    Linear reservoir baseflow model.

    Parameters:
        precip_mm: daily precipitation (mm)
        runoff_mm: daily direct runoff (mm)
        basin_area_km2: basin area (km²)
        k_recession: recession constant (0 < k < 1), dimensionless
        q_init_m3s: initial baseflow (m³/s)
        recharge_fraction: fraction of infiltration that recharges groundwater

    Returns:
        q_base_m3s: array of baseflow discharge (m³/s)

    Algorithm:
        loss_mm = precip_mm - runoff_mm (infiltration)
        recharge_mm = recharge_fraction * loss_mm
        recharge_m3s = recharge_mm * area_km2 * 1000 / 86400
        q_base[t] = k * q_base[t-1] + (1-k) * recharge_m3s[t]
    """
    # Validate recession constant (dt_107)
    if k_recession <= 0 or k_recession >= 1:
        print(f"  WARNING: Recession constant k={k_recession} outside (0,1) — clamping")
        k_recession = np.clip(k_recession, 0.01, 0.999)

    loss_mm = precip_mm - runoff_mm
    loss_mm = np.maximum(loss_mm, 0.0)

    # Recharge to groundwater
    recharge_mm = recharge_fraction * loss_mm
    # Convert mm/day → m³/s: Q = mm * km² * 1000 / 86400 (dt_114)
    recharge_m3s = recharge_mm * basin_area_km2 * 1000.0 / 86400.0

    q_base = np.zeros(len(precip_mm))
    q_base[0] = q_init_m3s

    for t in range(1, len(precip_mm)):
        q_base[t] = k_recession * q_base[t - 1] + (1.0 - k_recession) * recharge_m3s[t]
        q_base[t] = max(q_base[t], 0.0)

    print(f"[baseflow] k={k_recession:.3f}, q_init={q_init_m3s:.1f} m³/s, "
          f"mean baseflow={np.mean(q_base):.1f} m³/s")
    return q_base


# ---------------------------------------------------------------------------
# Muskingum Channel Routing (optional)
# ---------------------------------------------------------------------------
def muskingum_route(q_inflow, k_hr, x, dt_hr=24.0):
    """
    Muskingum channel routing.

    Parameters:
        q_inflow: inflow hydrograph (m³/s)
        k_hr: travel time parameter K (hours)
        x: weighting factor X (0-0.5)
        dt_hr: timestep (hours)

    Returns:
        q_outflow: routed outflow (m³/s)
    """
    dt = dt_hr * 3600.0  # Convert to seconds
    K = k_hr * 3600.0

    # Check Courant condition (dt_106)
    if x > 0.5:
        print(f"  WARNING: Muskingum X={x} > 0.5 — clamping to 0.5 (dt_106)")
        x = 0.5

    denom = 2.0 * K * (1.0 - x) + dt
    C1 = (dt - 2.0 * K * x) / denom
    C2 = (dt + 2.0 * K * x) / denom
    C3 = (2.0 * K * (1.0 - x) - dt) / denom

    # Verify coefficients
    if C1 < 0 or C2 < 0 or C3 < 0:
        print(f"  WARNING: Negative Muskingum coefficients C1={C1:.3f}, C2={C2:.3f}, C3={C3:.3f}")

    q_out = np.zeros_like(q_inflow)
    q_out[0] = q_inflow[0]

    for t in range(1, len(q_inflow)):
        q_out[t] = C1 * q_inflow[t] + C2 * q_inflow[t - 1] + C3 * q_out[t - 1]
        q_out[t] = max(q_out[t], 0.0)

    print(f"[muskingum] K={k_hr:.1f}hr, X={x:.2f}, C1={C1:.3f}, C2={C2:.3f}, C3={C3:.3f}")
    return q_out


# ---------------------------------------------------------------------------
# Estimate time to peak from basin area
# ---------------------------------------------------------------------------
def estimate_tp_from_area(area_km2, cn=75):
    """
    Estimate SCS time to peak from basin area using empirical relationship.

    For large basins, Tp scales with sqrt(area):
    Tc ≈ 0.5 * sqrt(area_km2) hours (rough estimate)
    Tp = 0.6 * Tc + D/2

    For Bengbu (121,330 km²), this gives Tc ≈ 174 hr, Tp ≈ 116 hr (~5 days)
    """
    # Kirpich-like estimate for large basins
    tc_hr = 0.5 * np.sqrt(area_km2)
    D = 24.0  # Daily timestep
    tp_hr = 0.6 * tc_hr + D / 2.0

    # Clamp to reasonable range
    tp_hr = max(tp_hr, D)  # At least 1 timestep
    tp_hr = min(tp_hr, 720.0)  # Max 30 days

    print(f"[estimate_tp] Area={area_km2:.0f} km², Tc≈{tc_hr:.1f} hr, Tp≈{tp_hr:.1f} hr")
    return tp_hr


# ---------------------------------------------------------------------------
# Process (main simulation)
# ---------------------------------------------------------------------------
def process(args):
    """Run HEC-HMS simulation."""
    print("=" * 60)
    print("HEC-HMS Simulation Engine (SCS-CN + SCS UH + Linear Reservoir)")
    print("=" * 60)

    # 1. Read forcing
    print("\n[read_forcing] Reading forcing CSV...")
    df = pd.read_csv(args.forcing_csv, index_col=0, parse_dates=True)
    print(f"  Period: {df.index[0]} to {df.index[-1]}, {len(df)} days")

    # Filter to requested period
    if args.start_date:
        df = df[df.index >= args.start_date]
    if args.end_date:
        df = df[df.index <= args.end_date]
    print(f"  After filtering: {len(df)} days")

    precip_mm = df["precip_mm"].values.copy()
    precip_mm = np.maximum(precip_mm, 0.0)

    # 2. Read soil parameters
    cn = args.cn if args.cn else 75.0
    ia_ratio = args.ia_ratio if args.ia_ratio else 0.05

    if args.soil_params and os.path.isfile(args.soil_params):
        print("\n[read_params] Reading soil parameters...")
        with open(args.soil_params) as f:
            soil = json.load(f)
        cn = soil.get("curve_number", cn)
        print(f"  CN from soil file: {cn}")

    # 3. SCS-CN Loss
    print("\n[loss] Computing SCS-CN losses...")
    runoff_mm, loss_mm = scs_cn_loss(precip_mm, cn, ia_ratio)

    # 4. SCS Unit Hydrograph
    print("\n[transform] Applying SCS Unit Hydrograph...")
    tp_hr = args.tp_hr if args.tp_hr else estimate_tp_from_area(args.basin_area_km2, cn)
    q_direct = scs_unit_hydrograph(runoff_mm, args.basin_area_km2, tp_hr, dt_hr=24.0)

    # 5. Baseflow
    print("\n[baseflow] Computing linear reservoir baseflow...")
    k_base = args.k_recession if args.k_recession else 0.95
    q_init = args.q_base_init if args.q_base_init else 50.0
    recharge_frac = args.recharge_fraction if args.recharge_fraction else 0.05
    q_base = linear_reservoir_baseflow(
        precip_mm, runoff_mm, args.basin_area_km2,
        k_recession=k_base, q_init_m3s=q_init,
        recharge_fraction=recharge_frac
    )

    # 6. Total discharge
    q_total = q_direct + q_base
    q_total = np.maximum(q_total, 0.0)

    print(f"\n[total] Mean Q: {np.mean(q_total):.1f} m³/s, "
          f"Peak Q: {np.max(q_total):.1f} m³/s, "
          f"Min Q: {np.min(q_total):.1f} m³/s")

    # 7. Build output DataFrame
    out_df = pd.DataFrame({
        "date": df.index,
        "precip_mm": precip_mm,
        "runoff_mm": runoff_mm,
        "loss_mm": loss_mm,
        "q_direct_m3s": q_direct,
        "q_base_m3s": q_base,
        "q_total_m3s": q_total,
    })
    out_df.set_index("date", inplace=True)

    # 8. Write output
    os.makedirs(os.path.dirname(args.output_csv) or ".", exist_ok=True)
    out_df.to_csv(args.output_csv)
    print(f"\n[write] Output: {args.output_csv}")
    print(f"  Columns: {list(out_df.columns)}")

    return out_df


# ---------------------------------------------------------------------------
# Validate outputs
# ---------------------------------------------------------------------------
def validate_outputs(df, basin_area_km2):
    """Check output for physical consistency."""
    warnings_list = []

    q_mean = df["q_total_m3s"].mean()
    q_max = df["q_total_m3s"].max()

    # Specific discharge check
    q_specific = q_mean / basin_area_km2 * 86400 / 1000 * 365.25  # mm/yr
    print(f"\n[validate] Mean Q: {q_mean:.1f} m³/s → {q_specific:.0f} mm/yr specific discharge")

    if q_specific < 10:
        warnings_list.append(f"Specific discharge very low: {q_specific:.0f} mm/yr (expect 100-500)")
    if q_specific > 2000:
        warnings_list.append(f"Specific discharge very high: {q_specific:.0f} mm/yr — check units!")

    if df["q_total_m3s"].min() < 0:
        warnings_list.append("Negative discharge detected!")

    for w in warnings_list:
        print(f"  WARNING: {w}")

    return warnings_list


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Run HEC-HMS SCS-CN simulation")
    parser.add_argument("--forcing_csv", required=True, help="Forcing CSV file")
    parser.add_argument("--soil_params", default=None, help="Soil parameters JSON")
    parser.add_argument("--basin_area_km2", type=float, required=True, help="Basin area (km²)")
    parser.add_argument("--start_date", default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--cn", type=float, default=None, help="Override Curve Number")
    parser.add_argument("--ia_ratio", type=float, default=0.05, help="Initial abstraction ratio")
    parser.add_argument("--tp_hr", type=float, default=None, help="Time to peak (hours)")
    parser.add_argument("--k_recession", type=float, default=0.95, help="Baseflow recession constant")
    parser.add_argument("--q_base_init", type=float, default=50.0, help="Initial baseflow (m³/s)")
    parser.add_argument("--recharge_fraction", type=float, default=0.05, help="Recharge fraction")
    parser.add_argument("--output_csv", required=True, help="Output CSV file")
    args = parser.parse_args()

    validate_inputs(args)
    df = process(args)
    validate_outputs(df, args.basin_area_km2)


if __name__ == "__main__":
    main()
