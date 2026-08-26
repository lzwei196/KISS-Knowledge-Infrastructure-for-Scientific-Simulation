# Stage 1: Convert Rainfall Forcing

## Purpose

Convert CMFD, MSWX, or NASA POWER precipitation into the ANUGA rainfall CSV consumed by `tools/run_anuga.py --forcing_csv`. This is the rain-on-grid branch described in `SKILL.md`: ANUGA `Rate_operator` expects rainfall as a rate in m/s over the mesh.

## Inputs

- `tools/convert_forcing_to_anuga.py`
- A forcing source selected with `--source cmfd`, `--source mswx`, or `--source nasa_power`
- `--lat`, `--lon`, `--start_year`, `--end_year`
- Optional `--forcing_dir` when the default `ki_tools_common.load_forcing` lookup should be overridden

## Outputs

- `rainfall_timeseries.csv` with columns `time_seconds,rainfall_m_per_s`
- `forcing_summary.json` with source, duration, timestep, total precipitation, and max rainfall-rate metadata

## Procedure

From the KI root:

```bash
python tools/convert_forcing_to_anuga.py \
    --source cmfd \
    --lat 32.9 --lon 117.4 \
    --start_year 2005 --end_year 2005 \
    --output_dir ./forcing/
```

The implementation in `tools/convert_forcing_to_anuga.py` first tries `load_hourly_forcing`, falls back to `load_daily_forcing` only when needed, converts mm per timestep to m/s, and validates the emitted CSV.

Use this stage only for rain-on-grid forcing. For river water routed in from upstream, use `docs/s2_load_hydat_series.md` and `docs/s3_build_inflow_hydrograph.md`.

## Verification

Check the generated files:

```bash
python - <<'PY'
import csv, json, pathlib
root = pathlib.Path("forcing")
rows = list(csv.DictReader(open(root / "rainfall_timeseries.csv")))
summary = json.load(open(root / "forcing_summary.json"))
assert rows, "rainfall_timeseries.csv has no data rows"
assert {"time_seconds", "rainfall_m_per_s"} <= set(rows[0]), rows[0].keys()
rates = [float(r["rainfall_m_per_s"]) for r in rows]
assert min(rates) >= 0.0, "negative rainfall rate"
assert summary["n_timesteps"] == len(rows)
print(len(rows), max(rates), summary["total_precip_mm"])
PY
```

## Traps

- `dt_anuga_001`: rainfall passed in mm/hr or source units instead of m/s floods the model by orders of magnitude. Remedy: regenerate with `tools/convert_forcing_to_anuga.py`.
- `dt_anuga_002`: rainfall already in m/s divided again produces no flooding. Remedy: inspect `forcing_summary.json` and confirm realistic `max_rainfall_m_per_s`.
- `dt_anuga_004`: `tools/run_anuga.py` requires exact CSV headers `time_seconds,rainfall_m_per_s`.

## Example

For a one-year CMFD rainfall driver at Huai basin coordinates:

```bash
python tools/convert_forcing_to_anuga.py \
    --source cmfd \
    --lat 32.9 --lon 117.4 \
    --start_year 2005 --end_year 2005 \
    --output_dir ./forcing/
```

Then pass `./forcing/rainfall_timeseries.csv` to `tools/run_anuga.py --forcing_csv`.
