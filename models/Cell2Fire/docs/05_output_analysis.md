# Stage 5: Output Analysis and Visualization

## Purpose

Parse Cell2Fire simulation outputs to compute burn probability maps, fire spread statistics, and risk metrics. Convert raw outputs into structured data for analysis and visualization.

## Inputs

| Input | Description |
|-------|-------------|
| Cell2Fire output folder | Directory with Messages, Grids, ROS, Intensity, etc. |
| Number of simulations | Must match `--nsims` used during execution |
| Instance folder | For cell size and coordinate reference |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `burn_probability.csv` | CSV grid | Burn probability per cell (0.0-1.0) |
| `all_messages.csv` | CSV table | All fire propagation messages across simulations |
| `summary.json` | JSON | Aggregate statistics |

## Procedure

### Step 1: Parse outputs

```bash
python parse_cell2fire_output.py \
    --output-folder ./results --nsims 10 \
    --instance-folder ./data/ScottAndBurgan/Vilopriu_2013-asc \
    --export-dir ./parsed
```

### Step 2: Compute burn probability

Burn probability (BP) is the fraction of simulations in which each cell burned:

```python
from parse_cell2fire_output import parse_final_grids, compute_burn_probability
import numpy as np

grids = parse_final_grids("./results", nsims=10)
bp = compute_burn_probability(grids)

# BP range: 0.0 (never burned) to 1.0 (burned in all simulations)
print(f"Max BP: {bp.max():.2f}")
print(f"Mean BP (burned cells only): {bp[bp > 0].mean():.2f}")
print(f"Cells with BP > 0.5: {np.sum(bp > 0.5)}")
```

### Step 3: Analyze fire spread

```python
from parse_cell2fire_output import parse_messages

messages = parse_messages("./results", nsims=10)

# Fire duration per simulation
duration = messages.groupby("sim")["time_period"].max()
print(f"Mean fire duration: {duration.mean():.1f} periods")

# Number of cells ignited per simulation
cells_per_sim = messages.groupby("sim")["receiver"].nunique()
print(f"Mean cells burned: {cells_per_sim.mean():.0f}")
```

### Step 4: Compute burned area

```python
import numpy as np

# Cell area in hectares
cellsize = 20  # meters (from ASC header)
cell_area_ha = (cellsize ** 2) / 10000.0

# Burned area per simulation
burned_per_sim = np.sum(grids > 0, axis=(1, 2))
area_ha = burned_per_sim * cell_area_ha

print(f"Mean burned area: {area_ha.mean():.1f} ha")
print(f"Max burned area: {area_ha.max():.1f} ha")
```

### Step 5: Visualize with matplotlib

```python
import matplotlib.pyplot as plt
import numpy as np

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Burn probability map
im1 = axes[0].imshow(bp, cmap="YlOrRd", vmin=0, vmax=1)
axes[0].set_title("Burn Probability")
plt.colorbar(im1, ax=axes[0], label="Probability")

# Single simulation fire scar
im2 = axes[1].imshow(grids[0], cmap="RdYlGn_r", vmin=0, vmax=1)
axes[1].set_title("Fire Scar (Simulation 1)")
plt.colorbar(im2, ax=axes[1], label="Burned")

plt.tight_layout()
plt.savefig("fire_analysis.png", dpi=150)
```

### Step 6: Export to GIS format (optional)

To create a georeferenced burn probability raster:
```python
# Write as ASC with original georeference
from convert_fuel_params import read_asc, write_asc

header, _ = read_asc("./instance/fuels.asc")
write_asc("burn_probability.asc", header, bp)
```

## Verification

1. **Burn probability range**: All values between 0.0 and 1.0.
2. **Spatial pattern**: Burns should originate from ignition points and spread with wind/slope.
3. **Burned area plausible**: Compare to historical fire sizes in the region.
4. **Fire duration**: Check number of periods vs. expected fire duration.
5. **Messages consistency**: Each receiver cell has at most one sender per simulation.

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Grid numbering mismatch | BP map shifted or wrong dimensions | Check grid CSV has correct nrows × ncols |
| Missing simulations | BP biased if some sims failed | Check for all MessagesFile{N}.csv |
| Zero burned cells | All simulations show no fire | Check ignition cell is burnable, weather has wind |
| All cells burned | BP = 1.0 everywhere | Reduce --max-fire-periods, check if landscape is all GR fuel |
| Message file format change | Parser returns empty dataframe | Check if newer C2F version changed CSV format |

## Example

Full analysis of 20 simulations on Vilopriu 2013:

```python
from parse_cell2fire_output import export_results

result = export_results(
    output_folder="./results",
    export_dir="./analysis",
    nsims=20,
    instance_folder="./data/ScottAndBurgan/Vilopriu_2013-asc",
)

print(f"Mean burned cells: {result['mean_burned_cells']:.0f}")
print(f"Mean burn fraction: {result['mean_burn_fraction']:.3f}")
print(f"Mean burned area: {result.get('mean_burned_area_ha', 'N/A'):.1f} ha")
```
