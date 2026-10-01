# Read the result and keep evidence

## Interpret the Calibration card

| Status | Meaning and next action |
|---|---|
| **Engine unavailable** | The bundled engine cannot load; repair the installation before running. |
| **Adapter needed** | The selected KI needs a project adapter. |
| **Project case needed** | Define the target, parameter bounds, observations and held-out period. |
| **Workflow prepared** | A case exists; the agent must still check it against this study. |
| **Holdout passed** | The result satisfied the configured held-out check. Read the report and scientific limitations. |
| **Holdout not passed** | Do not promote the fitted parameters as a validated result. Diagnose the protocol or model/data mismatch. |
| **Run needs review** | Inspect the failed or interrupted attempt and its logs. |

**Validated** on the latest calibration means it passed the configured check. It does not certify all model physics, identify a unique parameter set, or establish validity at other sites. **Not promoted** means the fit is not accepted for use by that workflow.

## Open the files

Use the project's files/Results view or its folder on disk. Under `calibration/runs/<run id>/`, keep:

- `report.json`: the host's result and acceptance summary.
- `engine-report.json`: optimization and holdout details.
- `engine-request.json`: the actual engine request, including the declared case and protocol.
- `engine.log`: execution and diagnostic messages.

Each run retains its own immutable copy of the calibration runtime, so a later run cannot overwrite the earlier run’s recorded runtime evidence. Keep the project adapter, case, original observations and native model inputs with these reports. Individual evaluation files should make it possible to verify which values were applied to the model. A successful process exit without readable scientific output is not a valid evaluation.

## Decide whether the fit is usable

1. Confirm the real model ran and every reported parameter was applied. Check the command, executable identity and generated parameter/input files.
2. Compare baseline versus fitted metrics on **both** training and holdout periods; verify the sample counts and dates.
3. Inspect time series and residuals, not only a headline score. Check physical constraints and balances required by the KI.
4. Report uncertainty, identifiability limitations and any boundary-hitting parameter. A single best point does not quantify uncertainty.
5. Check GeoForge’s run records and final project status. A missing or rejected required holdout check is a warning, not scientific completion. The AI’s narrative cannot override failed validation, stale inputs or missing evidence.

Use GeoForge’s **Stop** control to interrupt an optimization. Windows launches non-interactive calibration subprocesses without requesting a console window. Any model-specific graphical interaction still needs separate verification.

If a run fails, preserve its reports and error text, fix the actual cause and obtain a fresh passing run. Never rename a failed report as a success or substitute reference output for model execution.
