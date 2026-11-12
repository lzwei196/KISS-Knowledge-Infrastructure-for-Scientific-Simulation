# MODFLOW6 case: groundwater station 360681210141 (Jiangxi), monthly water level 2019-2021

What `tools/calib_run.py` needs for this case, and where each file is:

| Need | File | Notes |
|---|---|---|
| Forward driver | `inputs/run_and_score.py` | The server keeps it in the model home (`<models>/MODFLOW6/run_and_score.py`); `calib_run.py` loads it from there (`RUNNER_PY`). Server paths are written as `KISSPATH_*` tokens; the desktop decides where it goes. |
| Observations | `inputs/yearbook.db` | Cut from the server yearbook catalog: table `地下水_月均水位`, same schema, only `station_code = 360681210141` (36 rows, 2019-01 to 2021-12). Gives exactly the same observations and identity record through `calib_run.load_obs()` as the full catalog (checked 2026-11-11). The file name must stay `yearbook.db` (the contract checks it). |
| Monthly CMFD precipitation | `../../calib/cmfd_monthly_360681210141.json` | 48 months 2018-2021. `calib_run.py` reads it read only from the KI when the work folder has no cache. |
| Contract | `../../calibration.yaml` | Station identity, reference surface, envelope and windows. |
| MODFLOW 6 binary | not shipped | Server used mf6 6.6.3. |

Windows: calibration 2019-2020 (24 months), validation 2021 (12 months).

Default-parameter results on the server (2026-11-11, mf6 6.6.3; not a calibrated result):
NSE all = -0.2080, calibration = -0.1506, validation = -0.3368; PBIAS all = 3.26 %.

Hashes in `SHA256SUMS`.
