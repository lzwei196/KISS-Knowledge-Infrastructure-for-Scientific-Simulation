# s1_data_import

## Purpose

Load a sequence of radar precipitation frames into the pySTEPS-ready array contract used by this KI. This stage is implemented by `tools/s1_data_import/import_radar_data.py` and is responsible for format-specific import, basic metadata capture, NaN handling, and dBZ-to-mm/h conversion before any motion estimation or nowcast call.

## Inputs

- A directory of radar files supplied with `--data_dir`.
- `--format`: one of `opera_hdf5`, `knmi_hdf5`, `mch_gif`, `bom_rf3`, `geotiff`, or `netcdf`.
- `--n_frames`: at least 2 frames; 4 is the KI default for the synthetic diagnostic workflow described in `SKILL.md`.
- `--timestep`: frame interval in minutes, usually 5, 10, or 15.
- Optional `--no-convert_to_mmh` only when the caller intentionally keeps dBZ input outside the normal KI path.

## Outputs

- `radar_frames.npz` with `data` shaped `(n_frames, ny, nx)`.
- `metadata.json` with unit, transform, projection, grid extent, pixel size, and `accutime`.
- `import_summary.json` with frame count, unit, shape, and value-range summary.

## Procedure

Run the KI preflight first:

```bash
cd KISSPATH_KI_ROOT/pySTEPS/knowledge_infrastructure
python3 preflight_check.py
```

Inspect the stage CLI:

```bash
python3 tools/s1_data_import/import_radar_data.py --help
```

For real radar data, run the importer and write an explicit stage directory:

```bash
python3 tools/s1_data_import/import_radar_data.py \
  --data_dir /path/to/radar_frames \
  --format geotiff \
  --n_frames 4 \
  --timestep 5 \
  --output_dir /tmp/pysteps_case/s1_data_import
```

For native pySTEPS-supported archives, use the matching `--format` value rather than a generic reader. For NetCDF, the tool searches precipitation-like variable names such as `precip`, `rain`, `rr`, `pr`, or `qpe`.

## Verification

Check that the stage wrote both data and metadata:

```bash
python3 - <<'PY'
import json, numpy as np
from pathlib import Path
d = Path('/tmp/pysteps_case/s1_data_import')
R = np.load(d / 'radar_frames.npz')['data']
meta = json.loads((d / 'metadata.json').read_text())
print(R.shape, meta.get('unit'), meta.get('accutime'))
assert R.ndim == 3 and R.shape[0] >= 2
assert meta.get('unit') != 'dBZ'
PY
```

The offline KI-level validation path is `diagnostics/run_synthetic_advection.py`; it builds synthetic mm/h arrays internally instead of using this importer because no real radar archive is mounted in the KI.

## Traps

- `dt_pysteps_001`: inflated values or chaotic vectors usually mean dBZ reflectivity reached later stages as if it were mm/h. Use this stage's default conversion and inspect `metadata.json`.
- `dt_pysteps_002`: near-zero output can come from applying a log transform twice. Check `metadata['transform']` before transforming imported mm/h data again.
- `dt_pysteps_004`: wrong importer for HDF5/radar source. Match `--format` to the provider-specific structure.
- `dt_pysteps_006`: GeoTIFF nodata or extra bands can corrupt optical flow. This tool reads band 1 and replaces nodata with NaN before filling.
- `dt_pysteps_014`: NaNs spread through semi-Lagrangian advection and FFT cascade steps. This stage reports NaN fraction and fills missing values with 0.0.

## Example

```bash
cd KISSPATH_KI_ROOT/pySTEPS/knowledge_infrastructure
python3 tools/s1_data_import/import_radar_data.py \
  --data_dir /data/radar/example_geotiff \
  --format geotiff \
  --n_frames 4 \
  --timestep 5 \
  --output_dir /tmp/pysteps_case/s1_data_import
```

Expected next-stage input: `/tmp/pysteps_case/s1_data_import/radar_frames.npz` plus `/tmp/pysteps_case/s1_data_import/metadata.json`.
