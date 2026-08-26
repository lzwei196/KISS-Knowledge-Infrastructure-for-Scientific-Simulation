# s7_execution

## Purpose

Write `info.txt`, run the real HYPE v5.35.0 binary, and verify completion from logs and result files. This KI requires the real model binary; do not replace HYPE with a simplified Python calculation.

## Inputs

- `modelfiles/GeoClass.txt` from s2
- `forcingdir/Pobs.txt`, `Tobs.txt`, and `ForcKey.txt` from s3
- `modelfiles/GeoData.txt` from s4
- `modelfiles/par.txt` from s5
- Optional `LakeData.txt`, `DamData.txt`, `CropData.txt`, `Qobs.txt`, and calibration files
- Start/end dates, warmup years, PET model, and substance flags

## Outputs

- `info.txt`
- HYPE logs in `logdir/` or, for early failures, the run directory
- `resultdir/timeCOUT.txt`, `timeROUT.txt`, `timeSNOW.txt`, `timeEVAP.txt`, `timeCPRC.txt`, and requested map/time outputs

## Procedure

Run KI preflight from the KI root:

```bash
cd KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure
python preflight_check.py
```

Create `info.txt`:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s7_execution/configure_info.py \
  --start 2005-01-01 \
  --end 2010-12-31 \
  --warmup_years 1 \
  --modeldir ./modelfiles/ \
  --forcingdir ./forcingdir/ \
  --resultdir ./resultdir/ \
  --logdir ./logdir/ \
  --output outputs/hype_run/info.txt \
  --petmodel 1 \
  --substances none
```

Run HYPE through the wrapper:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s7_execution/run_hype.py \
  --hype_binary KISSPATH_BINARIES/hype/hype \
  --run_dir outputs/hype_run/ \
  --timeout 3600
```

## Verification

- `preflight_check.py` reports the HYPE binary and required KI files are available.
- `run_hype.py` exits with code 0.
- `resultdir/timeCOUT.txt` exists and has the expected date range after warmup/output start.
- If discharge observations are available, `timeROUT.txt` is present and can be parsed by s8.
- If the run fails, inspect `hyss_*.log` in both `logdir/` and the run directory.

## Traps

- `dt_r01`: directory arguments must end with `/`; otherwise HYPE concatenates paths like `mydirinfo.txt`.
- `dt_r06`: `STOP 1` may write `hyss_*.log` in the info directory instead of `logdir/`.
- `dt_s05`: `ForcKey.txt` SUBIDs do not match `GeoData.txt`, so some subbasins receive no precipitation.
- `dt_s09`: `substance N P` is set but nutrient parameters were not added to `par.txt`.

## Example

```bash
cd KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure
python preflight_check.py

python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s7_execution/configure_info.py \
  --start 1981-01-01 \
  --end 1990-12-31 \
  --warmup_years 1 \
  --modeldir ./modelfiles/ \
  --forcingdir ./forcingdir/ \
  --resultdir ./resultdir/ \
  --logdir ./logdir/ \
  --output outputs/hype_run/info.txt \
  --petmodel 1 \
  --substances none

python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s7_execution/run_hype.py \
  --run_dir outputs/hype_run/ \
  --hype_binary KISSPATH_BINARIES/hype/hype \
  --timeout 3600
```
