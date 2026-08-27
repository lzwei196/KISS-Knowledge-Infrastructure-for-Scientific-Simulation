# s4_forcing Skill

## Purpose

Convert gridded meteorological forcing into the NetCDF layout and units mHM reads: `pre`, `tavg`, and, for PET method 0, `pet`.

## Inputs

- `config.json` and `domain_info.json`.
- Forcing root passed as `--forcing_dir`.
- Forcing dataset selection from `config.json`, normally CMFD or MSWX.
- PET method code passed to `tools/s4_forcing/convert_forcing_to_mhm.py`.

## Outputs

- `input/meteo/pre/pre.nc`
- `input/meteo/tavg/tavg.nc`
- `input/meteo/pet/pet.nc` when `--pet_method 0`
- mHM-style `header.txt` files in the meteo variable directories.

## Procedure

Use the KI converter rather than hand-written unit arithmetic:

```bash
python tools/s4_forcing/convert_forcing_to_mhm.py \
  --config runs/wangjiaba/config.json \
  --domain_info runs/wangjiaba/domain_info.json \
  --forcing_dir KISSPATH_DATA/CMFD \
  --pet_method 0
```

The converter is expected to load forcing through HydroCraft's normalized forcing path described in `SKILL.md`: `ki_tools_common.load_forcing.load_daily_forcing`.

## Verification

Check files, variable names, and rough physical ranges:

```bash
test -f runs/wangjiaba/input/meteo/pre/pre.nc
test -f runs/wangjiaba/input/meteo/tavg/tavg.nc
test -f runs/wangjiaba/input/meteo/pet/pet.nc
ncdump -h runs/wangjiaba/input/meteo/pre/pre.nc | rg "pre|time|yc|xc"
ncdump -h runs/wangjiaba/input/meteo/tavg/tavg.nc | rg "tavg|time|yc|xc"
ncdump -h runs/wangjiaba/input/meteo/pet/pet.nc | rg "pet|time|yc|xc"
```

For CMFD daily precipitation, basin-mean annual precipitation should be physically plausible, not about one eighth of climatology.

## Traps

- `dt_r03` in `../diagnostics/triplets.yaml`: wrong meteo paths, variable names, or time range cause missing-forcing crashes.
- `dt_r06`, `dt_s08`, and `dt_s10`: precipitation and temperature units are silent error sources; CMFD daily precipitation needs daily mean-rate handling, not the 3-hour factor.
- `dt_s02` and `dt_s11`: Hargreaves requires real tmin/tmax. With daily mean temperature only, use `--pet_method 0` and Oudin PET.
- `dt_r12`: forcing grid headers must align with the square-L0-derived L1 grid.

## Example

The Wangjiaba reference in `SKILL.md` uses CMFD daily forcing and PET method 0. That writes an Oudin PET file for mHM to read with `processCase(5)=0`.
