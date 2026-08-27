# S7 Assembly

## Purpose
Assemble a complete Pywr JSON model from reservoir properties, inflow, operating rules, and demand nodes. This stage is implemented by `../tools/s7_assembly/assemble_pywr_model.py`.

## Inputs
- Reservoir JSON from S3.
- Inflow CSV from S4.
- Optional operating-rules JSON from S5.
- Optional demands JSON from S6.
- Simulation dates and timestep.
- Tool: `../tools/s7_assembly/assemble_pywr_model.py`

## Outputs
- Pywr model JSON for S8.
- JSON sections include `metadata`, `timestepper`, `solver`, `nodes`, `edges`, `parameters`, and recorders.
- Dataframe CSV paths are written for Pywr loading.

## Procedure
Assemble the full model:

```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"

"$PYWR_PYTHON" "$KI/tools/s7_assembly/assemble_pywr_model.py" \
  --reservoir_json /tmp/pywr_reservoir.json \
  --inflow_csv /tmp/pywr_inflow.csv \
  --rules_json /tmp/pywr_rules.json \
  --demands_json /tmp/pywr_demands.json \
  --start_date 1980-01-01 \
  --end_date 1990-12-31 \
  --output /tmp/pywr_model.json
```

Minimal model without optional rules or demands:

```bash
"$PYWR_PYTHON" "$KI/tools/s7_assembly/assemble_pywr_model.py" \
  --reservoir_json /tmp/pywr_reservoir.json \
  --inflow_csv /tmp/pywr_inflow.csv \
  --start_date 1980-01-01 \
  --end_date 1990-12-31 \
  --output /tmp/pywr_model.json
```

## Verification
- Confirm `/tmp/pywr_model.json` exists and parses as JSON.
- Check `solver.name` is `glpk`.
- Check all node `type` and parameter `type` values are lowercase Pywr schema values.
- Check every edge endpoint appears in `nodes`.
- Check the timestepper dates are fully covered by the S4 inflow CSV.

## Traps
- `dt_pywr_002`: invalid Pywr JSON structure, wrong node type case, or missing required fields.
- `dt_pywr_003`: an edge references a node name not present in `nodes`.
- `dt_pywr_004`: dataframe `url` paths are resolved relative to the model JSON location; use generated absolute paths.
- `dt_pywr_007`: parameter type names are case-sensitive and must be lowercase.
- `dt_pywr_013`: model date range must match the inflow CSV.

## Example
```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"
"$PYWR_PYTHON" "$KI/tools/s7_assembly/assemble_pywr_model.py" \
  --reservoir_json /tmp/pywr_reservoir.json \
  --inflow_csv /tmp/pywr_inflow.csv \
  --rules_json /tmp/pywr_rules.json \
  --demands_json /tmp/pywr_demands.json \
  --start_date 1980-01-01 \
  --end_date 1990-12-31 \
  --output /tmp/pywr_model.json
```
