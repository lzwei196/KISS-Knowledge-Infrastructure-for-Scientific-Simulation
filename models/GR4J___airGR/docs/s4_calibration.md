# Stage 4: Calibration

## Purpose

Calibrate the 4 GR4J parameters (X1, X2, X3, X4) by optimizing an efficiency criterion against observed discharge. The airGR package provides the Calibration_Michel algorithm, which uses a two-step approach: grid screening followed by steepest-descent local search.

## Inputs

| Input | Source | Format | Notes |
|-------|--------|--------|-------|
| Forcing CSV | Stage 1 output | CSV | Must include Qobs_mm column |
| Observed discharge | In forcing CSV | mm/day | NA values allowed |
| Criterion choice | User | String | NSE (default), KGE, KGE2, RMSE |
| Run period | User | Date range | Calibration period |

## Outputs

| Output | Format | Content |
|--------|--------|---------|
| Calibrated parameters | 4 floats | X1 [mm], X2 [mm/d], X3 [mm], X4 [d] |
| Criterion value | Float | NSE, KGE, etc. at calibrated params |
| Calibration history | Matrix | All tested parameter sets and criteria |

## Procedure

### Step 1: Prepare InputsCrit

```r
InputsCrit <- CreateInputsCrit(
  FUN_CRIT    = ErrorCrit_NSE,  # or ErrorCrit_KGE
  InputsModel = InputsModel,
  RunOptions  = RunOptions,
  VarObs      = "Q",
  Obs         = Qobs_mm[Ind_Run]  # NA allowed
)
```

**Observation requirements**:
- Must be in mm/day (same unit as GR4J output)
- NA values are allowed (timesteps with NA are excluded from criterion)
- At least ~100 non-NA values recommended

### Step 2: Create CalibOptions

```r
CalibOptions <- CreateCalibOptions(
  FUN_MOD   = RunModel_GR4J,
  FUN_CALIB = Calibration_Michel
)
```

Default search ranges (in real parameter space):
- X1: exp(-0.916) to exp(7.601) → ~0.4 to 2000 mm
- X2: sinh(-10) to sinh(10) → ~-11000 to 11000 mm/d
- X3: exp(-0.693) to exp(6.215) → ~0.5 to 500 mm
- X4: 0.5 to 39.5 d

### Step 3: Run Calibration_Michel

```r
OutputsCalib <- Calibration_Michel(
  InputsModel  = InputsModel,
  RunOptions   = RunOptions,
  InputsCrit   = InputsCrit,
  CalibOptions = CalibOptions,
  FUN_MOD      = RunModel_GR4J
)
Param <- OutputsCalib$ParamFinalR
```

**Algorithm details**:
1. **Grid screening**: Tests ~300-1000 parameter combinations on a predefined grid in transformed space
2. **Steepest descent**: Local search from best grid point
   - Step size starts at 0.64 (in transformed space)
   - Doubles after 2*NParam consecutive improvements
   - Halves when no improvement found
   - Converges when step < 0.01
3. **Typical runtime**: 1000-5000 model evaluations, 5-30 seconds for 10-year daily data

### Step 4: Evaluate calibration quality

| Criterion | Good | Acceptable | Poor |
|-----------|------|------------|------|
| NSE | > 0.75 | 0.50-0.75 | < 0.50 |
| KGE | > 0.70 | 0.40-0.70 | < 0.40 |
| PBIAS | < 10% | 10-25% | > 25% |

## Verification

1. **Parameters in reasonable range**: Compare with literature values for catchment type
2. **NSE > 0.5**: Minimum for acceptable calibration
3. **Split-sample test**: Calibrate on period A, validate on period B
4. **No boundary hitting**: If X1 or X3 at limits, search range may be too narrow
5. **Water balance**: PBIAS should be < 25%

## Traps

| ID | Trap | Silent? | Detection |
|----|------|---------|-----------|
| dt_008 | Using raw params as starting point in transformed space | Error | Poor calibration |
| CAL-001 | Qobs in wrong unit | Yes | NSE = -infinity |
| CAL-002 | Too short calibration period | Semi | Unstable parameters |
| CAL-003 | All Qobs = NA | Error | No valid comparison |
| CAL-004 | Criterion choice matters | Semi | NSE biased toward peaks |

## Example

```python
from tools.run_gr4j import run_gr4j

result = run_gr4j(
    forcing_csv="forcing_gr4j.csv",
    output_csv="gr4j_calib_output.csv",
    mode="calibration",
    criterion="NSE",
    run_start="1990-01-01",
    run_end="1999-12-31",
)
# result["calibrated_params"] ≈ [257, 1.01, 88, 2.21]
# result["NSE"] ≈ 0.92
```

## Typical Calibration Results (Literature)

| Region | NSE Range | X1 [mm] | X2 [mm/d] | X3 [mm] | X4 [d] |
|--------|-----------|---------|-----------|---------|--------|
| France (429 basins) | 0.60-0.95 | 100-1200 | -5-5 | 10-500 | 0.5-5 |
| Australia | 0.50-0.90 | 200-1500 | -3-2 | 20-300 | 1-4 |
| China (humid) | 0.65-0.95 | 150-800 | -2-3 | 30-200 | 1-3 |

## Advanced: Custom Calibration

airGR also supports external calibration algorithms:
- **DEoptim**: Differential Evolution (global optimizer, R package)
- **caRamel**: Multi-objective calibration (R package)
- **MCMC**: Bayesian parameter estimation via FME/coda packages
- See vignettes V02.1 and V02.2 in airGR documentation
