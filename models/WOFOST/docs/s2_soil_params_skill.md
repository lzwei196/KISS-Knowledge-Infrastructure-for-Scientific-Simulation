# Soil Parameter Setup — Skill Document

> **Stage ID**: s2_soil_params
> **Pipeline order**: 2 of 8
> **Depends on**: none

## Purpose

Configure soil hydraulic and physical parameters for the WOFOST classic water balance. Unlike DSSAT's multi-layer soil profile, WOFOST uses a single-layer "bucket" model characterized by three moisture limits (SMW, SMFCF, SM0) and hydraulic conductivity (K0). The soil parameters determine water stress patterns, which directly control yield in water-limited (WLP) simulations. Incorrect soil parameters produce plausible-looking but wrong yields with no error message.

## Prerequisites

- [ ] Target location coordinates known (lat, lon)
- [ ] HWSD global raster accessible at `data/soil/HWSD_RASTER/hwsd.bil` (or equivalent soil database)
- [ ] HWSD MDB database accessible at `data/forcing/huaihe_raw/soil/HWSD.mdb`
- [ ] Understanding of which simulation mode will be used (soil params not needed for Wofost72_PP)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| lat | number | basin delineation | Latitude of grid cell center |
| lon | number | basin delineation | Longitude of grid cell center |
| hwsd_raster | file | data/soil/HWSD_RASTER/hwsd.bil | HWSD global soil raster |
| hwsd_mdb | file | data/forcing/huaihe_raw/soil/HWSD.mdb | HWSD properties database |
| sand_pct | number | HWSD or lab data | Sand fraction (%) |
| clay_pct | number | HWSD or lab data | Clay fraction (%) |
| organic_carbon | number | HWSD or lab data | Organic carbon (%) |
| bulk_density | number | HWSD or lab data | Bulk density (g/cm3) |

## Procedure

### Step 1: Extract soil properties from HWSD

```python
# Use the shared HWSD soil adapter (same source as VIC and DSSAT)
# This extracts sand, silt, clay, OC, bulk density for the location
from hwsd_soil_adapter import get_soil_properties
props = get_soil_properties(lat=52.0, lon=5.5,
    hwsd_raster='data/soil/HWSD_RASTER/hwsd.bil',
    hwsd_mdb='data/forcing/huaihe_raw/soil/HWSD.mdb')
```

**Expected result**: Dictionary with T_SAND, T_SILT, T_CLAY, T_OC, T_REF_BULK_DENSITY.

**If this fails**: Check HWSD file paths; verify lat/lon is on land (ocean cells have no soil data).

### Step 2: Convert to WOFOST soil parameters via pedotransfer functions

```python
# Pedotransfer functions (Wosten et al. 1999)
import math

sand = props['T_SAND']   # %
clay = props['T_CLAY']   # %
om = props['T_OC'] * 1.724  # OC% → OM%
bd = props['T_REF_BULK_DENSITY']  # g/cm3

# Wilting point (pF 4.2, -1500 kPa)
SMW = 0.001 + 0.26 * clay/100 + 0.05 * om/100
# Field capacity (pF 2.0, -10 kPa)
SMFCF = 0.02 + 0.37 * clay/100 + 0.15 * om/100 + 0.10 * (1 - sand/100 - clay/100)
# Saturation (porosity)
SM0 = 1.0 - bd / 2.65  # assuming particle density 2.65 g/cm3

# Clamp to valid ranges
SMW = max(0.01, min(SMW, 0.50))
SMFCF = max(SMW + 0.01, min(SMFCF, SM0 - 0.02))

# Hydraulic conductivity (simplified Cosby et al.)
K0 = 10.0 ** (1.26 - 0.0064 * clay - 0.0126 * sand * 0)  # cm/day, simplified
K0 = max(1.0, min(K0, 100.0))

soil_params = {
    'SMW': round(SMW, 3),
    'SMFCF': round(SMFCF, 3),
    'SM0': round(SM0, 3),
    'CRAIRC': round(max(0.02, SM0 - SMFCF - 0.02), 3),
    'K0': round(K0, 1),
    'SOPE': 1.0,      # max percolation rate root zone (cm/day)
    'KSUB': 1.0,      # max percolation rate subsoil (cm/day)
    'RDMSOL': 120.0,   # max rootable depth (cm) — adjust per soil
    'IFUNRN': 0,       # 0=no runoff curve, 1=USDA curve number
    'SSMAX': 0.0,      # max surface storage (cm)
    'SSI': 0.0,        # initial surface storage (cm)
    'WAV': 20.0,       # initial available water in profile (cm)
    'NOTINF': 0.0,     # fraction not infiltrating
    'SMLIM': round(SMFCF, 3),  # soil moisture limit
}
```

