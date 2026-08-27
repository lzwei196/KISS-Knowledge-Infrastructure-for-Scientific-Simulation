# s6_namelist Skill

## Purpose

Assemble the four Fortran namelists mHM needs, including grid settings, process switches, paths, gauge metadata, evaluation period, optional optimization settings, and the parameter file.

## Inputs

- `config.json` and `domain_info.json`.
- Gauge id and gauge filename from s5.
- Warmup length and evaluation years.
- Optional calibration flags: optimizer method, objective function, and iterations.
- Optional calibrated parameter namelist from s9 or s10.

## Outputs

- mHM namelist files in the run directory, including `mhm.nml`.
- References to `mhm_parameter.nml`, meteo directories, morphology directories, gauge file, and `input/latlon/latlon_1.nc`.

## Procedure

Generate forward-run namelists:

```bash
python tools/s6_namelist/generate_mhm_namelists.py \
  --config runs/wangjiaba/config.json \
  --domain_info runs/wangjiaba/domain_info.json \
  --gauge_id 51030 \
  --gauge_filename 51030.txt \
  --warmup_days 365 \
  --eval_start_year 1981 \
  --eval_end_year 1990
```

For a calibration window, enable optimization and keep discharge objectives to `1` or `9` unless optional data are deliberately configured:

```bash
python tools/s6_namelist/generate_mhm_namelists.py \
  --config runs/wangjiaba/config.json \
  --domain_info runs/wangjiaba/domain_info.json \
  --gauge_id 51030 \
  --gauge_filename 51030.txt \
  --warmup_days 365 \
  --eval_start_year 1981 \
  --eval_end_year 1985 \
  --optimize \
  --opti_method 1 \
  --opti_function 1 \
  --n_iterations 2000
```

For a forward validation using calibrated parameters:

```bash
python tools/s6_namelist/generate_mhm_namelists.py \
  --config runs/wangjiaba/config.json \
  --domain_info runs/wangjiaba/domain_info.json \
  --gauge_id 51030 \
  --gauge_filename 51030.txt \
  --warmup_days 365 \
  --eval_start_year 1981 \
  --eval_end_year 1990 \
  --param_nml runs/wangjiaba/FinalParam.nml
```

## Verification

Inspect the load-bearing settings:

```bash
test -f runs/wangjiaba/mhm.nml
rg -n "iFlag_cordinate_sys|resolution_Hydrology|resolution_Routing|processCase|eval_Per|opti_function|nIterations" \
  runs/wangjiaba/mhm.nml
```

For EPSG:4326 grids, `iFlag_cordinate_sys` must be `1` and hydrology/routing resolutions must be in degrees, matching `domain_info.json`.

## Traps

- `dt_v001` in `../diagnostics/triplets.yaml`: `iFlag_cordinate_sys=0` on geographic grids collapses routed discharge to near zero.
- `dt_s07`: routing resolution mismatch shifts hydrograph timing.
- `dt_s02`: `processCase(5)` must match available PET/temperature/radiation forcing.
- `dt_r14`, `dt_r15`, and `dt_r16`: DDS needs at least six iterations, discharge objectives are `1` or `9`, and the calibration wrapper must not stamp defaults back into `mhm.nml`.

## Example

For a Wangjiaba calibration, use 1980 as spin-up and 1981-1985 as `eval_Per` with `--opti_function 1` or `--opti_function 9`, then regenerate forward namelists over 1981-1990 with the calibrated parameter file.
