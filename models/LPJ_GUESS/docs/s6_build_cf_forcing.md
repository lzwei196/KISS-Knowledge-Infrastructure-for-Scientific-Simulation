# Stage 6 (real engine): build CF NetCDF forcing

**Purpose.** Make the daily NetCDF files LPJ-GUESS reads with `-input cf`.

**Inputs.** Site label, lat, lon, ≥30-year period, source (`nasa_power` | `cmfd` | `mswx`).

**Outputs.** `<out>/temp.nc prec.nc insol.nc min_temp.nc max_temp.nc relhum.nc wind.nc`,
`gridlist_cf.txt` (`0 0 <site>`), `forcing_meta.json` (paths + summary).

**Procedure.**
```bash
python tools/build_lpjguess_cf_forcing.py --site DE-Tha --lat 50.9624 --lon 13.5652 \
  --start_year 1984 --end_year 2014 --source nasa_power --out_dir forcing/
```
Exit 0 ok, 2 validation failed (period <30 yr, implausible values), 3 loader failed.

**Verification.** JSON line `mean_temp_c`, `annual_precip_mm`, `mean_insol_wm2`; `ncdump -h`
shows `units = "K"`, `"kg m-2 s-1"`, `"W m-2"`, `"1"` and `calendar = "standard"`.

**Traps.** dt_lpjguess_021 (30 years), dt_lpjguess_023 (literal units), dt_lpjguess_024
(gridlist = indices), dt_lpjguess_029 (POWER shortwave from 1984).

**Example.** DE-Tha 1984-2014 (11323 days): 8.11 °C, 723 mm/yr, 118 W m-2, RH 0.80.
Output: `KISSPATH_OUTPUTS/lpjguess_detha_real_engine/forcing/`.
