# Stage 3: Reaction Setup

## Purpose

Configure the geochemical reactions to simulate: mineral equilibrium, ion exchange,
surface complexation, kinetic reactions, gas phases, and/or transport. This stage
translates the conceptual hydrogeochemical model into PHREEQC keyword blocks.

## Inputs

| Input                 | Format      | Required | Source                        |
|-----------------------|-------------|----------|-------------------------------|
| Mineral assemblage    | Text/XRD    | Varies   | Geological survey, drill logs |
| CEC data              | cmol+/kg    | For exch | HWSD, soil analysis           |
| Surface area          | m2/g        | For surf | BET measurement, literature   |
| Rate constants        | mol/m2/s    | For kin  | Literature values             |
| Dispersivity          | m           | For tran | Tracer tests, literature      |
| Flow velocity         | m/s         | For tran | Darcy flux / porosity         |

## Outputs

- PHREEQC keyword blocks: EQUILIBRIUM_PHASES, EXCHANGE, SURFACE, KINETICS, RATES, TRANSPORT
- Assembled input file ready for execution

## Procedure

### 3.1 Equilibrium Phases

Define minerals that the solution should equilibrate with:

```
EQUILIBRIUM_PHASES 1
    Calcite    0.0   10.0    # Target SI=0, initial 10 mol available
    Dolomite   0.0    5.0
    Gypsum     0.0    0.0    # SI=0, initial 0 mol (precipitate only)
    CO2(g)    -3.5   10.0    # log P(CO2) = -3.5 atm (soil gas)
```

Key parameters:
- First number: target saturation index (0.0 = equilibrium)
- Second number: initial moles available (0 = only precipitation allowed)

### 3.2 Ion Exchange

Convert CEC from soil data to PHREEQC EXCHANGE block:

```
EXCHANGE 1
    X    0.125    # mol exchange sites per kgw
    -equilibrate 1
```

**Unit conversion from HWSD**:
- HWSD CEC in cmol(+)/kg = meq/100g
- PHREEQC needs mol/kgw
- Formula: `X_mol = CEC_cmol * bulk_density / (porosity * 100)`

Use the converter tool:
```bash
python3 ki/tools/convert_soil_params.py --cec 25 --porosity 0.3 \
    --bulk-density 1.5 --output exchange.pqi
```

### 3.3 Surface Complexation

For adsorption modeling (e.g., arsenic on ferrihydrite):

```
SURFACE 1
    Hfo_sOH   0.005   600   0.09   # strong sites, SA(m2/g), mass(g)
    Hfo_wOH   0.2                    # weak sites
    -equilibrate 1
    -no_edl                          # or -diffuse_layer
```

### 3.4 Kinetic Reactions

Define rate expressions and run kinetics:

```
RATES
    Calcite_kinetics
    -start
    10 rate = PARM(1) * (1 - SR("Calcite"))
    20 moles = rate * TIME
    30 SAVE moles
    -end

KINETICS 1
    Calcite_kinetics
        -formula CaCO3 1
        -m    1.0          # initial moles
        -m0   1.0
        -parms 1.0e-6      # rate constant
    -steps 86400 in 10 steps   # 1 day, 10 steps
    -step_divide 1
```

### 3.5 Transport

Set up 1-D advection-dispersion-reaction:

```
TRANSPORT
    -cells          20
    -lengths        0.05    # 5 cm per cell = 1 m total
    -dispersivities 0.01    # 1 cm dispersivity
    -shifts         40      # number of advection steps
    -time_step      3600    # 1 hour per shift
    -flow_direction forward
    -boundary_conditions flux flux
    -diffusion_coefficient 1.0e-9
    -porosity       0.3
```

### 3.6 Selected Output

Always configure SELECTED_OUTPUT to get structured results:

```
SELECTED_OUTPUT
    -file           results.sel
    -totals         Ca Mg Na Cl S(6) C(4) Fe
    -molalities     CaCO3 CO2
    -saturation_indices Calcite Dolomite Gypsum
    -pH
    -pe
    -temperature
    -ionic_strength
    -step
    -simulation
```

## Verification

1. Check that all minerals in EQUILIBRIUM_PHASES exist in the selected database
2. Verify exchange capacity is in mol/kgw (not cmol/kg or meq/g)
3. For transport: check Grid Peclet number (dx/alpha) > 2 and Courant number ≤ 1
4. For kinetics: verify rate expression units are mol/s (not mol/day)
5. Run a test with PRINT -status true to see iteration details

## Traps

| Trap | Description | Detection | Fix |
|------|-------------|-----------|-----|
| ut_009 | CEC in meq/100g entered as mol | Exchange 100x too large | Divide by 100, convert soil→water |
| ut_010 | Surface area cm2/g vs m2/g | Adsorption 10,000x wrong | Ensure m2/g |
| ut_007 | Dispersivity in cm not m | Transport dispersion 100x wrong | Convert to meters |
| dk_009 | Initial moles = 0 | Mineral can't dissolve | Set >0 for dissolution |
| ut_008 | Kinetic rate in per-day | Rate 86,400x too fast | Use per-second consistently |

## Example

Complete reaction setup for calcite dissolution in a soil column:

```
EQUILIBRIUM_PHASES 1-20   # one assemblage per transport cell
    Calcite    0.0   0.5
    CO2(g)    -2.0  10.0

EXCHANGE 1-20
    X    0.05
    -equilibrate 1

TRANSPORT
    -cells          20
    -lengths        0.05
    -dispersivities 0.005
    -shifts         100
    -time_step      3600
    -flow_direction forward
    -boundary_conditions flux flux
    -porosity       0.30
    -diffusion_coefficient 1.0e-9

SELECTED_OUTPUT
    -file      column_results.sel
    -totals    Ca C(4) Na Cl
    -saturation_indices Calcite
    -pH  -pe
    -step
END
```
