# Stage 5: Output Parsing and Analysis

## Purpose

Parse the GEOPHIRES text-format output report (.out) into structured data formats
(CSV, JSON) for further analysis, visualization, and comparison. Extract key metrics,
production profiles, cost breakdowns, and cashflow tables.

## Inputs

| Input | Description |
|-------|-------------|
| results.out | GEOPHIRES text-format output report |
| (optional) HDR.json | GEOPHIRES JSON output (if generated) |

## Outputs

| Output | Description |
|--------|-------------|
| summary.json | Structured JSON with all parsed sections |
| production_profile.csv | Year-by-year production data |
| energy_profile.csv | Annual energy production and heat mining |

## Procedure

1. **Parse the output file**:
   ```bash
   python parse_geophires_output.py \
       --input results.out \
       --json summary.json \
       --csv production_profile.csv \
       --energy-csv energy_profile.csv
   ```

2. **Extracted sections**:

   | Section | Key Fields |
   |---------|-----------|
   | Summary | End-use, Average power/heat, LCOE/LCOH, Well counts |
   | Economic Parameters | Model, Discount rate, NPV, IRR, MOIC |
   | Capital Costs | Drilling, Surface plant, Exploration, Total CAPEX |
   | O&M Costs | Wellfield, Power plant, Water, Total OPEX |
   | Reservoir Parameters | Model type, Bottom-hole temp, Fracture geometry |
   | Reservoir Simulation | Production temperatures, Heat extraction, Pressure drops |
   | Production Profile | Year, Drawdown, Temperature, Pump power, Net power |
   | Energy Profile | Year, Energy provided, Heat extracted, Heat content |
   | Cashflow | Year, Revenue, OPEX, Net cashflow, Cumulative |

3. **Key scalar metrics** (extracted to metrics dict):
   - LCOE (cents/kWh) or LCOH ($/MMBTU)
   - Average net power (MW) or heat (MWth)
   - Total CAPEX (MUSD)
   - NPV (MUSD)
   - IRR (%)
   - Payback period (years)

4. **Production profile CSV columns**:
   ```
   year, thermal_drawdown, geofluid_temperature_degC, pump_power_MW, net_power_or_heat_MW, first_law_efficiency_pct
   ```

5. **Energy profile CSV columns**:
   ```
   year, energy_provided_GWh, heat_extracted_GWh, reservoir_heat_content_1e15J, percentage_heat_mined
   ```

## Verification

- JSON file is valid and contains all expected sections
- Production profile spans the full plant lifetime
- Year count matches Plant Lifetime setting
- LCOE/LCOH is present and positive
- Net power/heat values are non-negative (or investigate if negative)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Output format varies by version | Missing sections in parse | Check GEOPHIRES version |
| Direct-use vs electricity headers | Wrong columns parsed | Parser detects end-use automatically |
| Cogeneration dual output | Two power/heat columns | Parse both electricity and heat |
| MUSD vs USD units | Cost values off by 10⁶ | Check output section headers |
| Percentage vs fraction in output | Misinterpreted efficiency | Read unit labels in output |

## Example

Parsed summary.json excerpt:
```json
{
    "summary": {
        "End-Use Option": {"value": "Electricity", "unit": ""},
        "Average Net Electricity Production": {"value": 5.37, "unit": "MW"},
        "Electricity breakeven price": {"value": 5.04, "unit": "cents/kWh"}
    },
    "capital_costs": {
        "Drilling and completion costs": {"value": 21.95, "unit": "MUSD"},
        "Surface power plant costs": {"value": 12.83, "unit": "MUSD"},
        "Total capital costs": {"value": 40.85, "unit": "MUSD"}
    },
    "metrics": {
        "Average Net Electricity Production": 5.37,
        "Electricity breakeven price": 5.04,
        "Total capital costs": 40.85
    }
}
```

Production profile CSV excerpt:
```csv
year,thermal_drawdown,geofluid_temperature_degC,pump_power_MW,net_power_or_heat_MW,first_law_efficiency_pct
1,1.0000,165.00,0.27,5.60,9.83
2,0.9988,164.80,0.27,5.56,9.79
...
30,0.9359,154.43,0.28,4.45,8.38
```
