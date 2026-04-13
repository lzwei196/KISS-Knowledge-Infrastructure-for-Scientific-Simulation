# Stage 1: Solution Definition

## Purpose

Define the aqueous solution composition for PHREEQC simulation. This stage converts
raw water chemistry data (lab analyses, field measurements, literature values) into
properly formatted SOLUTION keyword blocks with correct units and charge balance.

## Inputs

| Input              | Format       | Required | Source                         |
|--------------------|-------------|----------|--------------------------------|
| Water chemistry    | CSV/Excel    | Yes      | Lab analysis, field data       |
| pH                 | -            | Yes      | Field measurement (calibrated) |
| Temperature        | Celsius      | Yes      | Field measurement              |
| pe or Eh           | - or mV      | No       | Field or calculated from O2    |
| Density            | kg/L (g/cm3) | No       | Default 1.0 for freshwater     |
| Concentration unit | mg/L or molal| Yes      | Lab report                     |

## Outputs

- PHREEQC SOLUTION keyword block(s) in `.pqi` text file
- JSON summary with unit conversions applied and warnings

## Procedure

1. **Collect water chemistry data** from lab reports or databases.
   Identify available elements and their reported units.

2. **Verify charge balance** of the raw analysis:
   Sum cation equivalents vs. anion equivalents. If charge balance error > 5%,
   flag for review. In PHREEQC, one ion can be adjusted using the `charge` keyword.

3. **Map element names** to PHREEQC conventions:
   - Sulfate (SO4) -> `S(6)` (sulfur in +6 oxidation state)
   - Bicarbonate (HCO3) -> `C(4)` or `Alkalinity`
   - Ammonium (NH4) -> `N(-3)`, Nitrate (NO3) -> `N(5)`
   - Silica (SiO2) -> `Si` (PHREEQC converts internally using `as SiO2`)

4. **Set concentration units** using the `units` keyword:
   ```
   units   mg/L       # milligrams per liter (= ppm for dilute solutions)
   units   mmol/kgw   # millimoles per kilogram water
   units   ug/L       # micrograms per liter (= ppb)
   ```

5. **Convert pe/Eh** if needed:
   - If Eh is reported in mV: `pe = Eh(mV) / 59.16` at 25C
   - General formula: `pe = Eh(V) * F / (2.303 * R * T_K)`
   - If neither pe nor Eh available, estimate from dissolved O2

6. **Specify alkalinity** correctly:
   - If reported as mg/L CaCO3: use `Alkalinity X as CaCO3`
   - If reported as meq/L: use `Alkalinity X`
   - If reported as mg/L HCO3: use `C(4) X as HCO3`

7. **Run the converter tool**:
   ```bash
   python3 ki/tools/convert_solution_input.py \
       --input water_data.csv --output solutions.pqi \
       --units mg/L --charge-balance Cl
   ```

## Verification

1. Load the generated .pqi file and check element list against original data
2. Verify unit specification matches the source data
3. Run PHREEQC and check:
   - Charge balance error < 5%
   - No "Element not found" errors
   - pH and pe in output match input (for initial speciation)

## Traps

| Trap | Description | Detection | Fix |
|------|-------------|-----------|-----|
| ut_001 | mg/L assumed but data is in mol/kgw | Concentrations ~1000x too high | Set `units mol/kgw` |
| ut_003 | Alkalinity as CaCO3 not flagged | DIC concentration 2x wrong | Use `as CaCO3` qualifier |
| ut_005 | Eh (mV) entered as pe directly | Redox speciation completely wrong | pe = Eh(mV)/59.16 |

## Example

```
SOLUTION 1  Groundwater sample GW-01
    temp    18.5
    pH      7.2
    pe      3.5      # Eh = 207 mV -> pe = 207/59.16 = 3.5
    density 1.001
    units   mg/L
    Ca      85.3
    Mg      22.1
    Na      14.5
    K       3.2
    Cl      28.7     charge   # adjust Cl for charge balance
    S(6)    42.0     as SO4
    C(4)    210.0    as HCO3
    Si      12.5     as SiO2
    Fe      0.35
END
```
