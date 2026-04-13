# Stage 6: Validation and Sensitivity Analysis

## Purpose

Validate GEOPHIRES simulation results against physical plausibility bounds,
published benchmarks, and expected ranges. Optionally perform sensitivity
analysis by varying key parameters.

## Inputs

| Input | Description |
|-------|-------------|
| summary.json | Parsed results from Stage 5 |
| benchmark.json | Optional reference results for comparison |
| complete_input.txt | Original input file (for sensitivity runs) |

## Outputs

| Output | Description |
|--------|-------------|
| validation_report.json | Validation results and metrics |
| validation.png | Comparison figure |
| sensitivity.csv | Sensitivity analysis results (optional) |

## Procedure

### Part A: Plausibility Validation

1. **Run validation**:
   ```bash
   python validate_geophires_results.py \
       --results summary.json \
       --figure validation.png
   ```

2. **Physical plausibility checks**:
   | Metric | Plausible Range | Red Flag |
   |--------|----------------|----------|
   | LCOE | 0.5–100 cents/kWh | < 0.5 or > 100 |
   | LCOH | 0.5–500 $/MMBTU | < 0.5 or > 500 |
   | Net Power | 0.01–5000 MW | Negative or > 5000 |
   | Bottom-hole T | 30–600 °C | < 30 or > 600 |
   | CAPEX | 0.1–50,000 MUSD | Negative or extreme |

3. **Profile consistency checks**:
   - Temperature should generally decrease over time (thermal drawdown)
   - Net power/heat should remain positive throughout
   - Pump power should not exceed 50% of gross generation

### Part B: Benchmark Comparison

4. **Compare to published results** (if available):
   ```bash
   python validate_geophires_results.py \
       --results summary.json \
       --benchmark published_results.json \
       --figure comparison.png
   ```

5. **Acceptable tolerance**:
   - Key metrics within ±10% of benchmark → PASS
   - ±10–25% → REVIEW (may be due to version differences)
   - > ±25% → INVESTIGATE (likely input error)

### Part C: Sensitivity Analysis

6. **Key parameters to vary** (in order of impact):
   | Parameter | Base | Range | Expected Impact |
   |-----------|------|-------|----------------|
   | Reservoir Depth | 3.0 km | 1–8 km | LCOE ±50% |
   | Gradient | 50 °C/km | 25–100 °C/km | LCOE ±60% |
   | Flow Rate | 55 kg/s | 20–120 kg/s | LCOE ±30% |
   | N Production Wells | 2 | 1–10 | LCOE ±40% |
   | Injection Temperature | 50°C | 30–80°C | LCOE ±20% |
   | Plant Lifetime | 30 yr | 20–50 yr | LCOE ±15% |
   | Discount Rate | 0.05 | 0.03–0.12 | LCOE ±25% |

7. **One-at-a-time sensitivity**:
   ```python
   from geophires_x_client import GeophiresXClient, GeophiresInputParameters

   client = GeophiresXClient()
   base_params = {'Reservoir Depth': 3.0, ...}

   for depth in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0]:
       params = base_params.copy()
       params['Reservoir Depth'] = depth
       result = client.get_geophires_result(GeophiresInputParameters(params))
       # Extract LCOE from result
   ```

8. **Monte Carlo** (for uncertainty quantification):
   - GEOPHIRES includes built-in Monte Carlo support
   - Define parameter distributions in input file
   - Run multiple realizations
   - Analyze LCOE distribution

## Verification

- Validation report shows "PASS" status
- No ERROR-level issues in plausibility checks
- Benchmark comparison within ±10% for key metrics
- Sensitivity results show monotonic trends where expected

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Version mismatch with benchmark | Large systematic differences | Note GEOPHIRES version used |
| Missing parameters in sensitivity | Different defaults between runs | Specify all params explicitly |
| Nonlinear interactions | Unexpected sensitivity results | Use factorial design, not OAT |
| Monte Carlo convergence | Unstable statistics | Increase sample count (>1000) |

## Example

Validation output:
```json
{
    "status": "PASS",
    "n_warnings": 1,
    "n_errors": 0,
    "plausibility": [
        "INFO: Final temperature (154.4°C) < initial (165.0°C). Normal drawdown."
    ],
    "comparison": {
        "Average Net Electricity Production": {
            "result": 5.37,
            "benchmark": 5.40,
            "relative_diff_pct": -0.56,
            "status": "PASS"
        }
    }
}
```

Expected LCOE ranges by system type (for reference):
| System Type | LCOE Range (¢/kWh) |
|-------------|-------------------|
| Hydrothermal electricity | 3–8 |
| EGS electricity | 5–30 |
| Direct-use heat | 1–5 ¢/kWh(th) |
| CLGS electricity | 10–50 |
