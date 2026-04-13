# S3: Model Construction

## Purpose

Build the .ohq script file that defines the model topology (blocks and links),
boundary conditions, constituents, reactions, and simulation parameters. This is
the core model definition step.

## Inputs

| Input                | Source              | Description                        |
|----------------------|---------------------|------------------------------------|
| Template commands    | Stage S2            | loadtemplate/addtemplate lines      |
| Converted forcing    | Stage S1            | Time series CSV files              |
| Hydraulic parameters | Stage S3 params     | K_sat, porosity, Manning's n       |
| Domain geometry      | GIS/survey          | Areas, lengths, elevations         |
| Water quality data   | Lab/literature      | Initial concentrations, loadings   |

## Outputs

| Output              | Format | Description                                   |
|---------------------|--------|-----------------------------------------------|
| model.ohq           | Text   | Complete OHQ script ready to run              |
| *.txt/*.csv         | CSV    | Time series files referenced by the script    |

## Procedure

### Step 1: System Configuration

Set solver parameters first:

```
setvalue; object=system, quantity=simulation_start_time, value=0
setvalue; object=system, quantity=simulation_end_time, value=100
setvalue; object=system, quantity=initial_time_step, value=0.001
setvalue; object=system, quantity=c_n_weight, value=1
setvalue; object=system, quantity=nr_tolerance, value=0.001
setvalue; object=system, quantity=nr_timestep_reduction_factor, value=0.75
setvalue; object=system, quantity=nr_timestep_reduction_factor_fail, value=0.2
setvalue; object=system, quantity=minimum_timestep, value=1e-06
setvalue; object=system, quantity=n_threads, value=8
setvalue; object=system, quantity=alloutputfile, value=output.txt
setvalue; object=system, quantity=observed_outputfile, value=observedoutput.txt
```

### Step 2: Create Sources

Define external inputs before blocks reference them:

```
create source; type=atmospheric exchange, name=aeration,
  saturation=8.66[g/m~^3], rate_coefficient=2[1/day]

create source; type=constant_source, name=DOM_source,
  rate_per_volume=16[g/day/m~^3]

create source; type=Evapotranspiration_Penmam (S), name=ET_1,
  z0=0.0003[m], z2=2[m],
  Temperature=Temp.csv, wind_speed=Wind.csv,
  solar_radiation=Solar.csv, R_h=Humidity.csv
```

### Step 3: Create Constituents

```
create constituent; type=Constituent, name=DOM,
  concentration=0[g/m~^3], diffusion_coefficient=0.0017[m~^2/day]

create constituent; type=Constituent, name=O2,
  concentration=0[g/m~^3], diffusion_coefficient=0.0017[m~^2/day]
```

### Step 4: Create Reaction Parameters

```
create reaction_parameter; type=ReactionParameter, name=mu_H,
  base_value=6.0, reference_temperature=20, Arrhenius_factor=1.07

create reaction_parameter; type=ReactionParameter, name=K_s,
  base_value=20, reference_temperature=0, Arrhenius_factor=1
```

### Step 5: Create Reactions

```
create reaction; type=Reaction, name=aerobic_decomposition,
  rate_expression=(mu_H*DOM/(DOM+K_s)*O2/(O2+K_o)),
  DOM:stoichiometric_constant=-1,
  O2:stoichiometric_constant=-1,
  NH3:stoichiometric_constant=eta_on
```

### Step 6: Create Blocks

```
create block; type=Pond, name=Pond (1),
  Storage=357.6[m~^3], bottom_elevation=-0.8[m],
  alpha=558.75, beta=2,
  inflow=inflow.txt,
  O2:concentration=7[g/m~^3],
  O2:external_source=aeration,
  O2:external_mass_flow_timeseries=DO_loading.txt,
  DOM:concentration=25[g/m~^3],
  Evapotranspiration=ET_1
```

### Step 7: Create Links

```
create link; from=Pond (1), to=Pond (2), type=wide_channel,
  ManningCoeff=0.1, length=27.23[m], width=18.15[m]

create link; from=Pond (6), to=fixed_head (1), type=wier,
  alpha=33000, beta=2.5, crest_elevation=0[m]
```

### Step 8: Create Observations (Optional)

```
create observation; type=Observation, object=Pond (6),
  name=O2_out, expression=O2:concentration,
  error_structure=normal, error_standard_deviation=1
```

## Verification

- Every block must have a valid type from loaded templates
- Every link must reference existing blocks (from and to)
- Every source referenced by a block must be created first
- All time series files must exist in the working directory
- Unit brackets [unit] should be present on all dimensional values
- Semicolons separate command fields; commas separate key=value pairs

## Traps

| Trap                                    | Impact   | Prevention                        |
|-----------------------------------------|----------|-----------------------------------|
| Missing unit bracket on values          | Silent   | Always include [m], [g/m~^3] etc  |
| Source referenced before creation       | Fatal    | Create sources before blocks      |
| Block name with special characters      | Degraded | Use simple names, avoid / \       |
| Weir spelled as "wier" (OHQ spelling)   | Fatal    | Use "wier" not "weir"             |
| Comma in block name conflicts with CSV  | Fatal    | Avoid commas in names             |
| Missing inflow file                     | Silent   | Zero inflow assumed silently      |

## Example

Minimal 2-cell pond model:

```
loadtemplate; filename = resources/main_components.json
setvalue; object=system, quantity=simulation_end_time, value=10
setvalue; object=system, quantity=initial_time_step, value=0.01
create block; type=Pond, name=inlet, Storage=100[m~^3], alpha=50, beta=2
create block; type=fixed_head, name=outlet, head=0[m], Storage=100000[m~^3]
create link; from=inlet, to=outlet, type=wier, alpha=1000, beta=2.5, crest_elevation=0[m]
solve
```
