# Stage 7 (real engine): build the annual CO2 file

**Purpose.** The 4.1.1 release ships no CO2 file; the engine needs one line per year.

**Inputs.** `models/LPJ_GUESS/inputs/co2/law2006.txt` (Law Dome spline, NOAA NCEI) and
`co2_annmean_mlo.txt` (NOAA GML Mauna Loa, via ftp://aftp.cmdl.noaa.gov — the https host
failed with an SSL error from this server). SHA256SUMS + README in the same folder.

**Outputs.** `<year> <ppm>` text file.

**Procedure.**
```bash
python tools/build_lpjguess_co2_file.py --law_dome law2006.txt --mauna_loa co2_annmean_mlo.txt \
  --start_year 1901 --end_year 2014 --out co2_1901_2014.txt
```
Law Dome before 1959, Mauna Loa from 1959. Exit 2 on any missing year or value outside 250-500 ppm.

**Verification.** JSON: years [1901, 2014], 296.2 → 398.81 ppm, splice offset 0.28 ppm at 1959.

**Traps.** dt_lpjguess_022. Years before the first line get the first value. CO2 is read by
calendar year and the spin-up calendar starts nyear_spinup years before the first forcing year,
so for DE-Tha (1984 start, 500 years) 1484-1900 run at 296.2 ppm and 1901-1983 follow the real
record. The file must reach the last forcing year.
