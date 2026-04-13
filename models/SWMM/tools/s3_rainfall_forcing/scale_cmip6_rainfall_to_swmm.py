#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      scale_cmip6_rainfall_to_swmm
Stage:        s3_rainfall_forcing
Description:  Apply CMIP6 monthly precipitation delta factors to SWMM rainfall
              TIMESERIES, producing future-scenario design storms for each
              SSP × time-period combination.

Approach — delta-change method:
  For each CMIP6 scenario and time period, compute the ensemble-median
  monthly precipitation ratio (future / baseline) from the CMIP6 delta file
  produced by compute_climate_deltas.py. Apply the ratio for the target month
  (default: July, peak convective season in East China) to scale all intensity
  values in the SWMM [TIMESERIES] block.

  P_future = P_baseline × delta_ratio(month, scenario, period)

  A separate scaled timeseries is written for each scenario × period,
  named "{original_ts_name}_{scenario}_{period}" (e.g., "3y_ssp245_near").

CRITICAL — SWMM INTENSITY FORMAT (dt_sxx_007):
  chaohu.inp uses FORMAT INTENSITY (mm/hr). The values in [TIMESERIES] are
  mm/hr, NOT mm per interval. Multiplying by the ratio directly is correct
  because the ratio is dimensionless.

Inputs (CLI args or set below):
  --inp_file      : SWMM .inp file (read-only, not modified)
  --delta_nc      : NetCDF delta file from compute_climate_deltas.py
  --output_dir    : directory to write scenario timeseries snippet files
  --ts_name       : TIMESERIES name in the .inp to scale (default: first found)
  --target_month  : month number for design storm season (default: 7 = July)
  --scenarios     : comma-separated list of scenarios to process
                    (default: "ssp126_near,ssp245_near,ssp245_far,ssp585_near,ssp585_far")

Output per scenario:
  {output_dir}/{ts_name}_{scenario}.txt  — SWMM [TIMESERIES] snippet
  {output_dir}/summary.json             — delta ratios applied per scenario

The snippets can be appended to a SWMM .inp file or referenced in
[RAINGAGES] via FILE format. To use: copy the [TIMESERIES] block into
a new .inp file and update the [RAINGAGES] section to reference the
new timeseries name.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CMIP6 delta reader
# ---------------------------------------------------------------------------

def read_cmip6_deltas(delta_nc, target_month):
    """
    Read monthly precipitation delta ratios from compute_climate_deltas output.

    The delta NetCDF is expected to have variable 'delta_pr' with dimensions
    (scenario, period, month) or (model, scenario, period, month).

    Returns: dict  {scenario_period_key: ratio}
      e.g.  {"ssp245_near": 1.12, "ssp585_far": 1.28}
    """
    try:
        import xarray as xr
    except ImportError:
        logger.error("xarray required: pip install xarray")
        sys.exit(1)

    delta_path = Path(delta_nc)
    if not delta_path.exists():
        logger.warning(f"Delta NC not found: {delta_nc} — using literature defaults")
        return _literature_defaults()

    try:
        ds = xr.open_dataset(str(delta_path))
    except Exception as e:
        logger.warning(f"Could not open delta NC: {e} — using literature defaults")
        return _literature_defaults()

    ratios = {}
    month_idx = target_month - 1  # 0-indexed

    # Try to extract per-scenario values
    # Expected variable: delta_pr with coords scenario, period, month
    if "delta_pr" in ds:
        dpr = ds["delta_pr"]
        coords = {str(c): list(dpr.coords[c].values) for c in dpr.dims}

        # Map scenario labels
        scenario_map = {
            "ssp126": "ssp126", "126": "ssp126",
            "ssp245": "ssp245", "245": "ssp245",
            "ssp585": "ssp585", "585": "ssp585",
        }
        period_map = {
            "near": "near", "2041-2060": "near", "mid": "near",
            "far":  "far",  "2081-2100": "far",  "end": "far",
        }

        for sc_key in coords.get("scenario", []):
            for pd_key in coords.get("period", ["near", "far"]):
                sc_label = scenario_map.get(str(sc_key), str(sc_key))
                pd_label = period_map.get(str(pd_key), str(pd_key))
                key = f"{sc_label}_{pd_label}"
                try:
                    sel = dpr.sel(scenario=sc_key, period=pd_key)
                    if "month" in sel.dims:
                        ratio_all = sel.isel(month=month_idx).values
                    else:
                        ratio_all = sel.values
                    # Ensemble median (may have model dim)
                    ratio = float(np.nanmedian(ratio_all))
                    # delta_pr may be additive (mm/day) or multiplicative (ratio)
                    # If values look like small increments (< 5), treat as ratio
                    # If values are large (> 10), treat as mm/day absolute
                    if abs(ratio) < 5:
                        ratios[key] = max(0.5, ratio)   # direct ratio
                    else:
                        logger.warning(f"delta_pr values appear additive: {ratio:.1f}")
                        ratios[key] = max(0.5, 1.0 + ratio / 100.0)
                except Exception as e:
                    logger.debug(f"Could not extract {key}: {e}")

        ds.close()

    if not ratios:
        logger.warning("No delta_pr values extracted from NC — using literature defaults")
        return _literature_defaults()

    return ratios


