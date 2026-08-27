# S3 Reservoir Curve

## Purpose

Create the DLBreach `Upstream_Reservoir` storage relationship. DLBreach supports tabulated volume-elevation or area-elevation curves and three power-law forms; this KI exposes those methods through `tools/s3_reservoir_curve/create_reservoir_curve.py`.

## Inputs

- `--method 0` with `--vz_file` for elevation and volume pairs.
- `--method 1` with `--asz_file` for elevation and surface area pairs.
- `--method 2` with `--volume_m3`, `--area_m2`, and `--dam_height`.
- `--method 3` with `--volume_m3`, `--dam_height`, and optional `--exponent`.
- `--method 4` with `--area_m2`, `--dam_height`, and optional `--exponent`.

## Outputs

- JSON containing `reservoir_card`, `method`, `summary`, `validation_errors`, and `status`.
- A DLBreach `Upstream_Reservoir` card for S5 assembly.

## Procedure

Use measured reservoir data when available. For a power-law curve from known normal-pool volume, area, and dam height:

```bash
python3 tools/s3_reservoir_curve/create_reservoir_curve.py \
  --method 2 \
  --volume_m3 3900000000 \
  --area_m2 23000000 \
  --dam_height 93 \
  --output outputs/demo/reservoir.json
```

For rough screening only, the tool can estimate volume and area from height:

```bash
python3 tools/s3_reservoir_curve/create_reservoir_curve.py \
  --method 2 \
  --dam_height 30 \
  --estimate_from_height \
  --output outputs/demo/reservoir.json
```

See `docs/format_spec.yaml` for the reservoir card unit convention and `docs/REFERENCES.md` for model references.

## Verification

- `status` is `success`.
- `validation_errors` is empty.
- For tabulated methods, elevations are monotonically increasing and storage or area is non-decreasing.
- The output JSON contains exactly one `reservoir_card` suitable for S5.

## Traps

- `dt_009`: volumes must be m3 and areas must be m2. MCM or km2 values make the reservoir about 1,000,000 times too small.
- `dt_005`: after S5 assembly, do not insert blank lines or comments inside multiline `Upstream_Reservoir` card blocks.

## Example

```bash
cd KISSPATH_KI_ROOT/DLBreach/knowledge_infrastructure
python3 tools/s3_reservoir_curve/create_reservoir_curve.py \
  --method 3 \
  --volume_m3 50000000 \
  --dam_height 30 \
  --exponent 2.0 \
  --output outputs/example_case/reservoir.json
```

