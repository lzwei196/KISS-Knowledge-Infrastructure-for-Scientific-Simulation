# Stage 3: Build Riverine Inflow Hydrograph

## Purpose

Convert a gauge discharge record into the `time_seconds,discharge_m3s` hydrograph consumed by `tools/run_anuga.py --inflow_csv`. This is the riverine inflow branch in `SKILL.md`, applied through ANUGA `Inlet_operator`.

## Inputs

- `tools/build_inflow_hydrograph.py`
- Exactly one of:
  - `--gauge_csv`, a tidy `date,value[,symbol]` CSV from `tools/load_hydat_series.py`
  - `--gauge_txt`, a China water-level archive TAB file with `stcd,dates,z,Q,name`
- Inclusive `--start` and `--end` dates

## Outputs

- A CSV with columns `time_seconds,discharge_m3s`
- Time is relative to `--start` at 00:00, so it shares the same time origin as rainfall CSVs from `tools/convert_forcing_to_anuga.py`

## Procedure

From the KI root, build an inflow hydrograph from a tidy HYDAT flow CSV:

```bash
python tools/build_inflow_hydrograph.py \
    --gauge_csv ./obs/hope_flow.csv \
    --start 2020-04-01 \
    --end 2020-06-30 \
    --output_csv ./forcing/inflow.csv
```

For a China TAB archive, use `--gauge_txt` instead of `--gauge_csv`; the input file must be a tab-separated archive with the `dates` and `Q` columns documented in `tools/build_inflow_hydrograph.py`.

```bash
python tools/build_inflow_hydrograph.py \
    --gauge_txt ./obs/china_station.txt \
    --start 2003-07-01 \
    --end 2003-08-07 \
    --output_csv ./forcing/inflow_lutaizi.csv
```

The tool drops missing or negative sentinel discharge values and refuses to emit a hydrograph with less than two valid rows or less than 80 percent event coverage.

## Verification

Check the output before running ANUGA:

```bash
python - <<'PY'
import csv
rows = list(csv.DictReader(open("./forcing/inflow.csv")))
assert len(rows) >= 2, "inflow hydrograph needs at least two rows"
assert {"time_seconds", "discharge_m3s"} <= set(rows[0]), rows[0].keys()
times = [float(r["time_seconds"]) for r in rows]
flows = [float(r["discharge_m3s"]) for r in rows]
assert times[0] == 0.0, times[0]
assert all(b > a for a, b in zip(times, times[1:])), "time_seconds not increasing"
assert max(flows) > 0.0, "zero-discharge hydrograph"
print(len(rows), times[-1], max(flows))
PY
```

## Traps

- `dt_anuga_004`: do not pass this file as `--forcing_csv`; rainfall files need `rainfall_m_per_s`, while inflow files need `discharge_m3s`.
- `dt_anuga_008`: a valid hydrograph still ponds if the downstream side is Reflective. Remedy: set `tools/run_anuga.py --outlet_side` to the actual drainage edge.
- `dt_anuga_010`: a physically plausible hydrograph can still travel too fast if `--manning_n` is unrealistically low.

## Example

The Fraser example in `SKILL.md` builds the driver from `./obs/hope_flow.csv`:

```bash
python tools/build_inflow_hydrograph.py --gauge_csv ./obs/hope_flow.csv \
    --start 2020-04-01 --end 2020-06-30 --output_csv ./forcing/inflow.csv
```

Then pass `./forcing/inflow.csv` to `tools/run_anuga.py --inflow_csv`.
