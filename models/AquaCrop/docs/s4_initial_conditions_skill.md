# Initial Water Content -- Skill Document

> **Stage ID**: s4_initial_conditions
> **Pipeline order**: 4 of 10
> **Depends on**: s2_soil_profile

## Purpose

Define the soil water content at the start of the simulation. Initial water content affects early-season crop germination and establishment. If set too low (below wilting point), the crop may fail to germinate. If set unrealistically high (above saturation), early drainage dynamics are distorted.

## Prerequisites

- [ ] Soil profile defined (S2 complete) -- needed to know number of layers
- [ ] Decision on initial moisture level (field observations, VIC output, or default FC)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| wc_type | string | User decision | 'Prop' (property name), 'Num' (volumetric m3/m3), 'Pct' (% of TAW) |
| method | string | User decision | 'Layer' (per soil layer) or 'Depth' (interpolate depth points) |
| depth_layer | list | Matches soil layers | Layer numbers [1, 2, ...] or depths [0.1, 0.5, ...] |
| value | list | User / VIC soil moisture | Values at each location |

## Procedure

### Step 1: Choose specification method

**Recommended default**: Field Capacity
```python
from aquacrop import InitialWaterContent
iwc = InitialWaterContent(wc_type='Prop', method='Layer', depth_layer=[1], value=['FC'])
```

**From VIC soil moisture output**:
```python
# VIC provides volumetric soil moisture (m3/m3) per soil layer
iwc = InitialWaterContent(wc_type='Num', method='Layer',
                          depth_layer=[1, 2],
                          value=[0.25, 0.30])  # m3/m3 from VIC
```

**As percentage of Total Available Water**:
```python
iwc = InitialWaterContent(wc_type='Pct', method='Layer',
                          depth_layer=[1], value=[70])  # 70% TAW
```

### Step 2: Match layers to soil profile

For multi-layer custom soils, the number of layers in IWC **must match** the soil.

**If single value given for multi-layer soil**: All layers silently default to FC. This is not an error but may not represent reality. See dt_012.

### Step 3: Validate ranges

- For `wc_type='Num'`: values must be between th_dry and th_s for the corresponding layer
- For `wc_type='Pct'`: values must be 0-100
- For `wc_type='Prop'`: values must be one of 'WP', 'FC', 'SAT'

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| iwc object | in-memory | `iwc.wc_type` is valid, `len(iwc.value)` matches expectation |

## Validation Checks

1. **Type validity**: `iwc.wc_type in ['Prop', 'Num', 'Pct']`
2. **Property names**: If `wc_type='Prop'`, each value must be 'WP', 'FC', or 'SAT'
3. **Layer match**: For multi-layer soil, `len(iwc.depth_layer)` should equal `soil.nLayer`

## Common Pitfalls

> **PITFALL**: Single-layer IWC with multi-layer soil
> AquaCrop silently defaults all layers to FC if IWC has fewer layers than soil. No warning is raised.
> **Do this instead**: Specify IWC for each soil layer explicitly.
> See diagnostic triplet dt_012.

> **PITFALL**: Initial water below wilting point
> Setting IWC below WP causes the crop to fail germination (GermThr threshold not met). The crop never emerges and yield is zero.
> **Do this instead**: Use at least 'WP' or preferably 'FC' as initial condition.
> See diagnostic triplet dt_004.

---

*This skill document is part of the aquacrop-ospy-knowledge infrastructure.*
*Stage 4 of 10 | Tools used: create_initial_water_content | Related triplets: dt_004, dt_012*
