# S6 — Output Parsing and Analysis

## Purpose

Extract, analyze, and visualize Alpine3D simulation results. Convert gridded ARC
ASCII output into time series, compute domain statistics, and compare with
observations for validation.

## Inputs

| Item | Format | Source | Required |
|------|--------|--------|----------|
| Grid output files | ARC ASCII | Stage s5 output | Yes |
| Time series output | SMET | Stage s5 output (at POIs) | Optional |
| Observation data | CSV/SMET | Station records | For validation |

## Outputs

| File | Format | Purpose |
|------|--------|---------|
| Time series CSV | CSV | Point or domain-averaged time series |
| Domain statistics CSV | CSV | Min/max/mean/std per timestep |
| Basin-integrated CSV | CSV | Total water volume per timestep |
| Validation plots | PNG | Observed vs. simulated comparison |

## Procedure

### 1. Parse Gridded Output

```bash
# Domain-wide statistics for SWE and snow depth
python tools/parse_alpine3d_output.py \
    --grid-dir ./output/grids/ \
    --params SWE HS TA \
    --output domain_stats.csv \
    --mode domain

# Point extraction at a specific pixel
python tools/parse_alpine3d_output.py \
    --grid-dir ./output/grids/ \
    --params SWE HS \
    --output point_ts.csv \
    --mode point --row 40 --col 50

# Basin-integrated SWE (total snow volume in m³)
python tools/parse_alpine3d_output.py \
    --grid-dir ./output/grids/ \
    --params SWE \
    --output basin_swe.csv \
    --mode basin --cellsize 25
```

### 2. Read Time Series Output (POI .met files)

The SMET time series files at POIs contain the full energy and mass balance:

```python
import csv

def read_smet_timeseries(filepath):
    """Read a SMET time series file into a list of dicts."""
    records = []
    fields = []
    in_data = False

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line.startswith("fields"):
                fields = line.split("=")[1].strip().split()
            elif line == "[DATA]":
                in_data = True
                continue
            elif in_data and line:
                vals = line.split()
                record = {}
                for i, field in enumerate(fields):
                    if i < len(vals):
                        if field == "timestamp":
                            record[field] = vals[i]
                        else:
                            try:
                                record[field] = float(vals[i])
                            except ValueError:
                                record[field] = None
                records.append(record)
    return records, fields
```

### 3. Key Output Variables

#### Gridded Parameters (GRIDS_PARAMETERS)

| Parameter | Unit | Description |
|-----------|------|-------------|
| HS | m | Snow depth |
| SWE | kg/m² | Snow water equivalent |
| TA | K | Air temperature (interpolated) |
| TSS | K | Snow surface temperature |
| ISWR | W/m² | Incoming shortwave radiation |
| ILWR | W/m² | Incoming longwave radiation |
| RSNO | kg/m³ | Snow mean density |
| MS_SNOWPACK_RUNOFF | kg/m² | Runoff from snowpack |
| MS_SOIL_RUNOFF | kg/m² | Runoff through soil bottom |
| ET | kg/m² | Evapotranspiration |

#### Time Series Fields (.met files)

| Category | Fields |
|----------|--------|
| Energy | lw_in, lw_out, sw_in, sw_out, qs (sensible), ql (latent), qg (ground) |
| Mass | psum_snow, psum_rain, evaporation, sublimation, runoff, melt |
| State | HS, SWE, rho (density), n_layers, T_surface |
| Stability | S_n (natural), S_s (skier), S_d (deformation) |

### 4. Validation Against Observations

#### Compute Standard Metrics

