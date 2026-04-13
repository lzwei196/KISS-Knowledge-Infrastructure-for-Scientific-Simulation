# Initial Conditions -- Skill Document

> **Stage ID**: s5_initial_conditions
> **Pipeline order**: 5 of 7
> **Depends on**: s1_domain_setup, s4_parameters

## Purpose

Generate the initial state of the hydrologic system for SUMMA: soil temperature and moisture profiles, snow state, canopy state, and aquifer storage. Proper initialization reduces spinup artifacts. A cold start (default) sets uniform values that require 1-2 years of simulation to equilibrate. A warm restart uses the final state from a previous run.

## Prerequisites

- [ ] Local attributes NetCDF exists (from Stage 1)
- [ ] Soil layer configuration decided (number of layers and thicknesses)
- [ ] Approximate mean annual temperature known for initial soil temperature

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| attributes_nc | file | Stage 1 | SUMMA local attributes NetCDF |
| n_soil_layers | value | config | Number of soil layers (default: 8) |
| soil_layer_depths | config | config | Layer thicknesses in meters |
| init_soil_temp | value | climate data | Initial soil temperature in K |
| init_soil_moisture | value | estimate | Initial volumetric moisture fraction |

## Default Soil Layer Configuration

SUMMA's standard 8-layer configuration:

| Layer | Depth (m) | Cumulative Depth (m) | Purpose |
|-------|-----------|---------------------|---------|
| 1 | 0.025 | 0.025 | Surface skin layer |
| 2 | 0.075 | 0.100 | Shallow root zone |
| 3 | 0.150 | 0.250 | Upper root zone |
| 4 | 0.250 | 0.500 | Mid root zone |
| 5 | 0.500 | 1.000 | Lower root zone |
| 6 | 0.500 | 1.500 | Subsoil |
| 7 | 1.000 | 2.500 | Deep subsoil |
| 8 | 1.500 | 4.000 | Deep subsoil / bedrock |

## Procedure

### Step 1: Determine initial conditions

- **Temperature**: Use mean annual air temperature for the basin.
  - Temperate: ~283 K (10 C)
  - Tropical: ~298 K (25 C)
  - Arctic/Alpine: ~268 K (-5 C)
- **Moisture**: Use field capacity (~0.25-0.35) for most basins.
- **Snow**: Set SWE=0, nSnow=0 for cold start (even in snowy regions -- snow builds up naturally).

### Step 2: Generate cold start file

```bash
python tools/s5_initial_conditions/create_initial_conditions.py \
  --attributes_nc outputs/<run>/summa_settings/attributes.nc \
  --output_nc outputs/<run>/summa_settings/coldState.nc \
  --n_soil_layers 8 \
  --soil_depths "0.025,0.075,0.15,0.25,0.50,0.50,1.0,1.5" \
  --init_temp 283.16 \
  --init_moisture 0.30
```

**Expected result**: `coldState.nc` with dimensions hru, scalarv, midSoil, midToto, ifcSoil, ifcToto.

### Step 3: Verify initial conditions

```bash
ncdump -h outputs/<run>/summa_settings/coldState.nc
```

Check that nSoil matches the number of soil layers, and all required state variables are present.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Cold state | `outputs/<run>/summa_settings/coldState.nc` | Has all required state variables, nSoil=8 |

## Validation Checks

1. **nSoil matches layer count**: `ncdump -v nSoil coldState.nc` should show the configured value (8).
2. **Temperature is realistic**: `ncdump -v mLayerTemp coldState.nc | tail -5` -- values should be 250-310 K.
3. **Moisture is reasonable**: `ncdump -v mLayerVolFracLiq coldState.nc | tail -5` -- values 0.1-0.5.
4. **Dimensions consistent**: midSoil = nSoil, ifcSoil = nSoil+1, midToto = nSnow+nSoil.

## Common Pitfalls

> **PITFALL**: Changing soil layers without regenerating coldState.
> SUMMA checks nSoil in coldState against the layer configuration. Mismatch = crash. See dt_006.

> **PITFALL**: Analyzing spinup period as if it were real output.
> First 1-2 years of cold-start output are equilibration artifacts. Discard them. See dt_015.

> **PITFALL**: Setting initial soil moisture too low (< 0.05) or too high (> theta_sat).
> Very dry starts cause extremely long spinup (5+ years). Moisture above saturation causes immediate runoff spikes.

---

*This skill document is part of the hydrocraft-summa knowledge infrastructure.*
*Stage 5 of 7 | Tools used: create_initial_conditions | Related triplets: dt_006, dt_015*
