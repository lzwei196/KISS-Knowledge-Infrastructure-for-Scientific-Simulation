# Stage 3: Convert Parameters

## Purpose

Create the parameter JSON consumed by the analytic LPJ-GUESS runner. This stage selects built-in PFT defaults, applies explicit overrides, optionally derives `LUE_max` from leaf traits, and validates parameter ranges before writing JSON.

## Inputs

- `tools/convert_parameters_to_lpjguess.py`
- PFT name or alias such as `enf`, `dbf`, `c3g`, or `tbe`
- Optional parameter overrides such as `--lue-max`, `--t-opt`, `--vpd-1`, `--ra-base`, `--rh-base`, and `--rh-q10`
- Optional trait inputs: `--vcmax-base`, `--sla`, `--leaf-n`
- Optional base JSON via `--from-json`

## Outputs

A JSON file containing the runner parameters, including:

- `LUE_max`
- `T_opt`, `T_min`, `T_max`
- `VPD_0`, `VPD_1`
- `SW_in_scale`
- `Ra_base`, `Ra_Q10`, `Ra_Tref`
- `Rh_base`, `Rh_Q10`, `Rh_Tref`
- `C_pool_scale`

This file is the `--params` input to `tools/run_lpjguess.py`.

## Procedure

Check the converter interface and available PFT names:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/convert_parameters_to_lpjguess.py --help
```

Generate default temperate deciduous broadleaf parameters:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/convert_parameters_to_lpjguess.py \
  --pft dbf \
  --output /tmp/lpjguess_params.json
```

Generate a calibrated-style parameter file with explicit overrides:

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/convert_parameters_to_lpjguess.py \
  --pft dbf \
  --lue-max 1.8 \
  --t-opt 22 \
  --vpd-1 35 \
  --ra-base 0.48 \
  --rh-base 2.2 \
  --rh-q10 2.0 \
  --output /tmp/lpjguess_params.json
```

## Verification

Validate the written JSON:

```bash
python3 - <<'PY'
import json
from pathlib import Path
params = json.loads(Path("/tmp/lpjguess_params.json").read_text())
required = ["LUE_max", "T_opt", "T_min", "T_max", "VPD_0", "VPD_1",
            "SW_in_scale", "Ra_base", "Ra_Q10", "Rh_base", "Rh_Q10",
            "C_pool_scale"]
missing = [key for key in required if key not in params]
print("missing", missing)
print({key: params[key] for key in required if key in params})
PY
```

Check that the converter reports `Output parameters validated` and that `T_min < T_opt < T_max`, `Ra_base` is between `0` and `1`, and Q10 values are at least `1.0`.

## Traps

- `dt_lpjguess_011`: if GPP is high everywhere after stage 4, revisit `LUE_max` in this JSON; `tools/convert_parameters_to_lpjguess.py` warns when it is outside the normal range.
- `dt_lpjguess_012`: wrong seasonal GPP timing usually means `T_opt`, `T_min`, or `T_max` does not match the PFT climate niche.
- `dt_lpjguess_013`: winter or summer respiration errors are usually controlled by `Rh_Q10`, `Rh_base`, and `Rh_Tref`.
- `dt_lpjguess_003`: `VPD_0` and `VPD_1` are hPa parameters; do not provide kPa or Pa thresholds.

## Example

```bash
cd KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
python3 tools/convert_parameters_to_lpjguess.py \
  --pft temperate_needleleaf_evergreen \
  --output /tmp/enf_lpjguess_params.json
```

Use `/tmp/enf_lpjguess_params.json` as the stage 4 `--params` file.
