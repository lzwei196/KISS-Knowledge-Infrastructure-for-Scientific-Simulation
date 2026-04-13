# Stage 5: Output Analysis

## Purpose

Parse LPJmL binary output files, convert to human-readable formats (CSV, NetCDF), compute crop yield metrics, and validate against observed data. This stage transforms raw binary output into actionable results.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Output binary files | `*.bin` (raw) | LPJmL output time series |
| Grid file | `output/grid.bin` | Grid cell coordinates |
| Globalflux | `output/globalflux.csv` | Global carbon/water fluxes |
| JSON metafiles | `output/*.json` | Output variable metadata (if `output_metafile: true`) |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| CSV time series | `.csv` | Extracted data per cell or global mean |
| NetCDF files | `.nc` | Gridded output for visualization |
| Yield tables | `.csv` | Crop yields in t DM/ha |
| Validation plots | `.png` | Observed vs simulated comparisons |

## Procedure

### 1. Convert binary to NetCDF (recommended for spatial analysis)

```bash
# Convert all binary outputs to NetCDF
bin/allbin2cdf output/lpjml_config_restart.json

# Or convert individual files
bin/bin2cdf -json output/lpjml_config_restart.json output/mnpp.bin output/npp.nc
```

### 2. Extract time series for specific cells

```bash
# Using parse_lpjml_output.py
python tools/parse_lpjml_output.py \
    --input output/pft_harvest.pft.bin \
    --grid output/grid.bin \
    --output harvest_cell27410.csv \
    --variable pft_harvestc \
    --cell 27410 \
    --firstyear 1901 --lastyear 2019 \
    --timestep annual --nbands 32

# By lat/lon
python tools/parse_lpjml_output.py \
    --input output/mnpp.bin \
    --grid output/grid.bin \
    --output npp_beijing.csv \
    --variable npp \
    --lat 39.9 --lon 116.4 \
    --timestep monthly
```

### 3. Convert harvest carbon to yield

LPJmL outputs crop harvest as **gC/m2/yr**. To get familiar yield units:

```
Yield (t DM/ha) = harvestc (gC/m2) / 0.45 * 0.01
Yield (t DM/ha) = harvestc (gC/m2) * 0.02222
```

- 0.45 = carbon fraction of dry biomass (biomass2c)
- 0.01 = m2 to hectare conversion (1 ha = 10000 m2)
- Typical ranges: wheat 2-8 t/ha, maize 3-12 t/ha, rice 3-10 t/ha

### 4. Validate against observations

Common validation datasets:
- **FAO**: National crop yields (fao.org/faostat)
- **GGCMI**: Gridded crop model intercomparison yields
- **Ray et al. (2012)**: Global crop yield trends
- **GRDC**: River discharge observations

Metrics for crop yield validation:
- **PBIAS** (Percent Bias): Acceptable if |PBIAS| < 25%
- **R²** (Coefficient of determination): Good if > 0.6
- **RMSE** (Root Mean Square Error): Compare to observed standard deviation
- **Yield gap**: Simulated vs potential yield

### 5. Analyze globalflux.csv

```python
import pandas as pd
df = pd.read_csv("output/globalflux.csv")
# Key columns: NEE, NPP, Rh, fire_emission, discharge
# All in GtC/yr or km3/yr
```

## Verification

- Total global NPP should be 50-70 GtC/yr
- Global discharge should be 35,000-45,000 km3/yr
- Wheat yields: 2-5 t/ha (global average ~3.5 t/ha)
- Maize yields: 3-8 t/ha (global average ~5.5 t/ha)
- Rice yields: 3-7 t/ha (global average ~4.5 t/ha)
- NEE should be near-zero for pre-industrial, -1 to -3 GtC/yr for present

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Binary byte order | Garbage values when reading | LPJmL uses little-endian (x86 native) |
| Missing scale factor | Values 1000x wrong | Check JSON metafile for `scale` field |
| Confusing gC/m2 with t/ha | Yields 100x too high | Apply / 0.45 * 0.01 conversion |
| Grid-scaled vs PFT-scaled | Values don't sum correctly | Check `grid_scaled` config setting |
| Harvest includes residuals | Yield too high | Use `pft_harvestc` (excludes residuals), not `harvestc` (includes) |
| Monthly vs annual output | Shape mismatch when reading | Check `timestep` in outputvars.cjson |
| Band order in PFT outputs | Wrong crop selected | Band order follows `landusemap` in config |
| Raw format lacks header | Cannot determine dimensions | Use JSON metafile or known grid size |

## Example

```bash
# Full output analysis workflow
# 1. Convert key outputs to NetCDF
bin/bin2cdf -json output/lpjml_config_restart.json \
    output/flux_harvest.bin output/harvest.nc

# 2. Extract wheat yield for a cell
python tools/parse_lpjml_output.py \
    --input output/pft_harvest.pft.bin \
    --grid output/grid.bin \
    --output wheat_yield.csv \
    --variable pft_harvestc \
    --lat 52.0 --lon 12.0 \
    --timestep annual --nbands 32 \
    --convert_yield

# 3. Quick statistics
bin/statclm output/flux_harvest.bin
bin/printglobal output/flux_harvest.bin output/grid.bin

# 4. Compare to FAO
python -c "
import pandas as pd
sim = pd.read_csv('wheat_yield.csv')
print(f'Mean wheat yield: {sim.temperate_cereals_rf.mean():.2f} t/ha')
"
```

## Output File Naming Convention

LPJmL output files follow this pattern:
- `m` prefix = monthly timestep (e.g., `mnpp.bin`)
- `a` prefix = annual timestep (e.g., `anbp.bin`)
- No prefix = annual (e.g., `vegc.bin`, `soilc.bin`)
- `pft_` prefix = PFT/CFT-specific (multi-band)
- `cft_` prefix = CFT-specific
- `.pft.bin` suffix = PFT-band output (32 bands)
- `.grid.bin` suffix = grid-scaled output (1 band)
