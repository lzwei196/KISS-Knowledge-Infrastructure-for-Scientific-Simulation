# s6 TSI Analysis

## Purpose

Compute and interpret Carlson Trophic State Index values for lake or reservoir water. In this KI, TSI is computed by `tools/run_wasp.py` during `simulate` when chlorophyll-a forcing is present, and `tools/parse_output_wasp.py` extracts/classifies TSI values from model output.

## Inputs

- Forcing JSON from `tools/convert_forcing_to_wasp.py`
- Chlorophyll-a values in ug/L for `TSI_chla`
- Optional Secchi depth in m and total phosphorus in ug/L when available in the forcing or upstream data
- Parameter JSON from `tools/convert_parameters_to_wasp.py`
- `tools/run_wasp.py`
- `tools/parse_output_wasp.py`

## Outputs

- `output.tsi` in the simulation JSON when Chl-a forcing is present
- Parser metrics JSON with a `tsi` block when the input output contains TSI
- Trophic classification: oligotrophic, mesotrophic, eutrophic, or hypereutrophic

## Procedure

Run from the KI root after creating forcing and parameter files:

```bash
python tools/run_wasp.py \
  --mode simulate \
  --forcing /tmp/wasp_forcing.json \
  --params /tmp/wasp_params.json \
  --output /tmp/wasp_tsi_simulation.json

python tools/parse_output_wasp.py \
  --input /tmp/wasp_tsi_simulation.json \
  --metrics-json /tmp/wasp_tsi_metrics.json
```

If Chl-a is missing, return to stage 1 and include a WQP/NLA chemistry source:

```bash
python tools/convert_forcing_to_wasp.py \
  --wqp-dir /path/to/WQP/Lake_Erie_Central \
  --nla-chem-csv /path/to/nla2017_water_chem.csv \
  --output /tmp/wasp_forcing.json
```

## Verification

- `output.tsi` exists in the simulation JSON when Chl-a records are present.
- `TSI_chla` and `TSI_mean` are finite numbers.
- The parser assigns `classification` based on `TSI_mean`.
- If Secchi and TP are available, compare the indices rather than relying on only one number.

## Traps

- `dt_wasp_017`: zero or negative Chl-a, Secchi, or TP values cannot be used in log-based TSI formulas.
- `dt_wasp_023`: TSI index disagreement greater than 15 points indicates non-algal turbidity, nutrient limitation, or another water-quality interpretation issue.
- `dt_wasp_025`: Chl-a in mg/L makes TSI deeply negative unless converted to ug/L.
- `dt_wasp_003`: DO percent saturation is not a TSI input, but the same unit-discipline problem can invalidate water-quality interpretation across stages.

## Example

```bash
python tools/run_wasp.py --mode simulate --forcing /tmp/erie_forcing.json --params /tmp/erie_params.json --output /tmp/erie_tsi.json
python tools/parse_output_wasp.py --input /tmp/erie_tsi.json --metrics-json /tmp/erie_tsi_metrics.json
```

