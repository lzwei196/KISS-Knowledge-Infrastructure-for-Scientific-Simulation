# Stage 2: Economic Parameter Setup

## Purpose

Configure the economic and financial parameters for GEOPHIRES simulation.
Map economic assumptions to the correct GEOPHIRES economic model format,
handling percent-to-fraction conversions and model-specific requirements.

## Inputs

| Input | Source | GEOPHIRES Unit |
|-------|--------|----------------|
| Economic model choice | User decision | Integer 1–5 |
| End-use option | Site characterization | Integer 1, 2, 31–52 |
| Plant type | Temperature analysis | Integer 1–9 |
| Interest/discount rates | Financial assumptions | **fraction** (not percent) |
| Plant lifetime | Project plan | years |
| Utilization factor | Operations estimate | fraction 0–1 |
| Cost overrides | Site-specific estimates | MUSD |

## Outputs

- `economics_params.txt`: GEOPHIRES-formatted economic parameter file
- Validated parameter set with compatibility checks

## Procedure

1. **Select economic model** based on analysis depth:

   | Model | Complexity | Required Inputs | Best For |
   |-------|-----------|----------------|----------|
   | 1 (FCR) | Low | Fixed Charge Rate | Quick screening |
   | 2 (Standard) | Medium | Discount Rate | Standard studies |
   | 3 (BICYCLE) | High | Bond/Equity rates, Tax | Detailed finance |
   | 4 (CLGS) | Low | Basic rates | Closed-loop systems |
   | 5 (SAM PPA) | Very High | Full PPA structure | Utility-scale projects |

2. **Convert rates from percent to fraction**:
   ```
   5% discount rate → 0.05 (NOT 5.0)
   39.2% tax rate → 0.392 (NOT 39.2)
   ```
   The tool auto-detects: values > 1.0 are treated as percentages.

3. **Set end-use and plant type** (must be compatible):
   - Electricity (1) → Plant Type 1–4 (ORC or flash)
   - Direct-Use Heat (2) → Plant Type 7 (DH), 9 (Industrial)
   - Cogeneration (31–52) → Appropriate combination

4. **Configure cost overrides** if site-specific cost data is available:
   - Well drilling costs (MUSD per well)
   - Surface plant CAPEX (MUSD)
   - Annual O&M (MUSD/yr)

5. **Run conversion**:
   ```bash
   python convert_site_economics.py --config economics_config.json --output economics_params.txt
   ```

## Verification

- Fixed Charge Rate should be 0.01–0.20 (1–20%), not 1–20
- Discount Rate should be 0.03–0.15 (3–15%), not 3–15
- Plant Lifetime should be 20–50 years
- Utilization Factor should be 0.8–0.95 for baseload geothermal

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Rate as percent not fraction | LCOE 100× too high | Divide by 100 |
| End-use/plant type mismatch | Zero power output | Match plant type to end-use |
| Missing BICYCLE parameters | Simulation uses defaults silently | Specify all 5 BICYCLE params |
| Wrong economic model for CLGS | Invalid LCOE calculation | Use Model 4 for closed-loop |
| Utilization > 1.0 | Physically impossible output | Ensure fraction ≤ 1.0 |

## Example

BICYCLE model configuration:
```json
{
    "economic_model": 3,
    "end_use_option": "electricity",
    "power_plant_type": "subcritical_orc",
    "plant_lifetime_years": 30,
    "fraction_investment_bonds": 0.65,
    "bond_interest_rate": 0.07,
    "equity_interest_rate": 0.12,
    "inflation_rate": 0.025,
    "combined_tax_rate": 0.392,
    "utilization_factor": 0.9,
    "pump_efficiency": 0.8,
    "time_steps_per_year": 4
}
```

Output:
```
Economic Model,3,
End-Use Option,1,
Power Plant Type,1,
Plant Lifetime,30,
Fraction of Investment in Bonds,0.65,
Inflated Bond Interest Rate,0.07,
Inflated Equity Interest Rate,0.12,
Inflation Rate,0.025,
Combined Income Tax Rate,0.392,
Utilization Factor,0.9,
Circulation Pump Efficiency,0.8,
Time steps per year,4,
```
