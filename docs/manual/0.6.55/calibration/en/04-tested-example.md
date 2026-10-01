# Tested example: SHAW reference recovery

This Windows benchmark exercises the real SHAW 3.03 native executable repeatedly through its KI wrapper and the bundled calibration engine. It asks whether optimization can recover a known parameter setting from the publisher's own output.

> **Scope:** the target is an official model reference, not measured field data. The result demonstrates parameter application, native execution, scoring and holdout handling. It must not be quoted as observational model skill.

## Reproducible setup

Use the five unchanged SHAW Trial inputs listed in the three-page quickstart and the publisher's temperature reference table from the [official SHAW 3.03 archive](https://www.ars.usda.gov/ARSUserFiles/20520500/SHAW/303/Shaw303.zip). The reference file is `Shaw303/Output/Trial/temp.out` inside that archive. Preserve the original files. The project adapter creates a separate candidate input set for each evaluation.

| Setting | Tested value |
|---|---|
| Parameter | `bulk_density_scale`, applied to all 11 soil nodes |
| Bounds | 0.8 to 1.5 |
| Deliberately perturbed baseline | 1.3 |
| Known reference setting | 1.0 |
| Method / seed / search budget | DDS / 20261002 / 60 requested optimizer evaluations |
| Training rows | 155 hourly rows × 11 nodes; 1986-12-04 13:00 to 1986-12-10 23:00 |
| Held-out rows | 145 hourly rows × 11 nodes; 1986-12-11 00:00 to 1986-12-17 00:00 |
| Metrics | NSE and temperature RMSE in °C; no Celsius PBIAS |

These bounds and the artificial baseline are a **software reference-recovery protocol**, not recommendations for estimating field soil density. Other Trial parameters and forcing remain fixed.

## Actual result

The fitted scale was **1.003065603**. Training NSE was **0.99998413** and RMSE **0.011098 °C**. Held-out NSE improved from **0.98713640** at the perturbed baseline to **0.99998794**. The configured held-out check passed, and the engine marked the result promotable within this benchmark.

The shared engine was pinned at revision `579162102f71f2fa4619b874a21bd219caaed25e`. The adapter was project-owned (`calibration/kis/SHAW/calibration.yaml` and `tools/calib_run.py`), not a newly claimed universal SHAW adapter. Full execution evidence was retained in the test project and `D:/GeoForge-Calibration-20261002/native-calibration-result.json` on the validation machine.

The source and frozen Windows engine produced the same fitted result. The test made 64 actual native calls, including the probe, baseline and holdout checks. A separate run at the known reference setting 1.0 reproduced the publisher’s temperature output byte for byte. All six optimizer backends also passed a synthetic interface test; those synthetic tests do not demonstrate scientific performance.

## Inspect the actual model output

![Real SHAW reference-recovery benchmark](../../images/en/08-calibration-benchmark.png)

The upper panel compares the publisher reference, the deliberately perturbed baseline and the fitted native run at 0.10 m soil depth. Shading marks the held-out period. The lower panel shows actual scored evaluations and the best training loss. These are model reference outputs, not field observations.

## Ask the AI for this benchmark

> Prepare a project-owned SHAW calibration adapter that runs the real native Trial for every evaluation. Use the official temperature output only as a reference-recovery target, not observations. Recover bulk_density_scale on all 11 nodes in [0.8, 1.5], with baseline 1.3, DDS seed 20261002 and budget 60. Train through 1986-12-10 23:00 and hold out 1986-12-11 00:00 through 1986-12-17 00:00. Report applied parameters, actual run records, NSE and RMSE for both splits and the uncalibrated baseline. Preserve original inputs and present a plan before execution.

For a scientific study, replace this reference-recovery target with suitable independent observations and justify a new protocol. Do not reuse these near-perfect reference scores as evidence for a real catchment or field site.
