# s4 Outflow

## Purpose

Generate the GLM outflow boundary configuration and, when needed, an outflow CSV. This stage defines natural overflow, constant release, scheduled reservoir operation, or a balance-mode release equal to inflow.

## Inputs

- Morphometry crest elevation from s1.
- Inflow CSV from s3 for balance mode.
- Optional release schedule CSV with `time,FLOW`.
- Tool: `tools/s4_outflow/configure_outflow.py`.

## Outputs

- Optional outflow CSV, usually `bcs/outflow.csv`, with `time,FLOW`.
- Outflow config JSON, usually `outflow_config.json`, consumed by s6.
- JSON fields such as `mode`, `num_outlet`, `outl_elvs`, `bsn_len_outl`, `bsn_wid_outl`, `crest_width`, and `crest_factor`.

## Procedure

1. Natural overflow mode writes only config; GLM computes overflow internally:

```bash
python tools/s4_outflow/configure_outflow.py \
  --mode natural \
  --crest_elev 320 \
  --output_json outflow_config.json
```

2. Constant managed release:

```bash
python tools/s4_outflow/configure_outflow.py \
  --mode constant --flow 10.0 \
  --crest_elev 320 --outflow_elev 315 \
  --start_date 2000-01-01 --end_date 2010-12-31 \
  --output bcs/outflow.csv \
  --output_json outflow_config.json
```

3. Balance mode for a stable water-level first pass:

```bash
python tools/s4_outflow/configure_outflow.py \
  --mode balance \
  --inflow_csv bcs/inflow_1.csv \
  --crest_elev 320 \
  --start_date 2000-01-01 --end_date 2010-12-31 \
  --output bcs/outflow.csv \
  --output_json outflow_config.json
```

## Verification

- `outflow_config.json` has `"status": "success"`.
- `num_outlet` is `0` for natural overflow and `1` for CSV-controlled releases.
- `outl_elvs` is physically within the lake/reservoir elevation range.
- In balance mode, `bcs/outflow.csv` has the same date coverage as `bcs/inflow_1.csv`.

## Traps

- `dt_010`: if s6 writes `num_inflows=0` or inconsistent flow counts, GLM can ignore files silently.
- `dt_017`: downstream coupling only works when inflow and outflow grid cells are hydrologically aligned.
- `dt_011` and `dt_012`: relative paths in `glm3.nml` are resolved from the GLM run directory.

## Example

```bash
python tools/s4_outflow/configure_outflow.py \
  --mode scheduled --flow 15.0 \
  --crest_elev 155 --outflow_elev 145 \
  --start_date 2001-01-01 --end_date 2010-12-31 \
  --output bcs/outflow.csv \
  --output_json outflow_config.json
```
