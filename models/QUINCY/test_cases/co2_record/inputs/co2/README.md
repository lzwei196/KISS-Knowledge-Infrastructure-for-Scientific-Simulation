# Atmospheric CO2 record for the QUINCY real engine

Copied 2026-10-07 from `models/LPJ_GUESS/inputs/co2/` (downloaded there on 2026-10-07; see that README for the URLs).

- `co2_1901_2014.txt` — annual mean CO2 [ppm], Law Dome ice core 1901-1958 (Etheridge et al. 1996;
  MacFarling Meure et al. 2006) and NOAA Mauna Loa 1959-2014.
- `co2_annmean_mlo.txt` — NOAA GML Mauna Loa annual means (used for years after 2014).
- `law2006.txt` — raw Law Dome file (kept for provenance).

`tools/build_quincy_climate.py` reads the two annual files to fill the CO2 column of climate.dat
(and to fill gaps in a FLUXNET site's own CO2_F_MDS record).
