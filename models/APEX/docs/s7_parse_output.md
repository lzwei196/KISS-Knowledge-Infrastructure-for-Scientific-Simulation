# S7 Parse Output

## Purpose

Parse APEX annual output tables into a pandas DataFrame or CSV. `tools/s7_parse_output.py` scans `*.ACY` and `*.OUT` files, preserving the source filename in `__source__`.

## Inputs

- A workspace after S6
- `tools/s7_parse_output.py`
- Non-empty `*.ACY` or `*.OUT` files
- Optional CSV output path

## Outputs

- A pandas DataFrame from `parse(workspace)`
- A CSV when `--out` is supplied
- Optional daily watershed DataFrame through the Python API `parse_daily_water(workspace, out_csv=...)` when a `*.DWS` file exists

## Procedure

```bash
cd KISSPATH_KI_ROOT/APEX/knowledge_infrastructure
python tools/s7_parse_output.py --workspace /tmp/apex_ws --out /tmp/apex_ws/results.csv
```

For daily water output:

```python
from tools.s7_parse_output import parse_daily_water
parse_daily_water("/tmp/apex_ws", out_csv="/tmp/apex_ws/daily_water.csv")
```

## Verification

```bash
python - <<'PY'
import pandas as pd
df = pd.read_csv("/tmp/apex_ws/results.csv")
print(df.shape)
print(df["__source__"].value_counts().head())
print(df.head())
PY
```

The parsed year range should match `APEXCONT.DAT` after spin-up handling expectations. For scored analyses, filter out spin-up years before comparing to observations.

## Traps

- `diagnostics/triplets.yaml:apex0806_template_outputs_parsed_as_results` - if S1 was bypassed or old outputs remain, S7 can parse stale template results.
- `diagnostics/triplets.yaml:zero_exit_silent_crash` - an exit code does not prove the outputs belong to the current run; check output timestamps and year span.
- `diagnostics/triplets.yaml:spinup_low_yields` - early spin-up rows are not validation years.
- `SKILL.md` "Scoring YLDG" section - regional aggregate yield series such as GDHY require detrending and area-representative management before scoring.

## Example

```bash
python tools/s7_parse_output.py --workspace /tmp/apex_bengbu --out /tmp/apex_bengbu/results.csv
python -c 'import pandas as pd; print(pd.read_csv("/tmp/apex_bengbu/results.csv").tail())'
```
