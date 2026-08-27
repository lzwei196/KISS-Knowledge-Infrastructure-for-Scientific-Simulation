# S3 Build Soil

## Purpose

Replace the copied template soil profile values with HWSD-derived texture, bulk density, pH, and organic carbon for the target point while preserving the APEX fixed-format `*.SOL` skeleton.

## Inputs

- A workspace from S1
- `tools/s3_build_soil.py`
- Latitude and longitude
- `ki_tools_common.soil_utils.lookup_hwsd`
- The soil list file, normally `SOILCOM.DAT` for APEX0806, and the listed `*.SOL` files such as `Heiden.SOL` and `HoustonB.SOL`

## Outputs

- Updated `*.SOL` files. By default, `build_soil(..., all_soils=True)` rewrites every existing soil referenced by `SOILCOM.DAT`, resolving case-insensitive filename mismatches and skipping dangling list entries with a warning.

## Procedure

```bash
cd KISSPATH_KI_ROOT/APEX/knowledge_infrastructure
python tools/s1_setup_workspace.py /tmp/apex_ws
python tools/s3_build_soil.py --workspace /tmp/apex_ws --lat 32.94 --lon 117.36
```

To intentionally rewrite just one file:

```bash
python tools/s3_build_soil.py --workspace /tmp/apex_ws --lat 32.94 --lon 117.36 --sol-name Heiden.SOL
```

## Verification

```bash
python - <<'PY'
from pathlib import Path
for p in Path("/tmp/apex_ws").glob("*.SOL"):
    lines = p.read_text().splitlines()
    if len(lines) >= 13:
        print(p.name, "BD:", lines[4], "SAND:", lines[7], "SILT:", lines[8])
PY
```

`tools/s3_build_soil.py` validates that the written sand and silt rows are present and remain inside `[0, 100]`.

## Traps

- `diagnostics/triplets.yaml:hwsd_lookup_failed` - the HWSD lookup can fail because of missing raster data, a coordinate outside the raster bounds, or missing `rasterio`.
- `diagnostics/triplets.yaml:apex0806_only_first_soil_rewritten` - the Riesel template uses multiple soil IDs; rewriting only the first listed soil leaves other subareas on Texas template soils.
- `diagnostics/triplets.yaml:file_missing_uppercase` - `SOILCOM.DAT` and on-disk `*.SOL` filenames must match the case that APEX will open.

## Example

```bash
python tools/s3_build_soil.py --workspace /tmp/apex_bengbu --lat 32.94 --lon 117.36
grep -n "" /tmp/apex_bengbu/Heiden.SOL | sed -n '5,13p'
```