```python
def compute_metrics(observed, simulated):
    """Compute NSE, KGE, RMSE, PBIAS for paired time series."""
    n = len(observed)
    if n == 0:
        return {}

    obs_mean = sum(observed) / n
    sim_mean = sum(simulated) / n

    # NSE
    ss_res = sum((o - s) ** 2 for o, s in zip(observed, simulated))
    ss_tot = sum((o - obs_mean) ** 2 for o in observed)
    nse = 1 - ss_res / ss_tot if ss_tot > 0 else float('-inf')

    # RMSE
    rmse = (ss_res / n) ** 0.5

    # PBIAS (%)
    pbias = 100 * sum(s - o for o, s in zip(observed, simulated)) / sum(observed) if sum(observed) != 0 else 0

    # Pearson correlation
    cov = sum((o - obs_mean) * (s - sim_mean) for o, s in zip(observed, simulated)) / n
    std_o = (sum((o - obs_mean) ** 2 for o in observed) / n) ** 0.5
    std_s = (sum((s - sim_mean) ** 2 for s in simulated) / n) ** 0.5
    r = cov / (std_o * std_s) if std_o > 0 and std_s > 0 else 0

    # KGE
    alpha = std_s / std_o if std_o > 0 else 0
    beta = sim_mean / obs_mean if obs_mean != 0 else 0
    kge = 1 - ((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2) ** 0.5

    return {
        "NSE": round(nse, 4),
        "KGE": round(kge, 4),
        "RMSE": round(rmse, 4),
        "PBIAS": round(pbias, 2),
        "r": round(r, 4),
        "n": n,
    }
```

#### Expected Performance Ranges

| Variable | Good NSE | Good RMSE | Notes |
|----------|---------|-----------|-------|
| Snow depth (HS) | > 0.7 | < 0.20 m | Highly site-dependent |
| SWE | > 0.7 | < 50 kg/m² | Depends on elevation |
| Runoff | > 0.6 | — | Daily discharge |
| Surface temperature | > 0.8 | < 3 K | Diurnal cycle matters |

### 5. Create Validation Plots

```python
import matplotlib.pyplot as plt

def plot_validation(timestamps, observed, simulated, param_name, metrics, output_path):
    """Create observed vs simulated time series plot."""
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(timestamps, observed, 'k-', linewidth=1.5, label='Observed')
    ax.plot(timestamps, simulated, color='#2563EB', linewidth=1.2, label='Simulated')
    ax.set_xlabel('Date')
    ax.set_ylabel(param_name)
    ax.legend()

    # Add metrics box
    metrics_text = '\n'.join([f'{k}: {v}' for k, v in metrics.items()])
    ax.text(0.98, 0.95, metrics_text, transform=ax.transAxes,
            verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
            fontsize=9, family='monospace')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
```

## Verification

```bash
# Check output CSV was created and has data
wc -l domain_stats.csv
head -5 domain_stats.csv

# Verify SWE is physically reasonable
python3 -c "
import csv
with open('domain_stats.csv') as f:
    reader = csv.DictReader(f)
    swe_vals = [float(r['SWE_mean']) for r in reader if r.get('SWE_mean')]
    print(f'SWE mean range: {min(swe_vals):.1f} to {max(swe_vals):.1f} kg/m²')
    print(f'Peak SWE: {max(swe_vals):.1f} kg/m² — ' + ('OK' if max(swe_vals) < 2000 else 'CHECK!'))
"

# Verify time series completeness
python3 -c "
import csv
with open('domain_stats.csv') as f:
    rows = list(csv.DictReader(f))
    print(f'Timesteps: {len(rows)}')
    print(f'First: {rows[0][\"timestamp\"]}')
    print(f'Last: {rows[-1][\"timestamp\"]}')
"
```

## Traps

| Issue | Symptom | Fix |
|-------|---------|-----|
| SWE in wrong units | Values 1000× too high/low | Check GRIDS_PARAMETERS spelling |
| No grid files | Empty output directory | Check GRIDS_WRITE = TRUE |
| Missing timesteps | Gaps in time series | Check simulation log for errors |
| NODATA pollution | Statistics include -9999 | Filter NODATA_value properly |
| Timestamp parsing | Wrong date extraction | Verify filename format |

## Example

```bash
# Full analysis pipeline
python tools/parse_alpine3d_output.py \
    --grid-dir ./output/grids/ \
    --params SWE HS ISWR TA \
    --output analysis/domain_stats.csv \
    --mode domain

python3 -c "
import csv
with open('analysis/domain_stats.csv') as f:
    rows = list(csv.DictReader(f))
    for r in rows[-5:]:
        print(f'{r[\"timestamp\"]}  SWE={r[\"SWE_mean\"]}  HS={r[\"HS_mean\"]}')
"
```
