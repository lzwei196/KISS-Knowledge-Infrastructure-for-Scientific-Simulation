# Soil Profile Setup -- Skill Document

> **Stage ID**: s2_soil_profile
> **Pipeline order**: 2 of 10
> **Depends on**: none

## Purpose

Create the soil profile that defines water holding capacity, drainage, and root zone properties. AquaCrop partitions the soil into compartments (default 12 x 0.1m = 1.2m depth). Each compartment belongs to a soil layer with specific hydraulic properties (wilting point, field capacity, saturation, saturated hydraulic conductivity). Getting the soil wrong silently corrupts the entire water balance.

## Prerequisites

- [ ] Know the soil texture class (sand/silt/clay fractions) or select a built-in type
- [ ] For HWSD coupling: HWSD raster + MDB processed for the grid cell

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| soil_type | string | User / HWSD | Built-in name or 'custom' |
| layers | list | User / HWSD | Custom layer definitions (thickness, thWP, thFC, thS, Ksat, penetrability) |
| dz | list | Optional | Compartment thickness list (default [0.1]*12, total 1.2m) |

## Procedure

### Step 1: Choose soil type or define custom layers

**Option A -- Built-in type** (fastest):
```python
from aquacrop import Soil
soil = Soil('SandyLoam')
```

**Option B -- Custom from hydraulic properties**:
```python
soil = Soil('custom')
soil.add_layer(thickness=0.3, thWP=0.10, thFC=0.22, thS=0.41, Ksat=1200, penetrability=100)
soil.add_layer(thickness=0.9, thWP=0.20, thFC=0.35, thS=0.48, Ksat=300, penetrability=100)
```

**Option C -- Custom from texture** (uses Saxton-Rawls pedotransfer):
```python
soil = Soil('custom')
soil.add_layer_from_texture(thickness=0.3, Sand=55, Clay=15, OrgMat=2, penetrability=100)
soil.add_layer_from_texture(thickness=0.9, Sand=30, Clay=25, OrgMat=1, penetrability=100)
```

### Step 2: Validate hydraulic constraints

For EVERY layer, verify: **thWP < thFC < thS** and **Ksat > 0**.

Run tool `validate_soil_hydraulics`.

**If constraint violated**: See diagnostic triplet dt_003.

### Step 3: Adjust compartment thickness if needed

Default compartments are 12 x 0.1m. For shallow soils or deep-rooted crops, adjust:
```python
soil = Soil('SandyLoam', dz=[0.1]*6 + [0.15]*4 + [0.2]*2)  # 1.7m total
```

The total depth must exceed maximum crop root depth (`crop.Zmax`). If soil is shallower than Zmax, the model restricts root growth.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Soil object | in-memory | `soil.nLayer >= 1`, `soil.profile` is DataFrame with th_wp, th_fc, th_s, Ksat columns |

## Validation Checks

1. **Hydraulic ordering**: For each layer: `th_wp < th_fc < th_s`
   - If violated: Assertion error. See dt_003.

2. **Ksat positive**: `Ksat > 0` for all layers
   - If zero: Soil is impermeable, all water becomes runoff.

3. **Total depth**: `soil.zSoil >= crop.Zmax`
   - If too shallow: Root growth will be restricted, reducing water uptake.

4. **Penetrability**: 0-100 (percentage of roots that can penetrate the layer)
   - 100 = fully penetrable, 0 = impenetrable layer (root barrier)

## Common Pitfalls

> **PITFALL**: thWP > thFC or thFC > thS (inverted water limits)
> This happens when importing soil data from a source that uses different column ordering. The symptom is an assertion error: `assert 1 == 2` with message "wrong soil type".
> **Do this instead**: Always verify thWP < thFC < thS before passing to add_layer.
> See diagnostic triplet dt_003.

> **PITFALL**: Using wrong soil type name (case-sensitive)
> Soil type names are case-sensitive: `'SandyLoam'` works, `'sandyloam'` triggers assertion.
> **Do this instead**: Use exact names from the built-in list. See SKILL.md Section 4.

> **PITFALL**: Custom soil with no add_layer calls
> `Soil('custom')` creates an empty profile. If you forget to call `add_layer()`, the model will crash during initialization.
> See diagnostic triplet dt_011.

---

*This skill document is part of the aquacrop-ospy-knowledge infrastructure.*
*Stage 2 of 10 | Tools used: create_soil_profile, validate_soil_hydraulics | Related triplets: dt_003, dt_011*
