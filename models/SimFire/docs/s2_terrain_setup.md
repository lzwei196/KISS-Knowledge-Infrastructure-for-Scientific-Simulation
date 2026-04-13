# S2: Terrain Setup — Fuel and Elevation Data Acquisition

## Purpose

Acquire or generate terrain data (fuel model classification and surface elevation) that
SimFire uses to compute fire spread rate via the Rothermel equation. This stage populates
the `FuelLayer` and `TopographyLayer` objects that provide per-pixel fuel parameters and
elevation values.

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| Geographic bounding box | User/config | lat, lon, height, width | degrees, meters |
| LandFire year | Config | integer | 2019, 2020, or 2022 |
| Fuel function (functional mode) | Config | string | "chaparral" or custom |
| Elevation function (functional mode) | Config | string | "flat", "gaussian", "perlin" |

## Outputs

| Output | Format | Units | Shape |
|--------|--------|-------|-------|
| Fuel model array | int array | FBFM-13 codes (1–13) | (H, W) pixels |
| Elevation array | float array | **feet** | (H, W) pixels |
| Fuel parameter objects | Fuel dataclass | lb/ft², ft, —, ft²/ft³ | per-pixel |

## Procedure

### Operational Mode (Real-World Data)

1. **Define bounding box** from config `operational` section:
   - `latitude`, `longitude`: top-left corner (decimal degrees)
   - `height`, `width`: area extent in **meters** (NOT feet)
   - `resolution`: 30 meters (LandFire native, must be 30)

2. **Download LandFire data** via the `landfire` Python package:
   - FBFM-13 layer: 13-class fuel behavior fuel model
   - ELEV layer: surface elevation in meters

3. **Convert fuel codes**:
   - Codes 1–13: standard burnable fuel models
   - Codes 91 (Urban), 92 (Snow/Ice), 93 (Water), 98 (Agriculture), 99 (Barren): non-burnable
   - NoData (-32768): mapped to non-burnable
   - Each code maps to a `Fuel(w_0, delta, M_x, sigma)` object

4. **Convert elevation to feet**:
   - CRITICAL: LandFire elevation is in **meters**
   - SimFire expects **feet**: multiply by 3.28084
   - Slope is computed as `np.gradient(elevation_ft, pixel_scale_ft)`

### Functional Mode (Procedural Generation)

1. **Topography functions**:
   - `flat()`: constant zero elevation everywhere
   - `gaussian(amplitude, mu_x, mu_y, sigma_x, sigma_y)`: bell-shaped hill
   - `perlin(octaves, persistence, lacunarity, seed, range_min, range_max)`: natural terrain

2. **Fuel functions**:
   - `chaparral(seed)`: uniform Chaparral (model 4) with optional w_0 jitter
   - Custom: any function returning `Fuel(w_0, delta, M_x, sigma)`

### 13 Standard FBFM Fuel Models

| ID | Name | w_0 (lb/ft²) | δ (ft) | M_x | σ (ft²/ft³) | Typical Habitat |
|----|------|---------------|--------|-----|-------------|-----------------|
| 1 | Short Grass | 0.034 | 1.0 | 0.12 | 3500 | Annual grasslands |
| 2 | Grass/Timber/Shrub | 0.092 | 1.0 | 0.15 | 2784 | Open pine with grass |
| 3 | Tall Grass | 0.138 | 2.5 | 0.25 | 1500 | Tall prairie grass |
| 4 | Chaparral | 0.230 | 6.0 | 0.20 | 1739 | Dense shrub (SoCal) |
| 5 | Brush | 0.046 | 2.0 | 0.20 | 1683 | Young shrub |
| 6 | Dormant Brush | 0.069 | 2.5 | 0.25 | 1564 | Hardwood slash |
| 7 | Southern Rough | 0.046 | 2.5 | 0.40 | 1552 | SE US understory |
| 8 | Closed Timber Litter | 0.069 | 0.2 | 0.30 | 1889 | Short-needle litter |
| 9 | Hardwood/Pine Timber | 0.133 | 0.2 | 0.25 | 2484 | Long-needle litter |
| 10 | Timber/Understory | 0.138 | 1.0 | 0.25 | 1764 | Timber with understory |
| 11 | Light Logging Slash | 0.069 | 1.0 | 0.15 | 1182 | Light debris |
| 12 | Medium Logging Slash | 0.184 | 2.3 | 0.20 | 1145 | Medium debris |
| 13 | Heavy Logging Slash | 0.321 | 3.0 | 0.25 | 1159 | Heavy debris |

## Verification

1. Check fuel array has valid codes:
   ```python
   fuel = np.load("fuel_array.npy")
   valid = set(range(0, 14))
   assert set(np.unique(fuel)).issubset(valid), f"Unexpected codes: {set(np.unique(fuel)) - valid}"
   ```

2. Check elevation is in feet (not meters):
   ```python
   elev = np.load("elevation_array.npy")
   # US continental range: -282 ft (Death Valley) to ~14,500 ft (Mt. Whitney)
   assert elev.max() < 20000, f"Max elevation {elev.max():.0f} ft — likely still in meters?"
   ```

3. Check burnable fraction:
   ```python
   burnable = np.sum((fuel >= 1) & (fuel <= 13)) / fuel.size
   print(f"Burnable: {burnable:.1%}")  # Should be > 0
   ```

## Traps

| Trap | Symptom | Severity | Fix |
|------|---------|----------|-----|
| Elevation left in meters | Slope factor too weak, fire ignores terrain | Silent | Multiply by 3.28084 |
| Fuel code 0 everywhere | Fire cannot spread anywhere | Fatal | Check LandFire download, bbox may be over water |
| Wrong LandFire year | Fuel data may not exist | Fatal | Use 2019, 2020, or 2022 |
| Area height/width in feet | Downloads tiny region | Degraded | Config area is in meters |
| Resolution ≠ 30 | API error or resampled data | Degraded | LandFire native is 30m only |
| FBFM-40 codes in data | Unmapped fuel models | Silent | SimFire only supports FBFM-13 |

## Example

Using `convert_landfire_to_simfire.py`:
```bash
python ki/tools/convert_landfire_to_simfire.py \
    --latitude 34.05 --longitude -118.25 \
    --height 3000 --width 3000 \
    --resolution 30 --year 2020 \
    --output-dir ./terrain_data/
```
