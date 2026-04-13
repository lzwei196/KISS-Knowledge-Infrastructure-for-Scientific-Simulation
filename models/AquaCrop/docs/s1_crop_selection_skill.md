# Crop Selection & Parameterization -- Skill Document

> **Stage ID**: s1_crop_selection
> **Pipeline order**: 1 of 10
> **Depends on**: none

## Purpose

Select the crop type and configure phenological, canopy, and water productivity parameters. This stage determines what plant species the model simulates and how it responds to temperature, water stress, and management. If skipped, there is no crop to simulate. Choosing the wrong crop type or GDD base temperature produces physically plausible but scientifically wrong results (silent error).

## Prerequisites

Before starting this stage, verify:

- [ ] `aquacrop` package is installed (`pip install aquacrop`)
- [ ] Python environment is activated
- [ ] Target region and growing season are known (to select planting date)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| crop_name | string | User decision | Built-in crop name (e.g., 'Maize', 'MaizeGDD') or 'custom' |
| planting_date | string | User / regional calendar | Planting date in MM/DD format (e.g., '05/01') |
| harvest_date | string | Optional | Latest harvest date in MM/DD format |
| overrides | dict | Optional | Parameter overrides (e.g., `Tbase=10, HI0=0.50`) |

## Procedure

### Step 1: Choose between Calendar-Day and GDD crop variant

If the target region has **variable inter-annual temperature**, use the GDD variant (e.g., `MaizeGDD` instead of `Maize`). GDD variants adapt phenological timing to actual temperature accumulation. Calendar-day variants assume fixed development durations regardless of temperature.

**Rule of thumb**: Always use GDD variants unless you have calibrated calendar-day parameters for the specific site.

### Step 2: Create the Crop object

```python
from aquacrop import Crop
crop = Crop('MaizeGDD', planting_date='05/01')
```

**If this fails**: See diagnostic triplet dt_002 (wrong crop name).

### Step 3: Override parameters if needed

Pass changed parameters as keyword arguments. Only parameters in the `allowed_keys` set can be overridden.

```python
crop = Crop('MaizeGDD', planting_date='05/01', HI0=0.50, Tbase=10, WP=35.0)
```

**Key parameters for calibration**:
- `Tbase`: Base temperature for GDD (crop-specific: Maize=8, Wheat=0, Rice=8, Soybean=5)
- `Tupp`: Upper temperature for GDD (typically 30-35 C)
- `HI0`: Reference harvest index (0.30-0.60 for grain crops)
- `WP`: Normalized water productivity (15-40 g/m2 depending on crop)
- `CCx`: Maximum canopy cover (0.70-0.98)
- `CGC`: Canopy growth coefficient
- `CDC`: Canopy decline coefficient
- `p_up1..p_up4`: Upper water stress thresholds
- `PlantPop`: Plants per hectare

### Step 4: Validate crop parameters

Run tool `validate_crop_params` to check:
- `Tbase < Tupp`
- `Emergence < Senescence < Maturity` (for GDD crops)
- `0 < HI0 <= 1`
- `WP > 0`
- `0 < CCx <= 1`

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Crop object | in-memory | `crop.Name` matches chosen name; `crop.planting_date` is set |

## Validation Checks

1. **GDD parameter ordering**: `crop.Emergence < crop.Senescence < crop.Maturity`
   - If unexpected: Crop will not progress through growth stages correctly. See dt_002.

2. **Temperature thresholds**: `crop.Tbase < crop.Tupp`
   - If Tbase >= Tupp: GDD accumulation will be zero or negative. Fatal.

3. **Harvest index**: `0 < crop.HI0 <= 1`
   - If HI0 = 0: Yield will always be zero. See dt_014.

## Common Pitfalls

> **PITFALL**: Using wrong GDD base temperature for the crop
> This happens when using a generic Tbase (e.g., 10 C) for a crop that has a lower base (e.g., Wheat Tbase=0 C). The symptom is that the crop matures too slowly or too quickly. The yield may still be positive but the phenology timing is wrong.
> **Do this instead**: Check the crop-specific Tbase in `crop_params.py` or FAO documentation.
> See diagnostic triplet dt_002 for full details.

> **PITFALL**: Using calendar-day crop for multi-year simulation
> Calendar-day crops have fixed development timing regardless of temperature. In multi-year runs across different climate years, this produces identical phenology every year, which is unrealistic.
> **Do this instead**: Use the GDD variant (e.g., `MaizeGDD` instead of `Maize`).

> **PITFALL**: Planting date in wrong format
> The format is `MM/DD` (month/day with slash), not `DD/MM` or `YYYY-MM-DD`.
> Using the wrong format may silently swap month and day if both are <= 12.

---

*This skill document is part of the aquacrop-ospy-knowledge infrastructure.*
*Stage 1 of 10 | Tools used: select_crop, validate_crop_params | Related triplets: dt_002, dt_005, dt_014*
