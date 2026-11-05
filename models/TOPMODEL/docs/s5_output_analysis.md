# Stage 5: Output Analysis and Validation

## Purpose

Parse TOPMODEL output files, convert units, compare with observed streamflow,
and compute standard hydrological performance metrics.

## Inputs

| Input | Description |
|-------|-------------|
| hyd.out | TOPMODEL hydrograph output, `it Qobs Qsim` (observed first), per-step depth in m |
| topmod.out | Detailed model state output |
| Observed discharge | Station data file (m³/s) |
| Basin area (km²) | For unit conversion |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| results.csv | CSV | Time series with dates, Q in m/hr and m³/s |
| metrics.json | JSON | NSE, KGE, PBIAS, r |
| validation_plot.png | PNG | Hydrograph and scatter plot |

## Procedure

### 1. Parse hyd.out

```python
# hyd.out format: it  Qobs  Qsim  (per-step depth, m); see topmodel.c results()
# Use the KI parser: it refuses 2-field, non-numeric or cut-off lines and steps
# that are not exactly 1..n. A well-formed nan/inf is returned as is: it means
# the run is broken, so drop the run, not the row (the parser CLI exits 2).
from parse_topmodel_output import parse_hyd_out
ts, q_sim_mhr, q_obs_mhr = parse_hyd_out('hyd.out')
# Missing observed days hold Qobs -9999 (listed in inputs.dat.provenance.json):
observed = q_obs_mhr != -9999.0
```

### 2. Convert to m³/s

```python
# Q_m3s = Q_mhr × basin_area_m² / 3600
basin_area_m2 = basin_area_km2 * 1e6
q_sim_m3s = q_sim_mhr * basin_area_m2 / 3600
q_obs_m3s = q_obs_mhr * basin_area_m2 / 3600
```

### 3. Load observed discharge (if not in hyd.out)

For Bengbu station 51080:
```python
# Format: stcd | dates(YYYY-MM-DD) | z | Q(m³/s) | name
obs = pd.read_csv(obs_file, sep='\t', header=None,
                   names=['stcd', 'date', 'z', 'Q', 'name'])
q_obs_m3s = obs['Q'].values
```

### 4. Align time series

- Match dates between simulation and observations
- Discard spinup period (typically first year)
- Missing observed days are the Qobs -9999 rows (see step 1); score only the other rows
- A nan/inf anywhere in hyd.out means a broken run: do not score it

### 5. Compute metrics

| Metric | Formula | Good | Acceptable |
|--------|---------|------|------------|
| NSE | 1 - Σ(sim-obs)² / Σ(obs-mean)² | >0.5 | >0 |
| KGE | 1 - √((r-1)²+(α-1)²+(β-1)²) | >0.5 | >0 |
| PBIAS | 100×Σ(sim-obs)/Σ(obs) | ±10% | ±25% |
| r | Pearson correlation | >0.7 | >0.5 |

### 6. Generate plots

- **Top panel**: Time series (obs=black, sim=blue #2563EB)
- **Bottom panel**: Scatter plot or flow duration curve
- **Annotations**: NSE, KGE, PBIAS in legend box

## Verification

- [ ] NSE > 0 (model better than mean)
- [ ] |PBIAS| < 50% (volume roughly correct)
- [ ] r > 0 (positive correlation)
- [ ] Peak timing approximately correct
- [ ] Water balance closes (check BAL in topmod.out)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Comparing m/hr sim with m³/s obs | NSE = -∞ | Convert to same units |
| Spinup included in metrics | Artificially low NSE | Discard first year |
| Daily obs vs hourly sim | Length mismatch | Aggregate sim to daily |
| Q_obs = 0 everywhere in hyd.out | Qobs not loaded | Provide obs file separately |
| Q_obs = -9999 on some rows | Missing observed days (sidecar `obs_missing_rows`) | Never score them; `calibrate_topmodel.py` and the parser CLI drop them |
| Simulated Q is steady/flat | Wrong TWI or parameters | Check subcat.dat, increase szm |

## Example

```bash
python tools/parse_topmodel_output.py \
  --hyd-file run/hyd.out \
  --topmod-file run/topmod.out \
  --start-date 1980-01-01 --dt-hours 24 \
  --basin-area-km2 121330 \
  --spinup-steps 365 \
  --output-csv results.csv
```
