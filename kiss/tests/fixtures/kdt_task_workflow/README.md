# Rainfall summary workflow

This is a small scientific **task workflow**, not a process-based simulator.
It reads a daily CSV containing `date` and `precip_mm`, checks the records, and
writes monthly precipitation totals.  The workflow has no evolving physical
state, calibration parameters, numerical solver, or model binary.

## Run

```bash
python3 summarize_rainfall.py \
  --input examples/daily_rain.csv \
  --output monthly_totals.csv
```

## Inputs and outputs

- Input: UTF-8 CSV with ISO dates and precipitation in millimetres.
- Output: UTF-8 CSV with `month`, `total_precip_mm`, and `n_days`.
- Negative precipitation and malformed dates cause a non-zero exit.
