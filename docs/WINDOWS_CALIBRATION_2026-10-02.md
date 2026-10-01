# Windows calibration verification — 2026-10-02

**Acceptance passed in the packaged GeoForge Desktop 0.6.55 candidate:** real SHAW reference recovery, all six optimization backends, normal DeepSeek planning, browser review approval, native calibration, fitted plotting and signed-receipt verification. The actual project is `COMPLETED`, with `science_complete=true`, `receipts_verified=true` and validation `passed`. Public installer provenance is recorded separately by the release process.

The test uses the shared calibration framework pinned at `579162102f71f2fa4619b874a21bd219caaed25e`. Its vendored source remains unchanged. Case-specific files are in a project-owned adapter; no curated SHAW equations, original Trial inputs, publisher reference outputs or installed model executable were changed for this calibration.

## What was actually calibrated

The scientific executable is the genuine Windows SHAW 3.03 build tested on October 1, SHA-256 `c3845f35b371c23d807f55f8f5dd2fef04fd5202ace78b33cfe4563ad98d4195`. The five Trial input files and published `temp.out` come from the [USDA-ARS SHAW 3.03 distribution](https://www.ars.usda.gov/ARSUserFiles/20520500/SHAW/303/Shaw303.zip). The archived provenance includes download URL, original archive members and individual file hashes.

This is a **publisher model-reference recovery benchmark**, not a calibration against independent field observations. A multiplier is applied to the 11 original soil bulk densities, with bounds **0.8–1.5** and a deliberately perturbed starting/default value **1.3**. The known reference multiplier is **1.0**. Each candidate is written to its own copy of `Trial.30.sit`, read back, and run through the real SHAW KI wrapper and native executable. The adapter checks the complete 301-row, 11-node temperature profile and exact timestamps before scoring.

The objective is pooled profile NSE over all 11 depths and the chosen time window. Pearson correlation and RMSE in °C are also saved. This pooled metric includes variation across depths as well as time; it is not a claim about independent station skill. Percentage bias is deliberately omitted because Celsius has an arbitrary zero. The initial profile row is excluded from fitting and validation.

| Window | Period | Hourly rows | Temperature values |
|---|---|---:|---:|
| Calibration | 1986-12-04 13:00 through 1986-12-10 23:00 | 155 | 1,705 |
| Holdout | 1986-12-11 00:00 through 1986-12-17 00:00 | 145 | 1,595 |

DDS, seed `20261002`, requested budget 60, recovered **1.003065602989716**, a **0.30656%** difference from the known multiplier. There were 60 optimizer evaluations and 64 actual native invocations, including commissioning/probe and holdout/baseline work. The source-host run took about 22 seconds; the provisional frozen-worker run took about 30 seconds. The final approved Desktop calibration receipt records **20.564 seconds**. All three reproduced the fitted parameter and reported metrics exactly.

| Metric | Default calibration | Fitted calibration | Default holdout | Fitted holdout |
|---|---:|---:|---:|---:|
| NSE | 0.99555921 | 0.99998413 | 0.98713640 | 0.99998794 |
| RMSE, °C | 0.18565885 | 0.01109807 | 0.34699787 | 0.01062321 |
| Pearson r | 0.99873896 | 0.99999219 | 0.99517947 | 0.99999402 |

An independent audit reread the native files and recomputed these metrics. A separate native replay at multiplier **1.0** reproduced the publisher's temperature output **byte for byte**, SHA-256 `c8051a3e2f1f7ad93667e7541266c4a5083937be7b212629cc7abb41eb21fc05`. The engine reports `completed`, `holdout_validated=true`, `promotable=true` for this benchmark. That verdict applies to reference recovery only and does not establish suitability for a real site or authorize promotion into the curated KI.

## Defects found and repaired

1. **Frozen readiness did not prove the SPOTPY result writer was usable.** The original bundle imported DDS/SCE-UA/DREAM successfully but the first DDS run failed with `AttributeError: {} is not a member of spotpy.database`. SPOTPY dynamically discovers `spotpy.database.ram`. The packaging specification now includes it, and host readiness checks both its import and discovery. The failure is preserved in `host-behaviors.json`; the RAM-fixed provisional bundle completes the real SHAW calibration.
2. **Calibration approval did not bind the actual project adapter.** The API previously called the generic step guard with a null tool path, while the runtime replaced the KI runner with the project-owned runner. The typed calibration step now binds the exact project runner, complete contract digest, algorithm, requested budget, seed, observation shapes, determining metric and case identity. The contract's parameter bounds are part of the reviewed bytes. The host copies the checked bytes into an immutable per-run runtime and archives the adapter with each run. Changed bytes or invocation require review again. The CLI now requires an approved plan step and uses the same authorization and receipt path. A two-run regression proves later calibration cannot overwrite the runtime bytes covered by an earlier receipt.
3. **Project adapters could not be prepared in the normal planning phase.** A bounded `write_calibration_adapter` operation prepares only the selected KI's project `calibration.yaml` and `tools/calib_run.py`. It checks syntax, bounds and the runner entry point, and executes nothing. Arbitrary project-file writes remain unavailable during planning. The adapter is approved before execution.
4. **Calibration results need their own receipt validation.** Configuration files and log numbers cannot prove a fit. Typed receipt validation requires the approved binding, completed optimization, finite fitted parameters/losses, actual evaluation count and training metrics. A completed search without an explicitly passing independent holdout is retained with a warning and cannot establish scientific completion. Raw run files remain hash-covered by the receipt.
5. **Per-evaluation console windows were reproduced in the frozen worker.** The native adapter reported a nonzero Windows console handle in the provisional windowed executable, whereas the hidden source worker reported zero. A scoped host-worker subprocess policy now applies `CREATE_NO_WINDOW` to framework evaluation launches, without changing the pinned framework. In the final packaged Desktop run, **all 64 adapter processes reported `GetConsoleWindow()==0`**, with all native wrapper exits zero.

## Other meaningful checks

- Wrong case identity returns `runner_wrong_case` before optimization.
- A missing real SHAW executable returns `failed_no_finite_solution`; ten unsuccessful optimizer attempts are not reported as a successful calibration.
- Stopping a 1,000-budget native run after two completed evaluations returns `stopped`, `promotable=false`, in approximately 1.08 seconds. The entire run tree had no late writes during the following four seconds. The canceled run and earlier successful run remain in project history.
- The host focused suite passes **79 tests, 1 skipped**, covering binding, bounded preparation, snapshot consistency, invalid result rejection, worker cancellation/error handling and frozen-entry behavior. The final full suite passes **1,727 Desktop tests, 35 skipped, 337 subtests**, plus **371 shared tests, 7 skipped**; 363 Python source hashes remained stable through that checkpoint.
- All six backends completed an explicitly synthetic numerical fixture in source, the RAM-fixed provisional bundle and the final acceptance bundle. This exercises optimization and packaging, not a second scientific model.

| Backend | Requested budget | Actual optimizer evaluations |
|---|---:|---:|
| DDS | 80 | 80 |
| SCE-UA | 80 | 151 |
| DREAM | 80 | 182 |
| NSGA-II | 80 | 80 |
| NSGA-III | 80 | 80 |
| MOEA/D | 80 | 91 |

The pinned samplers may initialize populations or finish batches beyond the requested optimizer budget. The interface and guide therefore call it a **requested optimizer budget**, not a hard limit on native-model launches. Commissioning and holdout runs are additional. DREAM's short synthetic smoke is not a converged posterior or uncertainty assessment.

## Verified workflow and evidence

Prepare the real model, case data and independent holdout. In planning, prepare the selected KI's project adapter. Submit a `kind=calibrate` step whose `tool` is the absolute project adapter path and whose `calibration` object specifies `obs_shape_by_var`, `algorithm`, `budget`, `seed` and `determining_metric`. The host resolves defaults and adds the contract/runner hashes before presenting the review. After approval, call `run_calibration` with the approved `plan_step_id` and the exact reviewed settings. A changed adapter or scientific protocol requires another review.

Reports, worker requests, saved adapter bytes, optimizer cache, native evaluation files and logs persist under `calibration/runs/<run-id>/`. The framework is shared; the adapter is project-owned. A completed search and a passing holdout are separate facts.

The actual final project, session `77693a6010fc`, used DeepSeek to prepare the supplied adapter through `write_calibration_adapter` and submit a typed plan. Independent inspection confirmed the runner was byte-identical and the parsed contract equal to the tested benchmark. The user-authorized test was approved through the real Chrome review card. Both English and Chinese cards displayed algorithm, requested budget, seed, metric, parameter bounds/defaults, observation shapes, case and expandable contract/runner hashes.

Run `20261002-014732-b685c41f` completed the native fit and the approved plotter produced the fitted run's profile figure. DeepSeek initially supplied an unsupported plot argument, `--reference-dir`; that call failed with exit 2 and no outputs. It immediately retried with supported arguments and succeeded. The host retains the failed attempt as one superseded failure: the final audit contains three signed attempts, with **1,204 hashed calibration outputs**, zero outputs from the failed plot attempt, and one successful PNG. All three receipt HMACs and their current input/output hashes verify; the approval remains current. There are no missing or stale steps, rejected receipts or unreceipted artifacts. No receipt, scientific output or approval state was edited manually.

The independent final audit recomputed default/fitted calibration and holdout metrics from the actual native output tables, verified the six original uploaded files remained unchanged, verified approved/runtime/archived adapter hashes, and checked that the plot used `train_metrics.__kdt__.native_run` rather than the final baseline evaluation directory. The figure was visually inspected: actual nonuniform depths, dates and physical units are readable.

Local evidence root: `D:/GeoForge-Calibration-20261002/`.

- `case-provenance.json`, original `calibration/cases/shaw-trial/upstream-provenance.json`: official source and immutable input/reference hashes.
- `native-calibration-result.json`, `native-independent-audit.json`, `shaw-calibration-comparison.png`: source-host real model, independent calculations and comparison plot.
- `host-behaviors.json`: original frozen failure, wrong-case rejection, missing-native failure, real cancellation and persisted history.
- `source-backend-smoke.json`, `frozen-probe-backends.json`: six actual synthetic backend runs and their true evaluation counts.
- `frozen-probe-native.json`: RAM-fixed provisional bundle, genuine DDS recovery, and the console handle that reproduced the remaining window defect.
- `calibration-host-tests.xml`: focused host test results.
- `final-desktop/preapproval-adapter-audit.json`: exact source/contract comparison before approval.
- `final-desktop/frozen-six-backends.json`: all six backends using the final packaged worker.
- `final-desktop/final-verification.json`, `final-desktop/audit_final.py`: completed Desktop status, three HMAC checks, all current receipt hashes, independent native metric calculations, preserved inputs, console handles and fitted-plot provenance.
- `D:/GeoForge-Release-20261002/ui-verification/calibration-review-{en,zh-CN}.png` and `calibration-review-hashes-en.png`: the actual issued review card in both languages and expanded hash details.

Raw provider configuration and credentials remain private and are excluded from release evidence. This acceptance does not establish field-observation validation, an all-model calibration sweep, long-run posterior convergence or a hard optimizer budget cap. Public installer validation and release hashes belong to the release record rather than the scientific calibration result.