**Expected result**: Dictionary with all 14 required soil parameters.

### Step 3: Validate water limits

```python
assert soil_params['SMW'] < soil_params['SMFCF'], \
    f"SMW ({soil_params['SMW']}) must be < SMFCF ({soil_params['SMFCF']})"
assert soil_params['SMFCF'] < soil_params['SM0'], \
    f"SMFCF ({soil_params['SMFCF']}) must be < SM0 ({soil_params['SM0']})"
assert soil_params['SM0'] <= 0.65, \
    f"SM0 ({soil_params['SM0']}) unreasonably high (max porosity ~0.65)"
assert soil_params['CRAIRC'] < soil_params['SM0'] - soil_params['SMFCF'], \
    "CRAIRC must be < SM0 - SMFCF (available air at field capacity)"
```

**Expected result**: All assertions pass.

**If this fails**: See diagnostic triplet dt_009 (soil FC < WP).

### Step 4: Set rootable depth

RDMSOL should reflect actual soil depth. For shallow soils (rocky, hardpan), reduce from default 120 cm.

```python
# Adjust RDMSOL based on soil type
if clay > 60:
    soil_params['RDMSOL'] = 80.0  # heavy clay, shallow roots
elif sand > 80:
    soil_params['RDMSOL'] = 150.0  # sandy, deep roots possible
# Leave at 120.0 for medium textures
```

### Step 5: Save soil parameters

```python
import json
output_path = f'outputs/{run_name}/wofost/soil_params.json'
with open(output_path, 'w') as f:
    json.dump(soil_params, f, indent=2)
```

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| soil_params dict | `outputs/{run}/wofost/soil_params.json` | JSON with 14 keys; SMW < SMFCF < SM0 |

## Validation Checks

1. **Water limits ordered**: SMW < SMFCF < SM0 — violation means pedotransfer failed
   - Command: `assert soil['SMW'] < soil['SMFCF'] < soil['SM0']`
   - If unexpected: See diagnostic triplet dt_009

2. **SM0 physically possible**: SM0 <= 0.65 (porosity cannot exceed ~65%)
   - If SM0 > 0.65: bulk density is too low or miscalculated

3. **K0 positive**: K0 > 0 cm/day — zero K0 means no water movement
   - Typical range: 1-50 cm/day

4. **RDMSOL reasonable**: 10-300 cm — shallower than 10 cm is extreme; deeper than 300 cm is unrealistic

## Common Pitfalls

> **PITFALL**: Using DSSAT soil parameters directly
> DSSAT uses multi-layer SLLL/SDUL/SSAT per layer. WOFOST uses single-layer SMW/SMFCF/SM0 for the entire profile. You cannot simply copy DSSAT layer 1 values — you need a profile-average or pedotransfer from raw texture.
> **Do this instead**: Always use pedotransfer from HWSD sand/clay/OC to WOFOST parameters.
> See diagnostic triplet dt_009.

> **PITFALL**: Forgetting WAV (initial available water)
> WAV defaults to 0 if not set. Starting a simulation with completely dry soil can cause immediate crop death, especially for spring-sown crops.
> **Do this instead**: Set WAV to a reasonable value (10-50 cm) representing antecedent moisture. For VIC-coupled runs, use VIC soil moisture output to initialize WAV.

> **PITFALL**: Not needed for PP mode
> If running Wofost72_PP (potential production), soil parameters are ignored. Don't waste time optimizing soil params for PP runs.

---

*This skill document is part of the wofost-pcse-knowledge infrastructure.*
*Stage 2 of 8 | Tools: convert_hwsd_to_pcse_soil, validate_soil_params | Related triplets: dt_009*
