# Stage 2: Load HYDAT Observation Series

## Purpose

Extract a daily HYDAT discharge or level series into the tidy `date,value,symbol` CSV used by this KI's riverine workflow. `--variable flow` produces an upstream discharge record for `tools/build_inflow_hydrograph.py`; `--variable level` produces a downstream stage observation and a datum sidecar for scoring.

## Inputs

- `tools/load_hydat_series.py`
- HYDAT SQLite database, default `KISSPATH_DATA/Hydat_sqlite3_20260116/Hydat.sqlite3`
- HYDAT `--station`
- `--variable flow` or `--variable level`
- Inclusive `--start` and `--end` dates

## Outputs

- A tidy CSV with columns `date,value,symbol`
- A sidecar `<output_csv>.meta.json` containing station metadata, datum name/id, datum conversions, period coverage, and symbol counts

## Procedure

From the KI root, extract the upstream flow driver:

```bash
python tools/load_hydat_series.py \
    --station 08MF005 \
    --variable flow \
    --start 2020-04-01 \
    --end 2020-06-30 \
    --output_csv ./obs/hope_flow.csv
```

For a downstream stage target, use `--variable level`:

```bash
python tools/load_hydat_series.py \
    --station 08MF035 \
    --variable level \
    --start 2020-04-01 \
    --end 2020-06-30 \
    --output_csv ./obs/agassiz_level.csv
```

The tool reads HYDAT's month-per-row, day-column tables and writes one row per valid date. It also opens the database read-only with `immutable=1`, which is required for the archive path used by this KI.

## Verification

Inspect both the CSV and the datum sidecar before using the series:

```bash
python - <<'PY'
import csv, json
csv_path = "./obs/agassiz_level.csv"
rows = list(csv.DictReader(open(csv_path)))
meta = json.load(open(csv_path + ".meta.json"))
assert rows, "no HYDAT rows emitted"
assert {"date", "value", "symbol"} <= set(rows[0]), rows[0].keys()
assert meta["coverage"] >= 0.9, meta["coverage"]
print(meta["station_id"], meta["variable"], meta["datum_name"], meta["datum_id"], len(rows))
PY
```

For stage scoring, read `datum_name`, `datum_id`, and `datum_conversions` in the sidecar before comparing to ANUGA `stage_m`.

## Traps

- `dt_anuga_003`: DEM elevations and water levels on different vertical datums create silent stage offsets. Remedy: use the sidecar metadata before scoring.
- `dt_anuga_025`: HYDAT stations on `ASSUMED DATUM` are not directly comparable to DEM elevations. Remedy: apply a published `STN_DATUM_CONVERSION` offset or choose a geodetic-datum station.
- `dt_anuga_024`: a gauge lat/lon may be on a bank or bridge, so stage extraction later can be flat unless snapped to the channel.

## Example

The riverine worked example in `SKILL.md` uses HYDAT `08MF005` flow as the driver and HYDAT `08MF035` level as the downstream target:

```bash
python tools/load_hydat_series.py --station 08MF005 --variable flow \
    --start 2020-04-01 --end 2020-06-30 --output_csv ./obs/hope_flow.csv
python tools/load_hydat_series.py --station 08MF035 --variable level \
    --start 2020-04-01 --end 2020-06-30 --output_csv ./obs/agassiz_level.csv
```
