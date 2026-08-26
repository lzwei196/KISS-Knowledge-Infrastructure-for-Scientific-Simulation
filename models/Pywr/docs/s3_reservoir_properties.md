# S3 Reservoir Properties

## Purpose
Convert one selected dam into the reservoir storage properties that Pywr expects: capacity in `m3`, dead storage, initial volume, location, and an area-volume curve. This stage is implemented by `../tools/s3_reservoir_properties/build_reservoir_properties.py`.

## Inputs
- Dam JSON from S2, such as `/tmp/pywr_dams.json`.
- Or manual dam fields: `--name`, `--capacity_mcm`, `--dam_height_m`, `--lat`, `--lon`.
- Optional `--area_volume_csv` with columns `volume_m3,area_m2`.
- Tool: `../tools/s3_reservoir_properties/build_reservoir_properties.py`

## Outputs
- Reservoir JSON for S5 and S7.
- Important output fields include `storage.max_volume_m3`, `storage.max_volume_mcm`, `storage.min_volume_m3`, `storage.initial_volume_m3`, dam coordinates, and geometry metadata.

## Procedure
Build properties for the largest dam from S2:

```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"

"$PYWR_PYTHON" "$KI/tools/s3_reservoir_properties/build_reservoir_properties.py" \
  --dam_json /tmp/pywr_dams.json \
  --dam_index 0 \
  --dead_storage_frac 0.10 \
  --initial_frac 0.50 \
  --output /tmp/pywr_reservoir.json
```

Manual mode:

```bash
"$PYWR_PYTHON" "$KI/tools/s3_reservoir_properties/build_reservoir_properties.py" \
  --name Meishan \
  --capacity_mcm 2275 \
  --dam_height_m 88 \
  --lat 31.43 \
  --lon 115.92 \
  --output /tmp/pywr_reservoir.json
```

## Verification
- Check `storage.max_volume_m3` equals `storage.max_volume_mcm * 1000000`.
- Check `storage.min_volume_m3 < storage.initial_volume_m3 < storage.max_volume_m3`.
- Check the selected dam coordinates match the dam that will be used by S4 and S8 CaMa injection.
- If a custom area-volume table is used, confirm its columns are `volume_m3` and `area_m2`.

## Traps
- `dt_pywr_014`: using MCM directly as Pywr volume makes the reservoir one million times too small.
- A `--dam_index` outside the S2 result range exits with an error; inspect `dams_found` in `/tmp/pywr_dams.json`.
- If S2 returned `NO_DAMS`, use manual mode or skip the Pywr reservoir workflow for that basin.

## Example
```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"
"$PYWR_PYTHON" "$KI/tools/s3_reservoir_properties/build_reservoir_properties.py" \
  --dam_json /tmp/pywr_dams.json \
  --dam_index 0 \
  --output /tmp/pywr_reservoir.json
```
