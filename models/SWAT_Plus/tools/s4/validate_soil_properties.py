#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      validate_soil_properties
Stage:        s4_soil_database
Description:  Validate soils.sol: bulk density, AWC, texture sums, layer ordering, nly match.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path

SOILS_SOL_PATH = ""
if len(sys.argv) >= 2:
    SOILS_SOL_PATH = sys.argv[1]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    if not SOILS_SOL_PATH or not Path(SOILS_SOL_PATH).exists():
        logger.error(f"soils.sol not found: {SOILS_SOL_PATH}")
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    lines = Path(SOILS_SOL_PATH).read_text().strip().split('\n')
    issues = []
    n_soils = 0
    i = 2  # Skip title and header

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        parts = line.split()
        if len(parts) >= 4 and not parts[0].replace('.','').replace('-','').isdigit():
            # This is a profile line
            soil_name = parts[0]
            try:
                nly = int(parts[1])
            except (ValueError, IndexError):
                issues.append({"soil": soil_name, "issue": "Cannot parse nly", "severity": "fatal"})
                i += 1
                continue

            n_soils += 1
            i += 1  # Skip layer header line
            i += 1  # Move to first layer

            prev_dp = 0
            actual_layers = 0
            for layer_idx in range(nly):
                if i >= len(lines):
                    issues.append({"soil": soil_name, "issue": f"Expected {nly} layers but file ends after {actual_layers}", "severity": "fatal"})
                    break
                lparts = lines[i].strip().split()
                if len(lparts) < 9:
                    issues.append({"soil": soil_name, "layer": layer_idx+1, "issue": f"Layer has only {len(lparts)} fields (need >= 9)", "severity": "fatal"})
                    i += 1
                    actual_layers += 1
                    continue

                try:
                    dp = float(lparts[0])
                    bd = float(lparts[1])
                    awc = float(lparts[2])
                    k = float(lparts[3])
                    cbn = float(lparts[4])
                    clay = float(lparts[5])
                    silt = float(lparts[6])
                    sand = float(lparts[7])

                    # Validation checks
                    if dp <= prev_dp:
                        issues.append({"soil": soil_name, "layer": layer_idx+1, "issue": f"Layer depth {dp} <= previous {prev_dp}", "severity": "fatal"})
                    if not (0.9 <= bd <= 2.5):
                        issues.append({"soil": soil_name, "layer": layer_idx+1, "issue": f"Bulk density {bd} outside [0.9, 2.5]", "severity": "degraded"})
                    if not (0.0 <= awc <= 0.5):
                        issues.append({"soil": soil_name, "layer": layer_idx+1, "issue": f"AWC {awc} outside [0.0, 0.5]", "severity": "degraded"})
                    if k <= 0:
                        issues.append({"soil": soil_name, "layer": layer_idx+1, "issue": f"Ksat {k} <= 0", "severity": "fatal"})
                    texture_sum = clay + silt + sand
                    if abs(texture_sum - 100) > 1:
                        issues.append({"soil": soil_name, "layer": layer_idx+1, "issue": f"Texture sum {texture_sum:.1f} != 100", "severity": "fatal"})

                    prev_dp = dp
                except (ValueError, IndexError) as e:
                    issues.append({"soil": soil_name, "layer": layer_idx+1, "issue": f"Parse error: {e}", "severity": "fatal"})

                actual_layers += 1
                i += 1

            if actual_layers != nly:
                issues.append({"soil": soil_name, "issue": f"nly={nly} but found {actual_layers} layers", "severity": "fatal"})
        else:
            i += 1

    n_fatal = sum(1 for i in issues if i.get("severity") == "fatal")
    return {
        "status": "pass" if n_fatal == 0 else "fail",
        "n_soils": n_soils,
        "total_issues": len(issues),
        "fatal_issues": n_fatal,
        "issues": issues[:50]
    }

def validate_outputs(result):
    if result["fatal_issues"] > 0:
        logger.warning(f"Soil data has {result['fatal_issues']} fatal issues")
    logger.info("Validation complete.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
