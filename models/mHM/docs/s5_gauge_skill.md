# s5_gauge Skill

## Purpose

Convert observed discharge to the text format mHM reads for gauge evaluation.

## Inputs

- Observed discharge file from HydroCraft, GRDC, HYDAT, or another source supported by `tools/s5_gauge/prepare_mhm_gauge.py`.
- Gauge id matching `idgauges.asc` from s2 and `evaluation_gauges` in s6.
- Gauge name.
- Start and end years for the output file.

## Outputs

- `<run_dir>/input/gauge/<gauge_id>.txt` or a zero-padded equivalent created by the tool.
- A five-line mHM header followed by daily rows with `YYYY MM DD HH MM Q`.

## Procedure

Convert observed discharge:

```bash
python tools/s5_gauge/prepare_mhm_gauge.py \
  --obs_file data/gauge/wangjiaba_q.csv \
  --gauge_id 51030 \
  --gauge_name Wangjiaba \
  --output_dir runs/wangjiaba/input/gauge \
  --start_year 1980 \
  --end_year 1990
```

Use the same gauge id in `tools/s2_morphology/generate_gauge_grid.py` and in `tools/s6_namelist/generate_mhm_namelists.py`.

## Verification

Check for the five header lines and six data columns:

```bash
ls runs/wangjiaba/input/gauge
sed -n '1,8p' runs/wangjiaba/input/gauge/51030.txt
awk 'NR>5 { if (NF != 6) { print "bad line", NR, NF; exit 1 } } END { print "gauge columns OK" }' \
  runs/wangjiaba/input/gauge/51030.txt
```

If the tool zero-pads the filename, pass that filename to s6 with `--gauge_filename`.

## Traps

- `dt_s13` in `../diagnostics/triplets.yaml`: four-column `YYYY MM DD Q` files make mHM parse day-of-month values as discharge.
- `dt_r04`: gauge id in `mhm.nml` must match a valid cell in `idgauges.asc`.
- `dt_v002`: a gauge can land on an L11 cell with no upstream drainage; if gauge discharge is zero but routed fields are nonzero, relocate using routed-output evidence.

## Example

For a Wangjiaba run using gauge id `51030`, create `idgauges.asc` in s2 with `--gauge_id 51030`, prepare the text file here, and pass `--gauge_id 51030 --gauge_filename 51030.txt` to s6.
