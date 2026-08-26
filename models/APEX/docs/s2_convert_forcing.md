# S2 Convert Forcing

## Purpose

Write daily weather forcing and monthly weather-generator statistics into the files that the copied APEX0806 workspace actually reads. `tools/s2_convert_forcing.py` resolves the COM-style weather targets from `APEXRUN.DAT`, `SUBACOM.DAT`, `WPM1.DAT`, `WIND.DAT`, and `WDLSTCOM.DAT`, then overwrites those files in place.

## Inputs

- A workspace from `tools/s1_setup_workspace.py`
- `tools/s2_convert_forcing.py`
- Latitude, longitude, start year, end year
- One forcing source: `cmfd`, `mswx`, or `nasa_power`
- Optional `--forcing-dir`, `--elev`, and `--cache-dir`

## Outputs

- The resolved daily `*.DLY` file, for example `A48309.dly` / `A48309.DLY`, written in APEX daily weather format.
- The resolved monthly weather `*.WP1` file and wind `*.WND` file, edited using their existing template structure.
- For legacy templates only, `WDLYLIST.DAT`, `WPM1LIST.DAT`, and `WINDLIST.DAT` are rewritten to point to the generated station.

## Procedure

```bash
cd KISSPATH_KI_ROOT/APEX/knowledge_infrastructure
python tools/s1_setup_workspace.py /tmp/apex_ws
python tools/s2_convert_forcing.py \
  --workspace /tmp/apex_ws \
  --lat 32.94 --lon 117.36 \
  --year1 2010 --year2 2015 \
  --source cmfd \
  --elev 23 \
  --cache-dir /tmp/apex_forcing_cache
```

For a full quickstart, `tools/quickstart.py` calls `build_forcing()` after S1, S9, S4, and S3.

## Verification

```bash
python - <<'PY'
from pathlib import Path
ws = Path("/tmp/apex_ws")
for name in ("A48309.dly", "109.WP1", "25.WND"):
    p = ws / name
    print(name, p.exists(), p.stat().st_size if p.exists() else 0)
print((ws / "A48309.dly").read_text().splitlines()[0])
print((ws / "A48309.dly").read_text().splitlines()[-1])
PY
```

The first and last daily rows should span the requested years, and `tools/s2_convert_forcing.py` will fail if the daily file has too few rows or if case variants differ byte-for-byte.

## Traps

- `diagnostics/triplets.yaml:weather_units_srad` - APEX expects solar radiation in MJ/m2/day, not W/m2. S2 writes the APEX unit.
- `diagnostics/triplets.yaml:ngn_weather_mismatch` - S2 can write a complete `*.DLY`, but S5 controls which variables APEX reads or generates through `NGN`.
- `diagnostics/triplets.yaml:apex0806_s2_weather_template_mismatch` - the APEX0806 template uses explicit COM station IDs, so writing `WEATHER01.dly` alone is not enough.
- `diagnostics/triplets.yaml:apex0806_wp1_rainfall_rows_shifted` - the WP1 rainfall block order must keep `PRW1` / `PRW2` as probabilities, not rain-day counts.
- `diagnostics/triplets.yaml:apex0806_multidecade_forcing_not_resumable` - use `--cache-dir` for long CMFD builds.

## Example

```bash
python tools/s2_convert_forcing.py --workspace /tmp/apex_bengbu --lat 32.94 --lon 117.36 --year1 2010 --year2 2015 --source cmfd --cache-dir /tmp/apex_cmfd_cache
```
