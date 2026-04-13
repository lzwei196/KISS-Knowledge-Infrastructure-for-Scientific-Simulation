# Raven Pipeline Workflow

## Pipeline Overview

```
s0: Template Selection ─┬─> s1: Basin/HRU Setup ─┬─> s2: Parameters (.rvp)
                        │                        │
                        ├─> s4: Model Structure   ├─> s3: Forcing (.rvt)
                        │                        │
                        │                        └─> s5: Initial Conditions (.rvc)
                        │                                    │
                        └────────────────────────────────────┘
                                                             │
                                                    s6: Execution (Raven.exe)
                                                             │
                                                    s7: Output Analysis
                                                             │
                                         ┌───────────────────┼───────────────────┐
                                         │                   │                   │
                                s8: Multi-Model       s9: Calibration    s10: VIC Comparison
                                    Ensemble              (DDS)
```

## Stage Dependencies

| Stage | Depends On | Can Parallel With |
|-------|-----------|-------------------|
| s0 | — | — |
| s1 | s0 | s4 |
| s2 | s1 | s3 |
| s3 | s1 | s2 |
| s4 | s0 | s1, s2, s3 |
| s5 | s1, s2 | s3 |
| s6 | s1-s5 | — |
| s7 | s6 | — |
| s8 | s1, s2, s3, s5 | — |
| s9 | s7 or s8 | — |
| s10 | s6 | s7 |

## Standard Workflow

### Single Model Run (10-15 min for a typical basin)

1. `select_model_template.py` — Choose HBV-EC (default) or another template
2. `build_rvh_from_shapefile.py` — Build HRU definition from shapefile + DEM
3. `build_rvp_parameters.py` — Build parameter file (reads class names from .rvh)
4. `convert_forcing_to_rvt.py` — Convert forcing with unit corrections
5. `generate_rvc_initial.py` — Set initial conditions
6. `validate_raven_inputs.py` — Cross-check all files
7. `run_raven.py` — Execute Raven
8. `parse_raven_output.py` — Extract results

### Multi-Model Ensemble (30-60 min)

Steps 1-5 with shared .rvh and .rvt, then:
9. `run_ensemble_comparison.py` — Run 5-8 templates in sequence
10. Review ranking and structural uncertainty

### Calibrated Model (2-4 hours)

Steps 1-9 (ensemble), then:
11. `calibrate_raven_dds.py` — DDS optimization of best template
12. `raven_vic_comparison.py` — Compare with VIC results

## Expected Runtimes

| Step | Typical | Notes |
|------|---------|-------|
| Template selection | <1s | Configuration only |
| HRU setup | 5-30s | DEM extraction |
| Parameters | <1s | Text file generation |
| Forcing conversion | 10s-5min | Depends on period and grid cells |
| Initial conditions | <1s | Text file generation |
| Validation | <1s | File parsing |
| Single Raven run | 5-60s | Depends on HRUs and period |
| Ensemble (5 models) | 30s-5min | 5x single run |
| DDS calibration (100 iter) | 10-100min | 100x single run |

## Coverage

| Stage | Tools | Skill Doc | Triplets |
|-------|-------|-----------|----------|
| s0 | select_model_template.py | s0_model_selection_skill.md | dt_012, dt_014 |
| s1 | build_rvh_from_shapefile.py | s1_basin_hru_setup_skill.md | dt_006, dt_007, dt_008 |
| s2 | build_rvp_parameters.py | — | dt_007, dt_008 |
| s3 | convert_forcing_to_rvt.py | s3_forcing_conversion_skill.md | dt_001-dt_005, dt_010, dt_025 |
| s4 | (via s0) | s4_process_algorithm_guide.md | dt_013, dt_014 |
| s5 | generate_rvc_initial.py | — | dt_023 |
| s6 | run_raven.py | — | dt_017, dt_018, dt_022 |
| s7 | parse_raven_output.py | — | dt_011 |
| s8 | run_ensemble_comparison.py | s8_model_intercomparison_skill.md | dt_024 |
| s9 | calibrate_raven_dds.py | s9_calibration_skill.md | dt_015, dt_016 |
| s10 | raven_vic_comparison.py | coupling_skill.md | dt_019, dt_020 |
| -- | validate_raven_inputs.py | — | all |
