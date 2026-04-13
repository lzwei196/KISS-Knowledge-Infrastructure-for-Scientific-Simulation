# s0: Model Structure Selection Guide

## Purpose

Choose the right Raven emulation template for a basin. Wrong choice produces plausible but suboptimal results (e.g., no snow process in a snow basin). This stage determines the entire model structure.

## Prerequisites

- Basin location (lat/lon) and approximate area
- Climate type (humid, semi-humid, semi-arid, cold, alpine)
- Whether the basin is snow-dominated
- Data availability (forcing variables: just P+T or full radiation/wind/humidity)

## Decision Matrix

| Climate | Data: P+T only | Data: Full forcing | Snow? |
|---------|---------------|-------------------|-------|
| **Humid** | GR4J (4 params) | HBV-EC | No -> GR4J, Yes -> HBV-EC |
| **Semi-humid** | GR4J or HYMOD | HBV-EC or SAC-SMA | No -> GR4J, Yes -> HBV-EC |
| **Semi-arid** | SAC-SMA | SAC-SMA | No -> SAC-SMA, Yes -> HYPR |
| **Cold/Alpine** | HBV-EC or UBC | HBV-EC | Always Yes -> HBV-EC or UBC |
| **Tropical** | GR4J | GR4J | No -> GR4J |
| **Prairie** | HYPR | HYPR | Yes -> HYPR |

## When to Use Each Template

### GR4J (4 parameters)
- **Best for**: Quick assessments, data-poor basins, humid/tropical climates
- **Avoid for**: Snow basins, basins needing sub-daily timestep
- **Advantage**: Only 4 calibration parameters — almost impossible to overfit

### HBV-EC (21 parameters)
- **Best for**: General-purpose, all climates, snow basins
- **Default choice**: When unsure, start with HBV-EC
- **Disadvantage**: Many parameters — risk of overfitting with short records

### HMETS (21 parameters)
- **Best for**: Canadian cold regions, advanced snow modeling
- **Advantage**: Sophisticated snow accumulation/melt processes

### SAC-SMA (16 parameters)
- **Best for**: US NWS operational basins, semi-arid regions
- **Advantage**: Well-tested soil moisture accounting for water supply

### HYMOD (5 parameters)
- **Best for**: Benchmarking, teaching, rapid prototyping
- **Avoid for**: Production use

### UBC (20 parameters)
- **Best for**: Mountainous basins with elevation banding
- **Advantage**: Designed for orographic precipitation and snowmelt

### HYPR (9 parameters)
- **Best for**: Canadian prairies with pothole/depression storage
- **Advantage**: Handles prairie-specific hydrology (connected/disconnected runoff)

## Procedure

1. Determine basin climate type and snow dominance
2. Check data availability (forcing variables)
3. Run: `python select_model_template.py --recommend --climate <type> --snow_dominated <true/false>`
4. For ensemble comparison: use `--list` to see all templates, then run `run_ensemble_comparison.py`

## Validation Checks

- [ ] Selected template has snow process if basin has significant winter snowpack
- [ ] PET method matches available forcing data
- [ ] Number of parameters is appropriate for available calibration data length

## Common Pitfalls

- **dt_012**: Using GR4J for a snow basin — no snowmelt, wrong seasonal pattern
- **dt_014**: Using PET_PENMAN_MONTEITH with only P+T forcing — Raven generates wind/humidity internally
- **dt_015**: Calibrating SAC-SMA (16 params) with only 3 years of data — overfitting
