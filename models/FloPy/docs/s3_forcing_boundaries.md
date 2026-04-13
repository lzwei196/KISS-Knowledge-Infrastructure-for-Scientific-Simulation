# S3: Forcing & Boundary Conditions — Climate/Hydro Data to MODFLOW Packages

## Purpose

Convert external forcing data (precipitation, ET, river stages, pumping schedules) into MODFLOW boundary condition packages: RCH (recharge), EVT (evapotranspiration), RIV (river), WEL (wells), CHD (constant head), GHB (general head), and DRN (drain).

## Inputs

| Input | Format | Source | Units |
|-------|--------|--------|-------|
| Precipitation | CSV (date, mm/day) | CMFD, ERA5, gauges | mm/day or mm/hr |
| Evapotranspiration | CSV (date, mm/day) | ERA5, Penman-Monteith | mm/day |
| River stage/discharge | CSV (date, row, col, stage_m) | Gauging stations | m ASL |
| Well pumping | CSV (layer, row, col, rate) | Operational records | L/s, m³/hr, or m³/day |
| Constant head | List of (layer, row, col, head) | Lake levels, ocean | m ASL |

## Outputs

| Output | Consumed by | Units (model) |
|--------|-------------|---------------|
| Recharge arrays (per stress period) | RCH/RCHA package | m/day |
| ET arrays (per stress period) | EVT/EVTA package | m/day |
| River stress period data | RIV package | m, m²/day |
| Well stress period data | WEL package | m³/day |
| Constant head data | CHD package | m |

## Procedure

### Recharge (most common forcing)

1. **Load precipitation** data (CSV with date and mm/day)
2. **Apply recharge fraction**: R = P × f (typical f = 0.05-0.30 depending on soil/climate)
3. **CRITICAL: Convert mm/day → m/day** (divide by 1000!) — dt_002
4. **Create spatial array**: Uniform or spatially varying recharge per stress period
5. **Validate**: Max recharge < 0.05 m/day (50 mm/day) for most climates

```python
# Correct unit conversion
recharge_m_day = precip_mm_day / 1000.0 * recharge_fraction

# FloPy MODFLOW 6
rcha = flopy.mf6.ModflowGwfrcha(gwf, recharge=recharge_m_day)

# FloPy MODFLOW-2005
rch = flopy.modflow.ModflowRch(model, rech=recharge_m_day)
```

### Wells

1. **Load pumping data**: Layer, row, col, rate
2. **CRITICAL: Convert to m³/day** — dt_003
   - L/s × 86.4 = m³/day
   - m³/hr × 24 = m³/day
   - gal/min × 5.451 = m³/day
3. **CRITICAL: Extraction is NEGATIVE** in MODFLOW convention
4. **Zero-based indexing**: FloPy layer 0 = MODFLOW layer 1 — dt_009

```python
# Well at layer 1, row 5, col 10 pumping 500 m³/day
# FloPy uses zero-based: (0, 4, 9)
wel_data = {0: [[(0, 4, 9), -500.0]]}  # Negative = extraction!
wel = flopy.mf6.ModflowGwfwel(gwf, stress_period_data=wel_data)
```

### Rivers

1. **Define river cells**: Which grid cells contain the river
2. **Set stage**: River water surface elevation (m ASL, same datum as grid)
3. **Compute conductance**: C = K_bed × L × W / d_bed
4. **Set river bottom**: Must be < stage

```python
# [layer, row, col, stage, conductance, rbot]
riv_data = {0: [
    [(0, 10, 5), 30.0, 100.0, 28.0],  # stage=30m, cond=100m²/d, rbot=28m
    [(0, 10, 6), 29.5, 100.0, 27.5],
]}
riv = flopy.mf6.ModflowGwfriv(gwf, stress_period_data=riv_data)
```

## Verification

- [ ] Recharge units are m/day (not mm/day): max < 0.05 for most climates
- [ ] Well rates are negative for extraction, positive for injection
- [ ] River stage > river bottom for all cells
- [ ] River conductance > 0 and physically reasonable (10-1000 m²/day typical)
- [ ] Zero-based indexing: first cell = (0, 0, 0)
- [ ] Stress period data covers all model periods

## Traps

| ID | Trap | Symptom | Fix |
|----|------|---------|-----|
| dt_002 | Recharge in mm/day not m/day | Heads rise unrealistically, flooding | Divide by 1000 |
| dt_003 | Well rates in L/s not m³/day | Pumping effect 86× too small | Multiply by 86.4 |
| dt_005 | River conductance wrong | River-aquifer exchange wrong magnitude | C = K_bed × L × W / d |
| dt_006 | Stage/head datum mismatch | Gradient reversed, wrong flow direction | Use consistent datum (m ASL) |
| dt_008 | ET in mm/day not m/day | ET effect 1000× too large | Divide by 1000 |
| dt_009 | 1-based indexing | Boundaries in wrong cells | Subtract 1 from all indices |

## Example

```bash
python tools/convert_forcing_to_modflow.py \
    --precip data/precip_mm_day.csv \
    --wells data/wells.csv \
    --rivers data/rivers.csv \
    --grid_meta grid_output/grid_metadata.json \
    --recharge_fraction 0.15 \
    --length_unit meters \
    --output_dir forcing/
```
