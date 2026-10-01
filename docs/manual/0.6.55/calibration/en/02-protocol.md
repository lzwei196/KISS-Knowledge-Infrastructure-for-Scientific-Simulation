# Choose a defensible protocol

## Engine, adapter and case

| Part | Responsibility | Project location |
|---|---|---|
| Shared engine | Runs the selected optimizer and checks the holdout | Bundled with GeoForge |
| KI adapter | Applies parameters, launches the native model, reads real output and returns a score | `calibration/kis/<KI>/` |
| Project case | Defines parameters, targets, periods, objectives and budget | `calibration/cases/` |
| Run evidence | Records requests, logs, scores, parameters and acceptance | `calibration/runs/<run id>/` |

A shipped adapter is a starting point, not proof that it fits your particular basin, variable or observation format. For a KI without one, the agent prepares a project-owned adapter; the shared optimizer remains unchanged. The tested SHAW benchmark uses this route.

## Search methods

| Target | Available methods | Practical choice |
|---|---|---|
| One scalar loss | DDS, SCE-UA, DREAM | Choose a loss whose direction and units you understand. Record the seed and budget. |
| Several competing objectives | NSGA-II, NSGA-III, MOEA/D | Review trade-offs among candidate solutions rather than choosing by a single hidden average. |

The method names describe search algorithms, not a guarantee of convergence. A large parameter space needs more evidence and computation than a small, identifiable one. The app accepts a requested optimizer budget from 1 to 10,000. This is not a strict ceiling on native model calls: optimizer initialization or population batches, baseline checks and holdout checks can add work. Review the actual evaluation count and allow for the cost of each native run. Begin with a small smoke run before committing a large budget.

## Before approving

- **Target and alignment:** match the same variable, units, time support and spatial support. A point observation does not automatically validate a basin mean.
- **Bounds:** justify them from model documentation, measurements or literature. Keep physically linked parameters consistent; do not optimize nuisance parameters merely because they move the answer.
- **Forcing:** do not tune precipitation, elevation or observation transformations simply to hide a model-data disagreement.
- **Split:** use a held-out period that the search cannot see. Warm-up may precede a scoring period but must be documented.
- **Metrics:** state which metric determines acceptance and which are diagnostic. Include baseline and fitted values, sample counts and missing-data handling.
- **Reproducibility:** retain the native executable version/hash, original inputs, applied parameters, seed, budget and scoring code.

For Celsius temperature, percentage bias is inappropriate because Celsius has an arbitrary zero; the SHAW reference test reports NSE and RMSE instead. For other variables, choose metrics using that model's validation convention rather than copying this temperature protocol.

An improved training score with worse holdout performance is evidence of overfitting or a deficient protocol. It is not a reason to reuse the holdout as more training data and report the same holdout score as independent.
