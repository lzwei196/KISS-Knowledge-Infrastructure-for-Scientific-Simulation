# S5: Output Analysis — Interpreting and Validating SimFire Results

## Purpose

Extract, analyze, and validate fire spread results from SimFire simulations.
Compute burn area statistics, fire perimeter metrics, spread rates, and
accuracy metrics when observed fire perimeter data is available.

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| Fire map array | S4 output | NPY/H5 | BurnStatus integers (0–5) |
| Pixel scale | Config | float | ft/pixel |
| Observed perimeter (optional) | BurnMD/NIFC | NPY/shapefile | Binary burned/unburned |
| Update rate | Config | float | min/step |

## Outputs

| Output | Format | Purpose |
|--------|--------|---------|
| `burn_statistics.csv` | CSV | Time series of burn metrics |
| `burn_summary.json` | JSON | Aggregate statistics |
| `burn_map.png` | PNG | Fire map visualization |
| `burn_progression.png` | PNG | Time series plot |

## Procedure

### Step 1: Load and Inspect Fire Map

```python
import numpy as np

fire_map = np.load("fire_map_final.npy")
print(f"Shape: {fire_map.shape}")
print(f"Unique values: {np.unique(fire_map)}")

# BurnStatus values
# 0=UNBURNED, 1=BURNING, 2=BURNED, 3=FIRELINE, 4=SCRATCHLINE, 5=WETLINE
```

### Step 2: Compute Burn Area

```python
pixel_scale_ft = 50  # from config
pixel_area_ft2 = pixel_scale_ft ** 2
pixel_area_acres = pixel_area_ft2 / 43560.0
pixel_area_ha = pixel_area_acres * 0.404686

burned = np.sum((fire_map == 1) | (fire_map == 2))
area_acres = burned * pixel_area_acres
area_ha = burned * pixel_area_ha

print(f"Burned pixels: {burned}")
print(f"Burned area: {area_acres:.1f} acres ({area_ha:.2f} ha)")
```

### Step 3: Compute Fire Perimeter

```python
fire_mask = ((fire_map == 1) | (fire_map == 2)).astype(int)
padded = np.pad(fire_mask, 1, mode="constant", constant_values=0)

# Count edge pixels (where fire meets non-fire)
edges = (
    np.abs(padded[1:-1, 1:-1] - padded[:-2, 1:-1]) +
    np.abs(padded[1:-1, 1:-1] - padded[2:, 1:-1]) +
    np.abs(padded[1:-1, 1:-1] - padded[1:-1, :-2]) +
    np.abs(padded[1:-1, 1:-1] - padded[1:-1, 2:])
)
perimeter_pixels = np.sum(edges > 0)
perimeter_ft = perimeter_pixels * pixel_scale_ft
perimeter_mi = perimeter_ft / 5280
print(f"Perimeter: {perimeter_mi:.2f} miles")
```

### Step 4: Accuracy Metrics (vs Observed)

When comparing against observed fire perimeters:

```python
observed = np.load("observed_perimeter.npy")  # 1=burned, 0=unburned
sim_burned = ((fire_map == 1) | (fire_map == 2)).astype(int)

TP = np.sum((sim_burned == 1) & (observed == 1))
FP = np.sum((sim_burned == 1) & (observed == 0))
FN = np.sum((sim_burned == 0) & (observed == 1))
TN = np.sum((sim_burned == 0) & (observed == 0))

# Sørensen coefficient (≈ F1 score for spatial data)
sorensen = 2 * TP / (2 * TP + FP + FN)

# Cohen's kappa
total = TP + FP + FN + TN
p_o = (TP + TN) / total
p_e = ((TP+FP)*(TP+FN) + (FN+TN)*(FP+TN)) / total**2
kappa = (p_o - p_e) / (1 - p_e)

# Commission error (over-prediction)
commission = FP / (TP + FP) if (TP + FP) > 0 else 0

# Omission error (under-prediction)
omission = FN / (TP + FN) if (TP + FN) > 0 else 0

print(f"Sørensen: {sorensen:.3f}")
print(f"Kappa: {kappa:.3f}")
print(f"Commission: {commission:.3f}")
print(f"Omission: {omission:.3f}")
```

**Interpretation guidelines:**
| Metric | Good | Acceptable | Poor |
|--------|------|------------|------|
| Sørensen | > 0.7 | 0.4–0.7 | < 0.4 |
| Kappa | > 0.6 | 0.3–0.6 | < 0.3 |
| Commission | < 0.3 | 0.3–0.5 | > 0.5 |
| Omission | < 0.3 | 0.3–0.5 | > 0.5 |

### Step 5: Visualization

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

colors = ["#2d5016", "#ff3300", "#8b4513", "#ffd700", "#ff8c00", "#4169e1"]
cmap = ListedColormap(colors)

fig, ax = plt.subplots(figsize=(10, 8))
ax.imshow(fire_map, cmap=cmap, vmin=0, vmax=5)
ax.set_title("SimFire Burn Map")

legend = [
    Patch(facecolor="#2d5016", label="Unburned"),
    Patch(facecolor="#ff3300", label="Burning"),
    Patch(facecolor="#8b4513", label="Burned"),
]
ax.legend(handles=legend, loc="lower right")
plt.savefig("burn_map.png", dpi=150)
```

### Step 6: Using the Parser Tool

```bash
python ki/tools/parse_simfire_output.py \
    --fire-map fire_map_final.npy \
    --pixel-scale 50 \
    --output-dir ./analysis/

# With observed comparison
python ki/tools/parse_simfire_output.py \
    --fire-map fire_map_final.npy \
    --pixel-scale 50 \
    --observed-perimeter observed.npy \
    --output-dir ./analysis/
```

## Verification

1. Burned area should be physically reasonable:
   - Small fires: < 100 acres
   - Medium fires: 100–10,000 acres
   - Large fires: > 10,000 acres

2. Perimeter-to-area ratio (compactness):
   - Circular fire: P/√A ≈ 3.54
   - Elongated fire (wind-driven): P/√A > 5

3. Spread rate cross-check:
   ```python
   # Estimate average spread rate from burn area and time
   runtime_min = 360  # 6 hours
   avg_radius_ft = np.sqrt(area_ft2 / np.pi)
   avg_ros_ftpm = avg_radius_ft / runtime_min
   print(f"Avg RoS: {avg_ros_ftpm:.1f} ft/min ({avg_ros_ftpm/88:.2f} mph)")
   # Typical: 1-50 ft/min for surface fires
   ```

## Traps

| Trap | Symptom | Severity | Fix |
|------|---------|----------|-----|
| Pixel scale wrong in analysis | Area off by orders of magnitude | **Silent** | Use same pixel_scale as config |
| Forgot ft² → acres conversion | Area appears huge | **Silent** | Divide by 43560 |
| Comparing maps of different sizes | Shape mismatch error | Fatal | Resample to common grid |
| H5 keys not sorted | Time series out of order | Degraded | Sort keys before processing |
| fire_map has float values | Comparison operators fail | Degraded | Cast to int first |

## Example

Complete analysis pipeline:
```bash
# Run simulation
python ki/tools/run_simfire.py --config config.yml --headless --output-dir ./run1/

# Parse output
python ki/tools/parse_simfire_output.py \
    --fire-map ./run1/fire_map_final.npy \
    --pixel-scale 50 \
    --output-dir ./analysis/

# Check results
cat ./analysis/burn_summary.json
```
