# S2: Parameter Setup

## Purpose

Configure model parameters for a SuperflexPy model structure. Parameters control storage
capacities, recession rates, routing delays, and exchange fluxes. This stage maps
physical catchment properties (soil, land use, topography) to model parameters, or
applies default/literature values as starting points for calibration.

## Inputs

| Input | Source | Format | Notes |
|-------|--------|--------|-------|
| Soil texture | HWSD, SoilGrids | Class name or properties | Optional |
| Soil depth | Field survey, literature | meters | Optional |
| Catchment area | GIS | km² | For Node/Network setup |
| HRU fractions | Land-use map | fractions summing to 1.0 | For multi-unit Nodes |
| Literature values | Publications | Parameter tables | Model-specific |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Parameter dict | Python dict | `{'param_name': value}` |
| Parameter JSON | JSON file | For tool pipeline |
| Prefixed names | Strings | `unit_element_param` format |

## Procedure

### For GR4J

1. **Set x1** (Production Store capacity, mm): Start 100-500 for humid, 50-200 for arid
2. **Set x2** (Exchange coefficient, mm/d): Start 0 (positive = import)
3. **Set x3** (Routing Store capacity, mm): Start 10-200
4. **Set x4** (UH time base, d): Start 1-5
5. **Fix structural parameters**: alpha=2.0, beta=5.0, ni=4/9, gamma=5.0, omega=3.5

### For HBV-style

1. **Set Smax** (Max soil storage, mm): Derive from AWC × depth × 1000
2. **Set beta** (Runoff exponent): 1.0 (sandy) to 4.0 (clay)
3. **Set k** (Recession, 1/d): Derive from baseflow recession analysis
4. **Set Ce** (PET factor): 0.5-1.5
5. **Set m** (ET smoothing): 0.001-0.1

### Pedotransfer Estimation

```python
# Estimate Smax from soil properties
AWC = (field_capacity - wilting_point) * depth_m * 1000  # mm
Smax = AWC * 1.5  # Safety factor

# Estimate k from saturated conductivity
k = min(1.0, Ksat_mm_d / 10000.0)
```

```bash
python ki/tools/convert_parameters.py \
    --model gr4j \
    --soil-texture loam \
    --depth 1.5 \
    --output params.json
```

## Verification

- [ ] All required parameters are present in the dict
- [ ] Parameters are within documented ranges
- [ ] Storage capacities (x1, x3, Smax) are in mm, not m or cm
- [ ] Time parameters (x4) are in days, not hours
- [ ] Prefixed names match model hierarchy

## Traps

| Trap ID | Description | Impact |
|---------|-------------|--------|
| dt_004 | S0 in meters instead of mm | Extreme initial transient |
| dt_005 | Input array order swapped (P↔PET) | Silent nonsense results |
| dt_006 | Wrong parameter prefix | KeyError or silent no-op |
| dt_016 | Time-varying param array length ≠ n_timesteps | Crash |

## Example

```python
from superflexpy.implementation.models.gr4j import model

# Discover parameter names (with prefixes)
print(model.get_parameters_name())
# ['model_ps_x1', 'model_ps_alpha', 'model_ps_beta', 'model_ps_ni',
#  'model_rs_x2', 'model_rs_x3', 'model_rs_gamma', 'model_rs_omega',
#  'model_uh1_lag-time', 'model_uh2_lag-time']

# Set calibration parameters
model.set_parameters({
    'model_ps_x1': 300.0,
    'model_rs_x2': 0.5,
    'model_rs_x3': 50.0,
    'model_uh1_lag-time': 2.0,
    'model_uh2_lag-time': 4.0,
})
```
