# S5 Update Control

## Purpose

Edit `APEXCONT.DAT` for the requested simulation period, spin-up period, print frequency, weather-read/generate mode, PET method, and optional groundwater/baseflow parameters.

## Inputs

- A workspace from S1 with `APEXCONT.DAT`
- `tools/s5_update_control.py`
- `--year1`, `--year2`
- Optional `--spinup-years`, `--ngn`, `--allow-generated-weather`, `--iet`, `--gws0`, `--rft0`, and `--rfp0`

## Outputs

- Canonical Fortran I4 fixed-width line 1 in `APEXCONT.DAT`
- Updated line 4 groundwater fields if `--gws0`, `--rft0`, or `--rfp0` is supplied

## Procedure

```bash
cd KISSPATH_KI_ROOT/APEX/knowledge_infrastructure
python tools/s1_setup_workspace.py /tmp/apex_ws
python tools/s5_update_control.py \
  --workspace /tmp/apex_ws \
  --year1 2010 --year2 2015 \
  --spinup-years 25 \
  --ngn 2345 \
  --iet 3
```

Run S2 before S5 when using real daily weather, so S5 can guard against an accidental `ngn=0` generated-weather run.

## Verification

```bash
python - <<'PY'
line = open("/tmp/apex_ws/APEXCONT.DAT").read().splitlines()[0]
fields = [int(line[i:i+4]) for i in range(0, 24, 4)]
print(fields[:6])  # NBYR, IYR, IMO, IDA, IPD, NGN
PY
```

For `year1=2010`, `year2=2015`, and `spinup-years=25`, the first fields should start with `31, 1985, 1, 1`.

## Traps

- `diagnostics/triplets.yaml:apexcont_free_format_nbyr` - APEX reads line 1 as fixed-width I4; free-format spacing can make `NBYR=6` parse as a different value.
- `diagnostics/triplets.yaml:apex0806_apexcont_split_field_shift` - parsing packed fixed-width fields with `split()` can shift later control flags.
- `diagnostics/triplets.yaml:apex0806_apexcont_freeformat_crash` - pristine free-format templates need split-format detection before canonical I4 rewriting.
- `diagnostics/triplets.yaml:ngn_weather_mismatch` - `NGN` determines which `*.DLY` variables are read versus generated.
- `diagnostics/triplets.yaml:spinup_low_yields` - non-template climates generally need 20-25 years of spin-up.

## Example

```bash
python tools/s5_update_control.py --workspace /tmp/apex_bengbu --year1 2010 --year2 2015 --spinup-years 25 --ngn 2345 --iet 3
head -1 /tmp/apex_bengbu/APEXCONT.DAT
```
