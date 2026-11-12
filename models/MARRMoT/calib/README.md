# Bengbu 51080 case inputs (read only)

`tools/calib_run.py` copies these two files into `<workdir>/calib/` when the work
folder has no valid cache. It never writes here.

- `forcing.csv`: daily CMFD precipitation/temperature averaged over 9 cells in the
  Huai basin above Bengbu, with Oudin PET (built by `tools/convert_forcing.py`), 1979-01-01 to 1990-12-31.
- `obs_q.csv`: Bengbu (51080) daily discharge (server file `data/obs/BB/51080_bengbu.txt`, m3/s), converted
  to mm/d over 121,330 km2, same dates row by row.

- `params.json`: the calibrated GR4J (m_07) values x1-x4 for this case (validated NSE 0.7516).
  Read only; the pre-run check requires it. Calibration runs read their values from
  `$KDT_CALIB_PARAMS`, not from this file.

Calibration window 1981-1985, validation window 1986-1990, 1979-1980 spin-up.
Copied from the server KI on 2026-11-11; SHA-256 in `SHA256SUMS`.
