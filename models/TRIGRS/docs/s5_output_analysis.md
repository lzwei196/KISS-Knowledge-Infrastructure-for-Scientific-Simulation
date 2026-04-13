# Stage 5: Output Analysis and Interpretation

## Purpose

Parse, visualize, and interpret TRIGRS output files. The primary output is the factor of safety (FS) grid, which indicates slope stability. Additional outputs include pressure head profiles, water table depth, and infiltration rates. This stage extracts results to standard formats (CSV, GeoTIFF) for further analysis and validation.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| TRfs_min_*.asc | ESRI ASCII grid | TRIGRS run | Minimum factor of safety per cell |
| TRz_at_fs_min_*.asc | ESRI ASCII grid | TRIGRS run | Depth of minimum FS |
| TRp_at_fs_min_*.asc | ESRI ASCII grid | TRIGRS run | Pressure head at min FS |
| TRwater_depth_*.asc | ESRI ASCII grid | TRIGRS run | Water table depth |
| TRlist_z_p_fs_*.txt | Text list file | TRIGRS run | Depth profiles per cell |
| TrigrsLog.txt | Text file | TRIGRS run | Run log |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| results.csv | CSV | Cell-level FS, coordinates, pressure head |
| summary.json | JSON | Aggregate statistics |
| fs_map.png | Image | Factor of safety map |
| profile_plots/ | Image directory | Depth profiles at selected cells |

## Procedure

### Step 1: Parse output grids

```bash
python parse_trigrs_output.py \
    --output_dir data/output/ \
    --suffix run01 \
    --result_csv results.csv \
    --summary_json summary.json
```

### Step 2: Interpret factor of safety

| FS range | Classification | Color (maps) | Action |
|----------|---------------|------|--------|
| FS < 1.0 | **Unstable** | Red | Potential failure zone |
| 1.0 <= FS < 1.3 | **Marginally stable** | Yellow/Orange | Monitor closely |
| 1.3 <= FS < 1.5 | **Quasi-stable** | Light green | Generally safe |
| FS >= 1.5 | **Stable** | Green | Safe |
| FS = -9999 | No data | Gray | Outside domain or flat |

### Step 3: Analyze spatial patterns

Key patterns to check:
- **Unstable areas should correlate with steep slopes**: If flat areas show FS < 1, check soil parameters
- **FS should decrease over time during storm**: If FS increases, check rainfall sign
- **Highest instability at end of heaviest rainfall**: Compare FS grids across timesteps
- **Channel bottoms typically stable**: Very low slopes = high FS

### Step 4: Plot depth profiles

For cells of interest, examine how pressure head and FS vary with depth:

```python
import matplotlib.pyplot as plt
import numpy as np

# Parse list file for cell profiles
# Typical profile shows:
# - Pressure head increasing (becoming less negative) with time
# - FS decreasing as pore pressure rises
# - Minimum FS may occur at depth, not surface
```

### Step 5: Check mass balance

From TrigrsLog.txt:
```
# Good mass balance: infiltration + runoff ≈ rainfall
# Large mass balance error indicates numerical issues
```

## Verification

```python
import numpy as np
import json

# Load summary
with open('summary.json') as f:
    summary = json.load(f)

# Check FS statistics
for step, data in summary.get('fs_min', {}).items():
    stats = data.get('stats', {})
    print(f"Step {step}:")
    print(f"  Min FS: {stats.get('min_fs', 'N/A')}")
    print(f"  Mean FS: {stats.get('mean_fs', 'N/A')}")
    print(f"  % Unstable: {stats.get('pct_unstable', 'N/A')}")

    # Sanity checks
    assert stats.get('min_fs', 0) >= 0, "Negative FS is non-physical"
    assert stats.get('pct_unstable', 0) < 100, "100% unstable is suspicious"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| FS all very high (>100) | No instability detected | Check: cohesion too high? Slope in wrong units? |
| FS all < 1.0 | Everything unstable | Check: cohesion in Pa? uww/uws correct? |
| FS = -9999 everywhere | No valid output | Check input grids; all nodata? |
| FS same at all timesteps | No transient response | Check: t and capt in seconds? cri too low? |
| Pressure head unrealistic | Very large positive or negative values | Check: Ks, D0, rainfall intensity |

## Example

```python
import numpy as np
import matplotlib.pyplot as plt

# Read FS grid
data = np.loadtxt('data/output/TRfs_min_run01_1.asc', skiprows=6)
data[data == -9999] = np.nan

# Plot FS map
fig, ax = plt.subplots(figsize=(10, 8))
im = ax.imshow(data, cmap='RdYlGn', vmin=0, vmax=3)
ax.set_title('Factor of Safety - TRIGRS')
plt.colorbar(im, label='Factor of Safety')

# Add classification contours
ax.contour(data, levels=[1.0, 1.3, 1.5],
           colors=['red', 'orange', 'green'],
           linewidths=[2, 1, 0.5])

plt.savefig('fs_map.png', dpi=150, bbox_inches='tight')
print("Map saved to fs_map.png")
```
