# Stage 3: Model Execution

## Purpose

Run the GR4J daily lumped rainfall-runoff model through the airGR R package. This stage handles the complete workflow from data preparation through CreateInputsModel, CreateRunOptions, to RunModel_GR4J. The model is executed either via rpy2 (Python-R bridge) or via subprocess calling Rscript.

## Inputs

| Input | Source | Format | Notes |
|-------|--------|--------|-------|
| Forcing CSV | Stage 1 output | CSV with Date, Precip_mm, PotEvap_mm | No NA in P or PE |
| Parameters | Calibration or manual | 4 float values | X1, X2, X3, X4 |
| Run period | User specification | Start/end dates | Must be within forcing dates |
| Warmup period | Auto or manual | Integer indices | Default: 1 year before run |

## Outputs

| Output | Format | Content |
|--------|--------|---------|
| Simulation CSV | CSV | Date, Qsim_mm, Prod, Rout, AE, Perc, PR, QR, QD, Exch, ... |
| Metadata JSON | JSON | Parameters used, n_timesteps, Qsim stats |

## Procedure

### Step 1: Prepare InputsModel

```r
InputsModel <- CreateInputsModel(
  FUN_MOD = RunModel_GR4J,
  DatesR  = dates,      # POSIXt vector
  Precip  = precip_mm,  # numeric vector, >= 0, no NA
  PotEvap = pe_mm       # numeric vector, >= 0, no NA
)
```

**Requirements**:
- DatesR must be POSIXlt or POSIXct, continuous, no duplicates
- Precip and PotEvap must be same length as DatesR
- No NA values allowed in Precip or PotEvap
- Values must be >= 0

### Step 2: Define run and warmup periods

```r
Ind_Run <- seq(start_idx, end_idx)  # Must be integer!
```

**Warmup options**:
- NULL: auto-selects 1 year before Ind_Run (recommended)
- Manual: provide IndPeriod_WarmUp as integer sequence
- 0L: no warmup (not recommended — poor initialization)

**TRAP (dt_009)**: IndPeriod_Run must be integer type. Use `as.integer()`.

### Step 3: Create RunOptions

```r
RunOptions <- CreateRunOptions(
  FUN_MOD       = RunModel_GR4J,
  InputsModel   = InputsModel,
  IndPeriod_Run = Ind_Run,
  IniResLevels  = c(0.3, 0.5, NA, NA)  # 30% prod, 50% routing
)
```

**Default initialization**:
- Production store: 30% of X1 capacity
- Routing store: 50% of X3 capacity
- UH states: all zero
- **A 1-year warmup is essential to stabilize states**

### Step 4: Run model

```r
Param <- c(X1, X2, X3, X4)
OutputsModel <- RunModel_GR4J(InputsModel, RunOptions, Param)
```

**Parameter bounds enforced at runtime**:
- X1 < 0.01 → clipped to 0.01 (with warning)
- X3 < 0.01 → clipped to 0.01 (with warning)
- X4 < 0.5 → clipped to 0.5 (with warning)

### Step 5: Extract outputs

All outputs are in mm/day (fluxes) or mm (store levels):
- `OutputsModel$Qsim`: simulated discharge [mm/d]
- `OutputsModel$Prod`: production store level [mm]
- `OutputsModel$Rout`: routing store level [mm]
- `OutputsModel$AE`: actual evapotranspiration [mm/d]
- Plus 14 other diagnostic variables

## Verification

1. **Water balance**: Long-term mean(P) ≈ mean(AE) + mean(Qsim) ± mean(Exch)
2. **Store levels**: Prod should oscillate between 0 and X1; Rout between 0 and X3
3. **Qsim range**: Should be physically reasonable (check against Qobs if available)
4. **No -999.999 values**: These indicate Fortran initialization failures

## Traps

| ID | Trap | Silent? | Detection |
|----|------|---------|-----------|
| dt_006 | No warmup period | Semi | First-year Qsim unreliable |
| dt_007 | NA in Precip or PE | Error | airGR raises stop() |
| dt_009 | IndPeriod not integer | Error | airGR raises stop() |
| dt_011 | X4 < 0.5 | Warning | Clipped silently |
| RUN-001 | Store levels = -999 | Silent | Fortran init failure |

## Example

```python
from tools.run_gr4j import run_gr4j

result = run_gr4j(
    forcing_csv="forcing_gr4j.csv",
    output_csv="gr4j_output.csv",
    mode="simulation",
    params={"X1": 257.238, "X2": 1.012, "X3": 88.235, "X4": 2.208},
    warmup_years=1,
    run_start="1990-01-01",
    run_end="1999-12-31",
)
# result["qsim_mean"] ≈ 1.5 mm/d for a typical humid catchment
```

## Runtime Performance

| Catchment/Period | Runtime | Notes |
|-----------------|---------|-------|
| 10 years daily | < 0.1 sec | Fortran core is very fast |
| 50 years daily | < 0.5 sec | |
| Calibration (10 yr) | 5-30 sec | ~1000-5000 model runs |
