# S7 — Calibration Guide

## Purpose

Guide the calibration of APSIM model parameters to improve agreement with
observed data. Calibration adjusts sensitive parameters within physically
plausible bounds to minimize the difference between simulated and observed
outputs.

## Inputs

| Input                | Format     | Source              |
|----------------------|-----------|---------------------|
| Simulation results   | CSV       | S5 output           |
| Observed data        | CSV       | Field trials        |
| Validation metrics   | JSON      | S6 output           |
| Parameter bounds     | table     | Literature / APSIM docs |

## Outputs

| Output               | Format     | Description                          |
|----------------------|-----------|--------------------------------------|
| Calibrated .apsimx   | JSON      | Updated simulation file              |
| Calibration log      | JSON      | Parameter changes and impact         |

## Procedure

### Calibration Priority Order

Calibrate in this order — each step addresses a specific model component:

**Priority 1: Phenology (timing)**
If flowering or maturity dates are wrong, yield will be wrong regardless of
other parameters.

| Parameter               | Units     | Range        | Effect                    |
|-------------------------|-----------|-------------|---------------------------|
| Thermal time targets    | °C·d      | crop-specific| Phase duration            |
| Vernalisation requirement| days     | 0-60        | Winter crop flowering     |
| Photoperiod sensitivity | h         | crop-specific| Daylength response        |
| Base temperature        | °C        | 0-12        | Development rate          |

**Priority 2: Biomass production (growth)**
If phenology is correct but yield is too high or low, adjust radiation
use efficiency and canopy parameters.

| Parameter               | Units     | Range        | Effect                    |
|-------------------------|-----------|-------------|---------------------------|
| RUE (Radiation Use Eff.)| g/MJ      | 0.8-2.0     | Biomass per MJ radiation  |
| Extinction coefficient  | —         | 0.3-0.7     | Light interception        |
| Maximum LAI             | m²/m²     | 3-10        | Canopy size limit         |
| Specific leaf area      | mm²/g     | 15000-30000 | Leaf area per unit mass   |

**Priority 3: Partitioning (allocation)**
If total biomass is right but grain yield is wrong, adjust harvest index
and allocation patterns.

| Parameter               | Units     | Range        | Effect                    |
|-------------------------|-----------|-------------|---------------------------|
| Harvest index           | 0-1       | 0.30-0.55   | Grain fraction of biomass |
| Grain filling rate      | g/°C·d    | crop-specific| Grain growth rate         |
| Grain maximum size      | g         | 0.02-0.06   | Individual grain weight   |

**Priority 4: Water balance**
If soil water dynamics are wrong, affecting yield through water stress.

| Parameter               | Units     | Range        | Effect                    |
|-------------------------|-----------|-------------|---------------------------|
| KL (root water uptake)  | /day      | 0.01-0.10   | Water extraction rate     |
| LL (crop lower limit)   | mm/mm     | ≥ LL15      | Extraction limit          |
| XF (root exploration)   | 0-1       | 0-1         | Root access to layer      |
| CN2Bare (curve number)  | —         | 60-95       | Runoff generation         |
| SWCON (drainage rate)   | 0-1       | 0.1-0.9     | Soil drainage             |
| Cona (evaporation)      | mm/d^0.5  | 2-5         | Stage 2 evaporation       |

**Priority 5: Nitrogen**
If N stress is over/under-predicted.

| Parameter               | Units     | Range        | Effect                    |
|-------------------------|-----------|-------------|---------------------------|
| Max/critical N conc.    | g/g       | crop-specific| N demand threshold        |
| KNO3 (N uptake rate)    | /day/ppm  | 0.01-0.10   | Nitrate uptake rate       |
| N fixation (legumes)    | —         | —           | Biological N fixation     |

### Calibration Method

1. **Manual calibration**: Adjust one parameter at a time, re-run, compare.
   Use the `--edit` flag for quick overrides:
   ```bash
   apsim run simulation.apsimx --edit overrides.txt
   ```

2. **Sensitivity analysis**: APSIM has built-in Morris and Sobol analysis:
   ```
   See Examples/Sensitivity/ for templates
   ```

3. **Automated optimisation**: APSIM includes an Optimisation model that can
   fit parameters to observed data using PEST or internal algorithms.

## Verification

- [ ] Each adjusted parameter is within its physical bounds
- [ ] Phenology is calibrated before yield
- [ ] Validation metrics improved (not just for calibration dataset)
- [ ] Independent validation dataset shows similar performance
- [ ] Changes are documented with justification

## Traps

- **Over-calibration**: Fitting too many parameters to too few data points.
  Rule of thumb: ≤ 3 parameters per observed variable.

- **Compensating errors**: Wrong phenology + wrong RUE can coincidentally
  give right yield for wrong reasons. Validate intermediate outputs.

- **Extrapolation**: Parameters calibrated for one site/climate may fail
  elsewhere. Test across sites.

- **Unit errors masking as calibration need**: If yield is 10× too high,
  check radiation units (dt_001) before adjusting RUE.

## Example

```bash
# Step 1: Check phenology
# Observed flowering: 15 Aug, Simulated: 1 Sep (16 days late)
# → Reduce thermal time target for Emergence→Flowering by ~200 °C·d

# Step 2: Check biomass
# Observed biomass at maturity: 12 t/ha, Simulated: 15 t/ha (25% high)
# → Reduce RUE from 1.5 to 1.2 g/MJ

# Step 3: Check yield
# Observed yield: 3.5 t/ha, Simulated: 4.2 t/ha (20% high)
# → Already improved by biomass fix. Fine-tune grain filling rate.
```
