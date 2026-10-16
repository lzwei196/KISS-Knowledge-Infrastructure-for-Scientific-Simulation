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

### Step 2: Convert to WOFOST soil parameters — use the SHARED hydraulics, never a private formula

> **dt_v007 (fixed 2026-09-12).** This step used to teach three linear formulas labelled
> "Wösten et al. (1999)". They were NOT Wösten's method, and against an independent Saxton &
> Rawls (2006) reference they gave soil with a median **0.58×** the real plant-available water.
> Re-running the C01 maize case with correct soil moved rainfed yield **+7.3% / +35.0% / 0%**
> over three seasons. Do not re-derive these numbers from a formula in a doc. Use the tool, which
> uses the shared library:

```bash
# stdout = the soil JSON (logs go to stderr). SOIL_PARAMS_JSON also makes the tool write
# soil_params.json.provenance.json (texture used, PTF source, units) next to it.
SOIL_PARAMS_JSON=soil_params.json \
  python tools/s2_soil_params/convert_hwsd_to_pcse_soil.py <lat> <lon> > soil_params.json
```

Then load the result. Every later step uses these two names (`soil_params`, `texture`):

```python
import json
with open('soil_params.json') as f:
    soil_params = json.load(f)     # 8 soil-hydraulic keys: SMW SMFCF SM0 CRAIRC K0 SOPE KSUB RDMSOL
with open('soil_params.json.provenance.json') as f:
    texture = json.load(f)['texture_input']   # sand/clay/silt/oc (%) and bd the tool used
```

If you must build the soil by hand (no tool run), make the SAME 8-key dict from the shared
library. This is what the tool does:

```python
from ki_tools_common.soil_utils import lookup_hwsd
props = lookup_hwsd(lat, lon)          # dominant HWSD component WITH usable texture (fixed 2026-09-11)
hyd   = props['hydraulics']            # shared Rawls-1982 class table, the same values every crop KI uses
texture = {'sand': props['sand'], 'clay': props['clay'], 'silt': props['silt'], 'oc': props['oc']}
soil_params = {
    'SMW':   round(float(hyd['wilting_point']), 4),
    'SMFCF': round(float(hyd['field_capacity']), 4),
    'SM0':   round(float(hyd['saturation']), 4),
    'CRAIRC': 0.06,                    # critical soil air content (standard WOFOST value), NOT SM0-SMFCF
    'K0':    round(float(hyd['ksat_cm_hr']) * 24.0, 2),   # UNITS: shared table is cm/hr, WOFOST K0 is cm/DAY
    'SOPE':  1.0,
    'KSUB':  1.0,
    'RDMSOL': 120.0,                   # set by texture in Step 4
}
```

Do NOT put IFUNRN, NOTINF, SSI, SSMAX, WAV or SMLIM in `soil_params`: in PCSE 6.0 they come from
`WOFOST72SiteDataProvider`, and having them in both places raises "Duplicate parameter found"
(dt_v003).

The shared table is itself a coarse 12-class lookup at ~0.86× the continuous reference — good
enough, and honest, but not perfect. Upgrading it is a `ki_tools_common` job, not a WOFOST one.

**Never** write `SMW = 0.001 + 0.26*clay ...` or any other private pedotransfer here. If you find
one in a WOFOST tool, it is the bug this note exists to prevent.

### Step 3: Validate water limits

```bash
python tools/s2_soil_params/validate_soil_params.py soil_params.json   # exit 0 = pass, 2 = a check failed
```

or, in the same Python session:

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

RDMSOL should reflect actual soil depth. The tool already applies the texture rule below; repeat
it only for a hand-built dict, or lower it further when you know the soil is shallow (rocky, hardpan).

```python
# Adjust RDMSOL based on soil type (same rule as convert_hwsd_to_pcse_soil.py)
if texture['clay'] > 60:
    soil_params['RDMSOL'] = 80.0   # heavy clay, shallow roots
elif texture['sand'] > 80:
    soil_params['RDMSOL'] = 150.0  # sandy, deep roots possible
else:
    soil_params['RDMSOL'] = 120.0  # medium textures
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
| soil_params dict | `outputs/{run}/wofost/soil_params.json` | JSON with the 8 soil-hydraulic keys; SMW < SMFCF < SM0 |

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
