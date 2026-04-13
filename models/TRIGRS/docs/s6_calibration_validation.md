# Stage 6: Calibration and Validation

## Purpose

Calibrate TRIGRS model parameters against observed landslide data and validate model performance. Calibration typically involves adjusting soil properties (Ks, c, phi, D0) to match observed landslide locations and timing. Validation uses metrics appropriate for binary classification (landslide / no-landslide).

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| TRIGRS output grids | ESRI ASCII | Stage 5 | FS, pressure head, water table |
| Landslide inventory | Shapefile / CSV | Field survey, remote sensing | Observed landslide locations |
| Rainfall event data | CSV | Meteorological records | Storm data for validation period |
| DEM | ESRI ASCII | Stage 1 | For spatial reference |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Calibrated parameters | tr_in.txt | Optimized soil parameters |
| Validation metrics | JSON / table | AUC-ROC, accuracy, TPR, FPR |
| ROC curve | PNG | Receiver operating characteristic |
| Calibration log | CSV | Parameter search history |

## Procedure

### Step 1: Prepare validation data

Convert landslide inventory to binary grid:
```python
import numpy as np

# Create binary landslide grid (1 = landslide, 0 = no landslide)
# Must match DEM dimensions
obs = np.zeros((nrows, ncols))
# Mark cells with observed landslides
for ls in landslide_inventory:
    row, col = geo_to_grid(ls.x, ls.y, dem_header)
    obs[row, col] = 1

print(f"Observed landslides: {obs.sum():.0f} cells")
```

### Step 2: Define FS threshold

The standard threshold is **FS = 1.0** for binary classification:
- FS < 1.0 -> predicted unstable (landslide)
- FS >= 1.0 -> predicted stable (no landslide)

Other thresholds (1.1, 1.3, 1.5) may improve performance depending on uncertainty.

### Step 3: Compute validation metrics

```python
def compute_metrics(fs_grid, obs_grid, threshold=1.0, nodata=-9999):
    """Compute binary classification metrics."""
    # Mask nodata
    valid = (fs_grid != nodata) & (obs_grid != nodata)
    fs = fs_grid[valid]
    obs = obs_grid[valid]

    # Binary predictions
    pred = (fs < threshold).astype(int)
    obs_bin = obs.astype(int)

    # Confusion matrix
    tp = ((pred == 1) & (obs_bin == 1)).sum()  # True positives
    fp = ((pred == 1) & (obs_bin == 0)).sum()  # False positives
    tn = ((pred == 0) & (obs_bin == 0)).sum()  # True negatives
    fn = ((pred == 0) & (obs_bin == 1)).sum()  # False negatives

    n = tp + fp + tn + fn
    accuracy = (tp + tn) / n if n > 0 else 0
    tpr = tp / (tp + fn) if (tp + fn) > 0 else 0  # Sensitivity/Recall
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0  # False positive rate
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0

    return {
        "accuracy": accuracy,
        "tpr": tpr,           # True positive rate (sensitivity)
        "fpr": fpr,           # False positive rate
        "precision": precision,
        "tp": int(tp), "fp": int(fp),
        "tn": int(tn), "fn": int(fn),
    }
```

### Step 4: ROC analysis

Vary the FS threshold from 0 to 5 and compute TPR vs FPR:

```python
thresholds = np.arange(0.0, 5.0, 0.1)
tpr_list, fpr_list = [], []
for th in thresholds:
    m = compute_metrics(fs_grid, obs_grid, threshold=th)
    tpr_list.append(m['tpr'])
    fpr_list.append(m['fpr'])

# AUC-ROC
from numpy import trapz
auc = abs(trapz(tpr_list, fpr_list))
print(f"AUC-ROC: {auc:.3f}")
# AUC > 0.7: acceptable; > 0.8: good; > 0.9: excellent
```

### Step 5: Calibrate parameters

**Sensitivity-ordered calibration approach:**

1. **K-sat** (most sensitive): Controls how fast rainfall infiltrates. Higher Ks = more infiltration = lower FS. Adjust first.
2. **Cohesion**: Direct effect on FS. Higher c = higher FS. Adjust second.
3. **Friction angle**: tan(phi) effect. Higher phi = higher FS.
4. **Water table depth**: Controls initial pore pressure.
5. **Diffusivity**: Controls timing of pressure response.

**Calibration strategy:**
- Start with literature/pedotransfer values
- Adjust Ks to match spatial extent of instability
- Adjust c and phi to match FS distribution
- Fine-tune timing with D0 and water table depth

### Step 6: Cross-validation

If multiple events are available:
1. Calibrate on Event A
2. Validate on Event B
3. Report both calibration and validation metrics

## Verification

```bash
# Run validation
python3 -c "
import numpy as np

# Load FS grid and observed landslide grid
fs = np.loadtxt('TRfs_min_run01_1.asc', skiprows=6)
obs = np.loadtxt('observed_landslides.asc', skiprows=6)

valid = (fs != -9999) & (obs != -9999)
pred = (fs[valid] < 1.0)
actual = (obs[valid] == 1)

tp = (pred & actual).sum()
fp = (pred & ~actual).sum()
fn = (~pred & actual).sum()
tn = (~pred & ~actual).sum()

print(f'TP={tp} FP={fp} FN={fn} TN={tn}')
print(f'Accuracy: {(tp+tn)/(tp+fp+fn+tn):.3f}')
print(f'TPR: {tp/(tp+fn):.3f}')
"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Comparing wrong timestep | Good FS map but poor validation | Use FS at observed failure time |
| DEM and inventory misaligned | Systematic offset in predictions | Check CRS and registration |
| Overfitting to one event | Excellent calibration, poor validation | Cross-validate on independent event |
| Ignoring spatial resolution | Fine grid shows many false positives | Match grid resolution to data quality |
| Binary comparison only | Losing continuous information | Use ROC/AUC analysis |

## Example

```python
# Typical validation results for a well-calibrated TRIGRS model:
# AUC-ROC: 0.75-0.85
# TPR at FS=1.0: 0.60-0.80 (60-80% of landslides predicted)
# FPR at FS=1.0: 0.10-0.30 (10-30% false alarm rate)
#
# Perfect prediction is rarely achievable due to:
# - Spatial heterogeneity in soil properties
# - Uncertainty in DEM resolution
# - 1D infiltration assumption
# - Infinite-slope model limitations
```
