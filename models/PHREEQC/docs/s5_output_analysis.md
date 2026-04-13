# Stage 5: Output Analysis

## Purpose

Parse, interpret, and validate PHREEQC output. Extract key results (speciation,
saturation indices, mass balances, transport profiles) into structured formats for
downstream analysis and visualization.

## Inputs

| Input            | Format       | Required | Source               |
|------------------|-------------|----------|----------------------|
| Full output      | .pqo text   | Yes      | Stage 4 execution    |
| Selected output  | .sel TSV    | Optional | Stage 4 (if configured) |

## Outputs

| Output           | Format  | Description                         |
|------------------|---------|-------------------------------------|
| Speciation CSV   | .csv    | Species molalities and activities   |
| SI table         | .csv    | Saturation indices for all phases   |
| Totals CSV       | .csv    | Element totals per simulation step  |
| Summary JSON     | .json   | Aggregated results and metadata     |

## Procedure

### 5.1 Parse Selected Output

The `.sel` file is the easiest path to structured data:

```bash
python3 ki/tools/parse_output.py \
    --input results.sel --output results.csv --format csv --selected
```

**TRAP**: `.sel` files use TAB delimiters, not commas. If using pandas directly:
```python
import pandas as pd
# CORRECT:
df = pd.read_csv("results.sel", sep="\t")
# WRONG - produces single mangled column:
# df = pd.read_csv("results.sel", sep=",")
```

### 5.2 Parse Full Output

For detailed speciation from `.pqo` files:

```bash
# Extract all sections
python3 ki/tools/parse_output.py \
    --input output.pqo --output full_results.json --format json --extract all

# Extract only saturation indices
python3 ki/tools/parse_output.py \
    --input output.pqo --output si_table.csv --format csv --extract si
```

### 5.3 Key Output Sections

#### Solution Composition
```
----------------------------Solution composition------------------------------

    Elements           Molality       Moles

    C(4)              3.390e-03   3.390e-03
    Ca                1.327e-03   1.327e-03
    Cl                8.066e-04   8.066e-04
```
- Molality = mol/kgw (moles per kg water)
- Use these values to verify mass balance

#### Species Distribution
```
----------------------------Distribution of species----------------------------

                                               Log       Log       Log
   Species          Molality    Activity  Molality  Activity     Gamma

   OH-             1.049e-07   1.012e-07    -6.979    -6.995    -0.016
   H+              1.023e-07   1.000e-07    -6.990    -7.000    -0.010
   H2O             5.551e+01   9.999e-01     1.744    -0.000     0.000
```
- Activity ≠ molality (activity = molality * gamma)
- Log gamma reflects the activity coefficient correction

#### Saturation Indices
```
-------------------------------Saturation indices-------------------------------

  Phase               SI**    log IAP   log K(298 K,   1 atm)

  Anhydrite        -2.37      -6.67     -4.30  CaSO4
  Aragonite        -0.14      -8.48     -8.34  CaCO3
  Calcite           0.00      -8.48     -8.48  CaCO3
  CO2(g)           -2.97      -4.40     -1.43  CO2
  Dolomite          0.12     -16.92    -17.04  CaMg(CO3)2
```
- SI = log(IAP/K): 0 = equilibrium, >0 = supersaturated, <0 = undersaturated
- Use SI to identify minerals likely to precipitate or dissolve

#### Phase Assemblage
```
-----------------------------Phase assemblage--------------------------------

                                  Moles in assemblage
Phase               SI  log IAP  log K(T, P)   Initial       Final       Delta

Calcite              0.00   -8.48     -8.48    1.000e+01   9.999e+00  -1.327e-03
```
- Delta = moles transferred (negative = dissolution, positive = precipitation)

### 5.4 Transport Output

For transport simulations, output includes spatial profiles at each time step.
Use SELECTED_OUTPUT with `-distance true` to get cell positions:

```python
import pandas as pd
df = pd.read_csv("transport.sel", sep="\t")
# Plot concentration vs distance at final time
final = df[df["step"] == df["step"].max()]
plt.plot(final["dist(m)"], final["Ca(mol/kgw)"])
```

### 5.5 Quality Checks

| Check                   | Acceptable Range     | Action if Failed           |
|-------------------------|---------------------|----------------------------|
| Charge balance error    | < 5%                | Review input, add `charge` |
| Percent error           | < 1%                | Numerical issue, simplify  |
| Water mass              | ~1.0 kg             | Check reaction stoichiometry|
| Ionic strength          | < 0.7 (for phreeqc.dat) | Switch to Pitzer model |
| Convergence iterations  | < 200               | Simplify or add stepping   |

## Verification

1. All solutions have charge balance < 5%
2. Mass is conserved (sum of element moles = input + reaction transfers)
3. Phases at equilibrium have SI within ±0.01 of target
4. Transport profiles are physically reasonable (monotonic fronts, no oscillation)
5. Kinetic results show expected time dependence (approach to equilibrium)

## Traps

| Trap | Description | Detection | Fix |
|------|-------------|-----------|-----|
| dk_008 | .sel parsed with comma sep | Single column in DataFrame | Use sep='\t' |
| dt_013 | SI misread as concentration | Values -20 to +5 range | SI is log10 ratio, not amount |
| dt_014 | Molality vs mg/L confusion | Off by molar mass factor | Convert: mg/L = molality * MW * 1000 |

## Example

Complete output analysis workflow:
```bash
# Parse selected output to CSV
python3 ki/tools/parse_output.py \
    --input simulation.sel --output results.csv --format csv --selected

# Parse full output for saturation indices
python3 ki/tools/parse_output.py \
    --input simulation.pqo --output si_data.json --format json --extract si

# Quick Python analysis
python3 -c "
import pandas as pd
df = pd.read_csv('results.csv')
print('pH range:', df['pH'].min(), '-', df['pH'].max())
print('Ca range:', df['Ca(mol/kgw)'].min(), '-', df['Ca(mol/kgw)'].max())
if 'si_Calcite' in df.columns:
    print('Calcite SI:', df['si_Calcite'].iloc[-1])
"
```
