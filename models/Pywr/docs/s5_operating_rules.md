# S5 Operating Rules

## Purpose
Generate monthly reservoir control curves, release limits, and cost priorities for the Pywr allocation model. This stage is implemented by `../tools/s5_operating_rules/create_operating_rules.py`.

## Inputs
- Reservoir JSON from S3, such as `/tmp/pywr_reservoir.json`.
- Reservoir purpose: `flood_control`, `irrigation`, `hydropower`, or `multipurpose`.
- Region flood-season preset, such as `china_east`, or custom `--flood_months`.
- Tool: `../tools/s5_operating_rules/create_operating_rules.py`

## Outputs
- Operating-rules JSON for S7.
- Monthly control curve and volume targets.
- Release and spill behavior parameters used by `assemble_pywr_model.py`.

## Procedure
Generate rules from S3 reservoir properties:

```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"

"$PYWR_PYTHON" "$KI/tools/s5_operating_rules/create_operating_rules.py" \
  --reservoir_json /tmp/pywr_reservoir.json \
  --purpose flood_control \
  --region china_east \
  --output /tmp/pywr_rules.json
```

Manual capacity mode:

```bash
"$PYWR_PYTHON" "$KI/tools/s5_operating_rules/create_operating_rules.py" \
  --capacity_mcm 2275 \
  --dam_height_m 88 \
  --purpose multipurpose \
  --flood_months 6,7,8,9 \
  --output /tmp/pywr_rules.json
```

## Verification
- Check monthly arrays have exactly 12 values.
- Confirm flood-season months have lower target storage for flood-control operation.
- Confirm the rule JSON uses the same reservoir capacity scale as S3.
- Use `../docs/model_couplings.yaml` and `../dag.yaml` to confirm the control curve is part of Pywr's storage regulation, not an external hydrology calculation.

## Traps
- `dt_pywr_010`: monthly profile arrays must contain exactly 12 values.
- `dt_pywr_006`: without a connected control curve, storage can bang between min and max with unrealistic releases.
- `dt_pywr_014`: if manual `--capacity_mcm` is wrong, downstream S7 storage volume will be wrong by orders of magnitude.

## Example
```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"
"$PYWR_PYTHON" "$KI/tools/s5_operating_rules/create_operating_rules.py" \
  --reservoir_json /tmp/pywr_reservoir.json \
  --purpose multipurpose \
  --region china_east \
  --output /tmp/pywr_rules.json
```
