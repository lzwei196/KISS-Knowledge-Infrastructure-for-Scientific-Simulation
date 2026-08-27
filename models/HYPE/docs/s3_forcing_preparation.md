# s3_forcing_preparation

## Purpose

Convert CMFD or MSWX gridded forcing into HYPE daily forcing files. HYPE expects daily `Pobs.txt` and `Tobs.txt` in tab-separated format, with forcing station columns keyed to subbasins by `ForcKey.txt`.

## Inputs

- CMFD or MSWX forcing directory: `--forcing_dir`
- Subbasin shapefile from s1: `--subbasins`
- Start and end years: `--start_year`, `--end_year`
- Source flag: `--source cmfd` or `--source mswx`

## Outputs

- `forcingdir/Pobs.txt`: daily precipitation, mm/day
- `forcingdir/Tobs.txt`: daily temperature, deg C
- `forcingdir/ForcKey.txt`: subbasin-to-forcing mapping

## Procedure

Run the KI converter:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s3_forcing_preparation/convert_forcing_to_hype.py \
  --forcing_dir data/forcing/Data_forcing_03hr_010deg/ \
  --subbasins outputs/hype_run/subbasins/subbasins.shp \
  --output outputs/hype_run/forcingdir/ \
  --start_year 2005 \
  --end_year 2010 \
  --source cmfd
```

The tool sums eight 3-hour precipitation steps per day, averages temperature, converts CMFD precipitation from kg/m2/s when detected, and converts CMFD temperature from Kelvin to Celsius.

## Verification

- `Pobs.txt`, `Tobs.txt`, and `ForcKey.txt` exist in `forcingdir/`.
- File columns are tab-separated; `cat -A outputs/hype_run/forcingdir/Pobs.txt | head -3` should show `^I` separators.
- The first and last forcing dates cover the `bdate` to `edate` range that will be written to `info.txt`.
- Annual precipitation is physically plausible for the basin, usually about 400-1600 mm for most HydroCraft cases.

## Traps

- `dt_r04`: `Pobs.txt` or `Tobs.txt` does not span the full `info.txt` period, producing `ERROR read Pobs, date not equal`.
- `dt_u03`: CMFD precipitation remains in kg/m2/s and rounds to zero discharge unless multiplied by 10800 seconds per 3-hour step.
- `dt_u01` and `dt_c02`: 3-hour precipitation is averaged instead of summed, so HYPE receives one eighth of the intended precipitation.
- `dt_u02`: CMFD temperature is left in Kelvin, breaking snow and PET behavior.
- `dt_s07`: forcing files written with spaces rather than tabs can be misread as zero or missing values.

## Example

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s3_forcing_preparation/convert_forcing_to_hype.py \
  --forcing_dir data/forcing/Data_forcing_03hr_010deg/ \
  --subbasins outputs/hype_run/subbasins/subbasins.shp \
  --output outputs/hype_run/forcingdir/ \
  --start_year 1981 \
  --end_year 1990 \
  --source cmfd

head -2 outputs/hype_run/forcingdir/Pobs.txt
tail -1 outputs/hype_run/forcingdir/Pobs.txt
cat -A outputs/hype_run/forcingdir/Pobs.txt | head -3
```
