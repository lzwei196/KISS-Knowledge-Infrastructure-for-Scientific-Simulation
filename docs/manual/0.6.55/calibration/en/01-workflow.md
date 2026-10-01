# Calibrate a real model

Calibration searches for parameter values that improve a model's fit to a chosen target. GeoForge supplies a common search engine, while a KI adapter must write the parameters into the real model, execute it and score its outputs. The engine must never replace the scientific model.

> **Separate three claims.** A working engine, a successful calibration run and a model validated against independent observations are different results. The SHAW benchmark in this guide tests recovery of the publisher's reference output; it is not field validation.

## Prepare a project

1. First run the uncalibrated model on the intended input data. Check dates, units, water/energy balances and physical plausibility before optimizing anything.
2. Start a new chat if the earlier project is already **Completed**. Choose the intended KI and AI before sending the first message.
3. Provide authentic observations with timestamps, units, locations and missing-value rules. Specify which simulated output corresponds to each measured variable.
4. State parameter names, meanings, units, defensible bounds, fixed parameters, fitting period and a separate held-out period. Keep the held-out data out of parameter search.
5. Set the search method, run budget and random seed. Ask for both baseline and fitted scores on both periods.

## Example request for your own observations

> Calibrate my selected model against the observation file I will upload. First check the baseline and the time/space/unit alignment. Propose a small set of physically defensible parameters and bounds; keep forcing and measurement corrections fixed unless independently justified. Fit only the agreed training period and reserve the later period as holdout. Use DDS with a budget of 100 evaluations and a recorded seed. Report baseline and fitted metrics on both periods, rejected runs and the exact model/input versions. Show the plan before running.

The dates, bounds and metrics are scientific decisions for your case. They are not supplied by this example request. Answer GeoForge's planning cards and use the input's **Upload files** button to bind required observations.

## Prepare the adapter without executing it

If the selected KI needs a project adapter, planning can write only that KI’s calibration contract and runner into its project calibration folder. This prepares the two files for review; it does not authorize optimization, native model execution or arbitrary project edits.

## Review and run

1. In **◇ Project status → Details → Calibration**, check whether an adapter and project case exist. **Adapter needed** means preparation is still required; it is not an engine failure.
2. **Calibrate with agent** (or **Continue calibration**) sends a request to the chat. **Add observations** attaches files; bind any required plan input through its own upload row.
3. On **Approve the plan?**, review inputs, parameter bounds and defaults, objective, train/holdout split, algorithm, requested budget, seed and executable calibration step. The plan binds the exact adapter and calibration contract that will run. Change the plan if they differ from your study.
4. Select **Approve and start**, then **Continue with this choice**. GeoForge records approved execution; a verbal claim from the AI does not replace that record.
5. Keep the app running. **Stop** ends the current attempt and preserves its recorded outcome. A stopped or failed attempt must not be presented as a successful fit.

Changing the adapter, contract, data, parameter bounds or invocation after approval requires the relevant plan to be reviewed again. Both API agents and local CLI agents must use the approved calibration step and its recorded run; switching agent type does not bypass approval. Do not change files underneath a running optimization.