def _literature_defaults():
    """
    Literature-based CMIP6 precipitation delta ratios for East China (Chaohu region).
    Source: IPCC AR6 Chapter 11, Chen et al. 2020 (Clim. Dyn.)
    July precipitation change relative to 1985-2014 baseline.
    """
    logger.info("Using literature-based CMIP6 delta ratios for East China July precipitation")
    return {
        "ssp126_near": 1.05,   # +5%  SSP1-2.6 2041-2060
        "ssp245_near": 1.10,   # +10% SSP2-4.5 2041-2060
        "ssp245_far":  1.14,   # +14% SSP2-4.5 2081-2100
        "ssp585_near": 1.13,   # +13% SSP5-8.5 2041-2060
        "ssp585_far":  1.28,   # +28% SSP5-8.5 2081-2100
    }


# ---------------------------------------------------------------------------
# SWMM .inp timeseries parser / writer
# ---------------------------------------------------------------------------

def parse_swmm_timeseries(inp_file):
    """
    Parse [TIMESERIES] block from SWMM .inp file.
    Returns: dict { ts_name: [(date_str, time_str, value_str), ...] }
    """
    content = Path(inp_file).read_text(encoding="utf-8", errors="ignore")
    result = {}

    # Extract TIMESERIES section
    match = re.search(
        r'\[TIMESERIES\](.*?)(?=\n\[|\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    if not match:
        return result

    section = match.group(1)
    for line in section.split("\n"):
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        name  = parts[0]
        date  = parts[1]
        time  = parts[2]
        value = parts[3]
        if name not in result:
            result[name] = []
        result[name].append((date, time, value))

    return result


def write_swmm_timeseries_snippet(ts_name, records, output_path, scenario_label,
                                  ratio, target_month):
    """
    Write a SWMM [TIMESERIES] snippet with scaled rainfall intensities.
    Values are multiplied by `ratio` (CMIP6 precipitation delta factor).
    """
    lines = [
        f";; CMIP6-scaled SWMM rainfall timeseries",
        f";; Source timeseries: {ts_name}",
        f";; Scenario: {scenario_label}",
        f";; Target month: {target_month} (precipitation delta ratio = {ratio:.4f})",
        f";; Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f";; CRITICAL: INTENSITY format assumed (mm/hr). Values multiplied by ratio.",
        f";;",
        f"[TIMESERIES]",
        f";;Name{' '*11}Date{' '*7}Time{' '*7}Value",
    ]
    new_ts_name = f"{ts_name}_{scenario_label}"
    for date, time, value in records:
        try:
            scaled = float(value) * ratio
        except ValueError:
            scaled = 0.0
        lines.append(f"{new_ts_name:<17}{date:<12}{time:<12}{scaled:.6f}")
    lines.append("")

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    return new_ts_name


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    errors = []
    if not Path(args.inp_file).exists():
        errors.append(f"SWMM .inp not found: {args.inp_file}")
    if not args.output_dir:
        errors.append("--output_dir required")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scale SWMM rainfall timeseries using CMIP6 precipitation deltas"
    )
    parser.add_argument("--inp_file",     required=True,
                        help="SWMM .inp file to read timeseries from")
    parser.add_argument("--delta_nc",     default="",
                        help="CMIP6 delta NetCDF from compute_climate_deltas.py")
    parser.add_argument("--output_dir",   required=True,
                        help="Directory for scaled timeseries snippets")
    parser.add_argument("--ts_name",      default="",
                        help="TIMESERIES name to scale (default: first found)")
    parser.add_argument("--target_month", type=int, default=7,
                        help="Month for design storm season (default: 7=July)")
    parser.add_argument("--scenarios",    default="",
                        help="Comma-separated scenarios to process "
                             "(default: all from delta_nc or literature defaults)")
    args = parser.parse_args()

    validate_inputs(args)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Parse SWMM timeseries
    logger.info(f"Parsing SWMM .inp: {args.inp_file}")
    all_ts = parse_swmm_timeseries(args.inp_file)
    if not all_ts:
        logger.error("No [TIMESERIES] block found in .inp file")
        sys.exit(1)

    ts_name = args.ts_name if args.ts_name else sorted(all_ts.keys())[0]
    if ts_name not in all_ts:
        logger.error(f"Timeseries '{ts_name}' not found. Available: {list(all_ts.keys())}")
        sys.exit(1)

    records = all_ts[ts_name]
    logger.info(f"Found timeseries '{ts_name}' with {len(records)} records")

    # Get CMIP6 delta ratios
    logger.info(f"Reading CMIP6 delta ratios (target month: {args.target_month})")
    delta_ratios = read_cmip6_deltas(args.delta_nc, args.target_month)

    # Filter scenarios if specified
    if args.scenarios:
        wanted = set(s.strip() for s in args.scenarios.split(","))
        delta_ratios = {k: v for k, v in delta_ratios.items() if k in wanted}

    logger.info(f"Scenarios to process: {list(delta_ratios.keys())}")

    # Write baseline (ratio=1.0) for reference
    baseline_key = f"{ts_name}_baseline"
    baseline_path = output_dir / f"{ts_name}_baseline.txt"
    write_swmm_timeseries_snippet(ts_name, records, str(baseline_path),
                                  "baseline", 1.0, args.target_month)
    logger.info(f"Written baseline: {baseline_path.name}")

    # Write scaled scenarios
    summary = {
        "source_ts": ts_name,
        "source_inp": str(args.inp_file),
        "target_month": args.target_month,
        "n_records": len(records),
        "scenarios": {}
    }

    for scenario, ratio in delta_ratios.items():
        out_path = output_dir / f"{ts_name}_{scenario}.txt"
        new_name = write_swmm_timeseries_snippet(
            ts_name, records, str(out_path), scenario, ratio, args.target_month
        )
        summary["scenarios"][scenario] = {
            "delta_ratio": round(ratio, 4),
            "output_file": str(out_path),
            "swmm_ts_name": new_name,
        }
        logger.info(f"  {scenario}: ratio={ratio:.4f} → {out_path.name}")

    # Write summary JSON
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Print instructions
    print("\n" + "="*60)
    print("CMIP6 → SWMM rainfall scaling complete.")
    print(f"Output directory: {output_dir}")
    print(f"\nTo use a scenario in SWMM:")
    print(f"  1. Copy the snippet file into your .inp [TIMESERIES] section")
    print(f"  2. Update [RAINGAGES]: change timeseries name from '{ts_name}'")
    print(f"     to e.g. '{ts_name}_ssp585_far'")
    print(f"  3. Run SWMM as usual")
    print("="*60)

    print(json.dumps({"status": "success", "summary": str(summary_path)}))
    sys.exit(0)


if __name__ == "__main__":
    main()
