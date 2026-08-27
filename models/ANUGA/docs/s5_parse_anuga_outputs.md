# Stage 5: Parse ANUGA Outputs

## Purpose

Extract usable validation products from ANUGA SWW output: discharge through a cross-section, stage/depth at a gauge, and peak inundation extent scored against an observed flood mask. This stage implements the output variables and observability caveats in `dag.yaml` and `docs/validation_convention.yaml`.

## Inputs

- `tools/parse_anuga_output.py`
- `--sww_file ./output/anuga_sim.sww` from `tools/run_anuga.py`
- One or more extraction targets:
  - `--cross_section "x1,y1,x2,y2"` in absolute model meters for discharge
  - `--gauge_xy "x,y"` or `--gauge_latlon "lat,lon"` for stage/depth
  - `--inundation_extent --obs_mask <GeoTIFF>` for CSI/POD/FAR flood extent scoring
- `--center_lat` and `--center_lon` when using `--gauge_latlon` or `--inundation_extent`

## Outputs

- Discharge CSV: `time_seconds,discharge_m3s`
- Stage CSV: `time_seconds,stage_m,depth_m`
- Inundation CSV and `inundation_csi.json` for categorical extent metrics
- `<output_csv stem>_summary.json` with extraction diagnostics and summary statistics

## Procedure

Extract discharge through a cross-section:

```bash
python tools/parse_anuga_output.py \
    --sww_file ./output/anuga_sim.sww \
    --cross_section "-2500,0,2500,0" \
    --output_csv ./output/discharge.csv
```

Extract stage at a HYDAT gauge using the same center as `tools/run_anuga.py` and snap to the channel low point:

```bash
python tools/parse_anuga_output.py \
    --sww_file ./output/anuga_sim.sww \
    --gauge_latlon "49.20369,-121.77583" \
    --center_lat 49.230 \
    --center_lon -121.740 \
    --snap_to_channel_m 400 \
    --output_csv ./output/stage.csv
```

Compute inundation extent against an observed flood-mask GeoTIFF:

```bash
python tools/parse_anuga_output.py \
    --sww_file ./output/anuga_sim.sww \
    --inundation_extent \
    --center_lat 49.230 \
    --center_lon -121.740 \
    --obs_mask ./obs/flood_mask.tif \
    --depth_threshold 0.1 \
    --output_csv ./output/inundation.csv
```

## Verification

For stage extraction, inspect the summary diagnostics before scoring:

```bash
python - <<'PY'
import csv, json
rows = list(csv.DictReader(open("./output/stage.csv")))
summary = json.load(open("./output/stage_summary.json"))
assert rows, "no stage rows"
assert {"time_seconds", "stage_m", "depth_m"} <= set(rows[0]), rows[0].keys()
g = summary["gauge_extraction"]
assert g["wet_fraction"] >= 0.5, g
print(len(rows), g["used_vertex"], g["wet_fraction"])
PY
```

For discharge extraction, confirm the sign and magnitude are plausible for the cross-section orientation:

```bash
python - <<'PY'
import csv
rows = list(csv.DictReader(open("./output/discharge.csv")))
assert rows, "no discharge rows"
q = [float(r["discharge_m3s"]) for r in rows]
print(min(q), max(q))
PY
```

## Traps

- `dt_anuga_005` and `dt_anuga_006`: the SWW may be missing, fragmented, or unreadable. Remedy: inspect `run_summary.json` and merge parallel SWW fragments if needed.
- `dt_anuga_021`: `stage_m` is water-surface elevation, not flood depth. Remedy: use `depth_m` for water thickness.
- `dt_anuga_022`: a cross-section outside the wet mesh, parallel to flow, or with reversed endpoint order gives zero or wrong-signed discharge.
- `dt_anuga_024`: a gauge vertex on the bank can stay dry and emit a flat stage line. Remedy: use `--snap_to_channel_m` and require acceptable `wet_fraction`.
- `dt_anuga_025`: absolute stage scoring is invalid when the observation datum is arbitrary or incompatible with the DEM.

## Example

The HYDAT stage example from `SKILL.md` is:

```bash
python tools/parse_anuga_output.py --sww_file ./output/anuga_sim.sww \
    --gauge_latlon "49.20369,-121.77583" \
    --center_lat 49.230 --center_lon -121.740 \
    --snap_to_channel_m 400 --output_csv ./output/stage.csv
```

Read `./output/stage_summary.json` before comparing `stage_m` to HYDAT level observations.
