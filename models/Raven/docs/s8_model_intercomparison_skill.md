# s8: Multi-Model Ensemble Methodology

## Purpose

Run multiple Raven model structures on the same basin with identical forcing and compare results. This quantifies **structural uncertainty** — how much hydrological predictions depend on model choice. This is Raven's unique capability within HydroCraft.

## Prerequisites

- Completed stages s1-s5 (shared .rvh, .rvt, .rvc files)
- Compiled Raven.exe
- List of templates to compare

## Recommended Template Sets

### Quick comparison (3 models, ~5 min):
```
gr4j,hbv_ec,hymod
```
- GR4J: lumped, minimal, 4 params
- HBV-EC: standard reference, 21 params
- HYMOD: simple benchmark, 5 params

### Full comparison (5 models, ~15 min):
```
gr4j,hbv_ec,hmets,hymod,sac_sma
```

### Snow basin comparison (4 models):
```
hbv_ec,hmets,ubc,hypr
```
Only includes snow-capable templates.

## Procedure

1. **Generate shared files** (s1-s5) for the basin
2. **Run ensemble**:
```bash
python run_ensemble_comparison.py \
    --base_dir <path> --basin_name <name> \
    --templates gr4j,hbv_ec,hmets,hymod,sac_sma \
    --start_date 2000-01-01 --end_date 2010-12-31
```
3. **Review ranking**: The tool ranks models by NSE (if observed data) or by internal consistency metrics
4. **Compute structural uncertainty**: CV of mean discharge across models

## Interpreting Results

### With observed data:
- **NSE > 0.6**: Good model structure for this basin
- **NSE 0.3-0.6**: Acceptable, may improve with calibration
- **NSE < 0.3**: Wrong model structure or data issue
- Best template for calibration = highest NSE in ensemble

### Without observed data:
- **CV of mean Q < 0.2**: Models agree well — structural uncertainty is low
- **CV 0.2-0.5**: Moderate structural uncertainty — results depend on model choice
- **CV > 0.5**: High structural uncertainty — report ensemble range, not single model
- Use ensemble median as best estimate, envelope as uncertainty bounds

## Validation Checks

- [ ] All ensemble members ran successfully
- [ ] Each member has unique discharge time series (dt_024: shared .rvp check)
- [ ] Discharge is non-zero for all models
- [ ] Snow-capable templates have snow accumulation in winter (if applicable)

## Common Pitfalls

- **dt_024**: All models produce identical output — shared .rvp not regenerated per template
- **dt_012**: Including GR4J/HYMOD for snow basins — produces wrong seasonal pattern
- **dt_015**: Trying to calibrate all models — calibrate only the best 1-2

## Publication-Quality Output

For papers, report:
1. Ensemble mean and spread (shaded uncertainty band)
2. Individual model traces
3. NSE/KGE for each model (if observed data available)
4. Best model and why it suits this basin's hydrology
5. Structural uncertainty as CV of mean discharge
