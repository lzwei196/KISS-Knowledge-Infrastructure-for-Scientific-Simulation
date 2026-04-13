# S6: Output Analysis — Extracting and Visualizing MODFLOW Results

## Purpose

Read MODFLOW binary output files, extract head distributions, cell budgets, and water balance summaries. Generate maps, cross-sections, and time series for analysis and reporting.

## Inputs

| Input | Format | Contents |
|-------|--------|----------|
| `.hds` | Binary | Head values (ntime, nlay, nrow, ncol) |
| `.bud` / `.cbc` | Binary | Cell-by-cell flow budgets |
| `.lst` | Text | Listing file with volumetric budget |
| `.ddn` | Binary | Drawdown (optional) |
| Model object | FloPy | For grid geometry and plotting |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Head CSV | CSV | Head values at observation points |
| Budget summary | JSON | In/out flows per budget term |
| Water balance | JSON | Percent discrepancy |
| Head contour map | PNG | Spatial head distribution |
| Cross-section | PNG | Vertical head distribution |
| Time series | PNG/CSV | Head evolution at selected points |

## Procedure

### Reading Head File

```python
import flopy
import numpy as np

# Open head file (check precision! — dt_013)
hds = flopy.utils.HeadFile('model.hds', precision='single')

# Available time steps
times = hds.get_times()           # [1.0, 365.0, ...]
kstpkper = hds.get_kstpkper()     # [(0, 0), (0, 1), ...]

# Get data for specific time step
head = hds.get_data(kstpkper=(0, 0))  # (nlay, nrow, ncol)

# Get all data
all_heads = hds.get_alldata()  # (ntimes, nlay, nrow, ncol)

# CRITICAL: Mask dry cells (dt_012)
head[head < -1e29] = np.nan
```

### Reading Budget File

```python
cbb = flopy.utils.CellBudgetFile('model.bud')

# List available records
records = cbb.get_unique_record_names()
# e.g., [b'        STO-SS', b'   FLOW-JA-FACE', b'           CHD', ...]

# Get specific budget term
rch_data = cbb.get_data(text='RCH')

# Get specific discharge (velocity vectors)
spdis = cbb.get_data(text='DATA-SPDIS')[0]
qx, qy, qz = flopy.utils.postprocessing.get_specific_discharge(spdis, gwf)
```

### Water Balance from Listing File

```python
# MODFLOW 6
mfl = flopy.utils.Mf6ListBudget('model.lst')
df_flux, df_vol = mfl.get_dataframes()

# MODFLOW-2005
mfl = flopy.utils.MfListBudget('model.list')
df_flux, df_vol = mfl.get_dataframes()

# Check percent discrepancy
print(f"Flux discrepancy: {df_flux['PERCENT_DISCREPANCY'].iloc[-1]:.4f}%")
```

### Visualization

```python
import matplotlib.pyplot as plt

# Map view — head contours
fig, ax = plt.subplots(figsize=(10, 10))
pmv = flopy.plot.PlotMapView(model=gwf, ax=ax, layer=0)
pmv.plot_grid(colors='grey', linewidths=0.3)
arr = pmv.plot_array(head[0], cmap='viridis')
cs = pmv.contour_array(head[0], levels=10, linewidths=0.5)
ax.clabel(cs, inline=True, fontsize=8)
pmv.plot_bc('WEL', color='red', markersize=5)
pmv.plot_bc('RIV', color='blue')
plt.colorbar(arr, ax=ax, label='Head (m)', shrink=0.7)

# Cross-section
fig, ax = plt.subplots(figsize=(12, 4))
pxs = flopy.plot.PlotCrossSection(model=gwf, line={'row': 20}, ax=ax)
pxs.plot_array(head, cmap='viridis')
pxs.plot_grid(colors='grey', linewidths=0.3)

# Flow vectors on map
pmv.plot_vector(qx, qy, normalize=True, color='white', alpha=0.5)
```

## Verification

- [ ] Head values are within physically reasonable range (not -1e30 or extremely high)
- [ ] Water balance percent discrepancy < 1%
- [ ] Head contours show expected flow patterns (high→low along gradient)
- [ ] Budget in/out roughly balance for each term
- [ ] No systematic dry cells (unless expected)
- [ ] Output at all requested time steps

## Traps

| ID | Trap | Symptom | Fix |
|----|------|---------|-----|
| dt_012 | HDRY not masked | Extreme values (-1e30) in statistics | `head[head < -1e29] = np.nan` |
| dt_013 | Wrong binary precision | Garbage data, wrong array shapes | Try `precision='double'` |
| dt_009 | Zero-based layer index | Reading wrong layer | Layer 0 = top layer |
| — | Budget text has spaces | `get_data(text='RCH')` fails | Check exact name with `get_unique_record_names()` |
| — | Missing save_flows | No .bud file | Set `save_flows=True` in model creation |

## Example

```bash
python tools/parse_modflow_output.py \
    --workspace ./model_workspace \
    --version mf6 \
    --precision single \
    --extract heads,budget,balance \
    --plot \
    --output_dir ./results
```
