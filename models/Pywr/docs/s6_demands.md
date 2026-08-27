# S6 Demands

## Purpose
Generate environmental, irrigation, municipal, and industrial demand-node definitions for the Pywr allocation graph. This stage is implemented by `../tools/s6_demands/create_demand_nodes.py`.

## Inputs
- Mean annual flow in `m3/s` for environmental demand.
- Irrigated area in `km2`, crop type, and irrigation efficiency for irrigation demand.
- Population and liters/person/day for municipal demand.
- Industrial demand in `m3/s`.
- Tool: `../tools/s6_demands/create_demand_nodes.py`
- Demand coupling notes: `model_couplings.yaml` entry `coupling_dssat_to_pywr_irrigation`.

## Outputs
- Demand JSON for S7 with demand-node definitions, priorities/costs, and summary totals.
- The output can contain one demand type or all supported types.

## Procedure
Create environmental demand after S4 gives a mean-flow estimate:

```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"

"$PYWR_PYTHON" "$KI/tools/s6_demands/create_demand_nodes.py" \
  --type environmental \
  --mean_annual_flow_m3s 150.0 \
  --eflow_percent 10 \
  --output /tmp/pywr_demands.json
```

Create a combined demand file:

```bash
"$PYWR_PYTHON" "$KI/tools/s6_demands/create_demand_nodes.py" \
  --type all \
  --mean_annual_flow_m3s 150.0 \
  --irrigated_area_km2 500 \
  --crop wheat \
  --population 500000 \
  --industrial_m3s 5.0 \
  --output /tmp/pywr_demands.json
```

## Verification
- Confirm the JSON has `"status": "OK"` and `demand_count` is nonzero.
- Check `total_mean_demand_m3s` is plausible relative to S4 mean inflow.
- For environmental demand, verify required `--mean_annual_flow_m3s` was supplied.
- For irrigation demand, verify `--irrigated_area_km2` and `--irrigation_efficiency` reflect the modeled basin.

## Traps
- `dt_pywr_009`: excessive demands can make the S8 LP infeasible unless supply, storage, and spill/slack paths can satisfy constraints.
- `dt_pywr_015`: if S4 mean inflow was converted incorrectly, environmental demand derived from MAF is also wrong.
- Missing required arguments produce JSON `error` messages, for example environmental demand without `--mean_annual_flow_m3s`.

## Example
```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"
"$PYWR_PYTHON" "$KI/tools/s6_demands/create_demand_nodes.py" \
  --type all \
  --mean_annual_flow_m3s 150.0 \
  --irrigated_area_km2 500 \
  --crop wheat \
  --population 500000 \
  --industrial_m3s 5.0 \
  --output /tmp/pywr_demands.json
```
