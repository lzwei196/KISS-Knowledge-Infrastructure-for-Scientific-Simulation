# Crop Parameter Configuration — Skill Document

> **Stage ID**: s1_crop_params
> **Pipeline order**: 1 of 8
> **Depends on**: none

## Purpose

Load and validate WOFOST crop growth parameters that define how the simulated crop develops, photosynthesizes, partitions biomass, and senesces. Without correct crop parameters, the model produces physically meaningless results. PCSE uses YAML-based crop parameter files organized hierarchically: GenericC3/C4 (base) → EcoType (regional) → Variety (cultivar-specific). The `YAMLCropDataProvider` class loads these and supports crop rotations by switching the active crop/variety.

## Prerequisites

- [ ] PCSE package installed (`pip install pcse`)
- [ ] Target crop identified (wheat, maize, rice, soybean, barley, etc.)
- [ ] Target variety identified (e.g., `Winter_wheat_101`, `Maize_VanHeemst_1988`)
- [ ] If using custom parameters: YAML file follows PCSE crop parameter format

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| crop_name | string | user specification | PCSE crop name (case sensitive): `wheat`, `maize`, `rice`, `soybean`, `barley`, etc. |
| variety_name | string | user specification | PCSE variety name (case sensitive): e.g., `Winter_wheat_101` |
| crop_dir | directory | optional | Custom crop parameter directory. If omitted, uses PCSE built-in parameters. |

## Procedure

### Step 1: Load crop parameters via YAMLCropDataProvider

```python
from pcse.input import YAMLCropDataProvider

# Option A: Use built-in PCSE crop parameters
cropdata = YAMLCropDataProvider()

# Option B: Use custom YAML files from a specific directory
cropdata = YAMLCropDataProvider(fpath='/path/to/custom/crop_yamls/')

# List available crops and varieties
print("Available crops:", cropdata.get_crop_types())
```

**Expected result**: No exception raised. `get_crop_types()` returns a list including your target crop.

**If this fails**: See diagnostic triplet dt_001 (YAML parse error) or dt_012 (PCSE API version mismatch).

### Step 2: Set the active crop and variety

```python
cropdata.set_active_crop(crop_name='wheat', variety_name='Winter_wheat_101')
```

**Expected result**: No exception. The provider now returns parameters for the selected variety.

**If this fails**: See diagnostic triplet dt_010 (case sensitivity). `crop_name` and `variety_name` are CASE SENSITIVE. Check exact names with `cropdata.get_crop_types()` and `cropdata.get_variety_names('wheat')`.

### Step 3: Verify critical parameters

```python
# Check key parameters exist and are reasonable
critical_params = {
    'TSUM1': (100, 3000),    # thermal time emergence → anthesis (C.d)
    'TSUM2': (100, 3000),    # thermal time anthesis → maturity (C.d)
    'TDWI': (1, 500),        # initial dry weight (kg/ha)
    'SPAN': (10, 100),       # max leaf lifespan at 35C (days)
    'TBASEM': (-10, 20),     # base temp for emergence (C)
}
for param, (lo, hi) in critical_params.items():
    val = cropdata[param]
    assert lo <= val <= hi, f"{param}={val} outside range [{lo}, {hi}]"
```

**Expected result**: All assertions pass.

**If this fails**: See diagnostic triplet dt_007 (parameter range).

### Step 4: Check vernalization parameters (winter crops only)

For winter wheat, winter barley, and other vernalization-requiring crops:

```python
if 'Winter' in variety_name or 'winter' in variety_name:
    vern_params = ['VERNSAT', 'VERNBASE', 'VERNDVS']
    for p in vern_params:
        assert p in cropdata, f"Winter crop missing {p}"
    assert cropdata['VERNSAT'] > 0, "VERNSAT must be > 0 for winter crops"
    assert cropdata['VERNDVS'] > 0, "VERNDVS must be > 0 (safety cutoff)"
    print(f"Vernalization: VERNSAT={cropdata['VERNSAT']}d, "
          f"VERNBASE={cropdata['VERNBASE']}C, VERNDVS={cropdata['VERNDVS']}")
```

**Expected result**: Vernalization parameters present and positive.

**If this fails**: See diagnostic triplet dt_005 (vernalization misconfiguration).

### Step 5: Validate AFGEN tables

PCSE uses AFGEN tables (piecewise linear interpolation) for many parameters. The x-values must be strictly monotonically increasing.

```python
afgen_params = ['AMAXTB', 'EFFTB', 'SLATB', 'FOTB', 'FLTB', 'FSTB', 'FRTB', 'TMPFTB']
for param in afgen_params:
    if param in cropdata:
        table = cropdata[param]
        # table is a list of [x1, y1, x2, y2, ...]
        x_vals = table[0::2]  # even indices are x
        for i in range(1, len(x_vals)):
            assert x_vals[i] > x_vals[i-1], f"{param}: x values not monotonic at index {i}"
```

**Expected result**: All AFGEN tables have monotonically increasing x-values.

**If this fails**: See diagnostic triplet dt_013 (AFGEN non-monotonic).

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| cropdata object | in-memory YAMLCropDataProvider | `cropdata['TSUM1']` returns a number |
| crop parameter dict | in-memory dict | Contains all WOFOST parameters for the selected variety |

## Validation Checks

1. **Crop type exists**: `crop_name in cropdata.get_crop_types()` — if not, check spelling and case.
2. **Variety exists**: `variety_name in cropdata.get_variety_names(crop_name)` — if not, list available varieties.
3. **TSUM1 + TSUM2 reasonable**: For the target climate, total thermal time (TSUM1+TSUM2) should be achievable within the growing season. E.g., for maize in temperate zone: 800-2000 C.d.
4. **TDWI positive**: Initial dry weight must be > 0 (typically 20-200 kg/ha).
5. **Partitioning tables sum to 1**: At each DVS value, FRTB + FLTB + FSTB + FOTB should equal 1.0 (biomass partitioning to roots, leaves, stems, storage organs must sum to 100%).

## Common Pitfalls

> **PITFALL**: Case sensitivity in crop_name and variety_name
> PCSE crop names are lowercase (`wheat`, `maize`) but variety names often have mixed case (`Winter_wheat_101`). Using wrong case causes `KeyError` with an unhelpful message.
> **Do this instead**: Always call `cropdata.get_crop_types()` and `cropdata.get_variety_names(crop)` first to see exact names.
> See diagnostic triplet dt_010.

> **PITFALL**: Missing vernalization parameters for winter crops
> If you select a spring variety for a winter crop simulation (or vice versa), phenology will be wrong. Spring wheat varieties lack VERNSAT — using them for autumn sowing produces incorrect development timing.
> **Do this instead**: Match variety type to sowing season. Winter varieties for autumn sowing, spring varieties for spring sowing.
> See diagnostic triplet dt_005.

> **PITFALL**: Custom YAML format errors
> When creating custom crop parameter YAML files, indentation errors are invisible. A parameter at the wrong indent level silently inherits the wrong parent.
> **Do this instead**: Use `yaml.safe_load()` to parse and inspect structure before passing to PCSE.
> See diagnostic triplet dt_001.

---

*This skill document is part of the wofost-pcse-knowledge infrastructure.*
*Stage 1 of 8 | Tools: load_crop_parameters, validate_crop_params | Related triplets: dt_001, dt_005, dt_007, dt_010, dt_012, dt_013*
