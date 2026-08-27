# Stage 4: Run ANUGA Simulation

## Purpose

Create the ANUGA triangular domain, fit DEM elevation, apply rainfall and/or riverine inflow, evolve the real ANUGA shallow-water solver, and write an SWW file for post-processing. This stage must run the installed `anuga` package; `SKILL.md` forbids replacing it with a toy model.

## Inputs

- `tools/run_anuga.py`
- Required domain center `--lat`, `--lon`
- Domain controls: `--extent_m`, `--max_area`, `--manning_n`, `--finaltime`, `--yieldstep`
- Optional rainfall driver `--forcing_csv ./forcing/rainfall_timeseries.csv`
- Optional riverine driver `--inflow_csv ./forcing/inflow.csv` plus `--inlet_latlon LAT LON` or `--inlet_xy X Y`
- Optional `--dem_path`; otherwise terrain is resolved as described in `SKILL.md`

## Outputs

- `anuga_sim.sww` in `--output_dir`
- `run_summary.json` with mesh count, forcing paths, outlet side, inlet metadata, DEM source paths, DEM range, and SWW existence

## Procedure

Run `preflight_check.py` first from the KI root:

```bash
python preflight_check.py
```

Rain-on-grid run:

```bash
python tools/run_anuga.py \
    --lat 32.9 --lon 117.4 \
    --extent_m 5000 \
    --forcing_csv ./forcing/rainfall_timeseries.csv \
    --output_dir ./output/ \
    --finaltime 86400
```

Riverine inflow run:

```bash
python tools/run_anuga.py \
    --lat 49.230 --lon -121.740 \
    --extent_m 20000 \
    --max_area 30000 \
    --manning_n 0.035 \
    --outlet_side left \
    --inflow_csv ./forcing/inflow.csv \
    --inlet_latlon 49.2745 -121.651 \
    --inlet_radius_m 1200 \
    --finaltime 7862400 \
    --yieldstep 21600 \
    --output_dir ./output/
```

Use `--inlet_latlon` rather than hand-converting frames; `tools/run_anuga.py` routes it through `latlon_to_domain_xy`.

## Verification

Check that ANUGA wrote a real SWW and that the DEM source was recorded:

```bash
python - <<'PY'
import json, os
summary = json.load(open("./output/run_summary.json"))
assert summary["sww_exists"], summary
assert os.path.isfile(summary["sww_output"]), summary["sww_output"]
assert summary["n_triangles"] > 0, summary["n_triangles"]
assert summary["dem_sources"] or summary["dem_range_m"], "DEM metadata missing"
print(summary["n_triangles"], summary["sww_output"], summary["dem_sources"])
PY
```

For analytical validation, the KI also carries `diagnostics/run_dam_break_wet.py`, which compares ANUGA against the shipped Stoker/Ritter wet-bed dam-break reference:

```bash
python diagnostics/run_dam_break_wet.py
```

## Traps

- `dt_anuga_016`: `import anuga` fails because compiled extensions do not match the Python runtime. Remedy: use `preflight_check.py` and reinstall ANUGA for the active Python if needed.
- `dt_anuga_023`: a non-China site needs `--dem_path` or the automatic global DEM fallback; confirm `run_summary.json` `dem_sources`.
- `dt_anuga_018` and `dt_anuga_019`: DEM coverage or coordinate-frame mistakes flatten or shift terrain. Remedy: trust the built-in DEM range guard and do not bypass `latlon_to_domain_xy`.
- `dt_anuga_008`, `dt_anuga_009`, and `dt_anuga_015`: outlet side, boundary tags, and Transmissive mass balance can dominate results.
- `dt_anuga_011`, `dt_anuga_013`, and `dt_anuga_014`: mesh resolution and wet/dry numerics control runtime, stability, and wetting-front behavior.

## Example

For a riverine HYDAT run after stages 2 and 3:

```bash
python tools/run_anuga.py --lat 49.230 --lon -121.740 --extent_m 20000 \
    --max_area 30000 --manning_n 0.035 --outlet_side left \
    --inflow_csv ./forcing/inflow.csv \
    --inlet_latlon 49.2745 -121.651 --inlet_radius_m 1200 \
    --finaltime 7862400 --yieldstep 21600 --output_dir ./output/
```

The next stage reads `./output/anuga_sim.sww`.
