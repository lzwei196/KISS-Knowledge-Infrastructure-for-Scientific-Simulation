# s4 — Meteorological Forcing

## Purpose

Convert rainfall and evaporation data from global reanalysis, satellite,
or station sources into SWMM [TIMESERIES] and [RAINGAGES] format. This is
the primary hydrological driver — errors here propagate to ALL downstream
results.

## Inputs

| Input              | Source                 | Format                      |
|--------------------|------------------------|-----------------------------|
| Rainfall           | Station, ERA5, GPM, CMFD | CSV or NetCDF            |
| Evaporation        | Station, PET model     | CSV (optional)              |
| Temperature        | Station, ERA5          | CSV (for snowmelt models)   |
| Wind speed         | Station, ERA5          | CSV (for evaporation)       |

## Outputs

| Output             | File           | Format                    |
|--------------------|----------------|---------------------------|
| [TIMESERIES]       | model.inp      | SWMM .inp text            |
| [RAINGAGES]        | model.inp      | SWMM .inp text            |
| [EVAPORATION]      | model.inp      | SWMM .inp text            |
| [TEMPERATURE]      | model.inp      | SWMM .inp text (optional) |

## Procedure

1. **Obtain rainfall data** in one of:
   - Station gauge records (highest accuracy, sparse coverage)
   - ERA5 reanalysis (hourly, 0.25°, global)
   - GPM IMERG (30-min, 0.1°, 60°N–60°S)
   - CMFD (3-hourly, 0.1°, China only)

2. **Convert to intensity units:**

   SWMM expects rainfall as **INTENSITY** (in/hr or mm/hr), not depth.

   | Source Format    | Conversion to in/hr         | Conversion to mm/hr      |
   |------------------|-----------------------------|--------------------------|
   | mm/hr            | × (1/25.4)                  | × 1.0 (no change)       |
   | mm/day           | × (1/25.4) × (1/24)         | × (1/24)                |
   | mm/timestep (3h) | ÷ 3 → mm/hr, then convert   | ÷ 3                     |
   | in/hr            | × 1.0 (no change)            | × 25.4                  |
   | in/day           | × (1/24)                     | × 25.4 / 24             |

   **CRITICAL**: If you provide mm (depth per timestep) when SWMM expects
   mm/hr (intensity), results will be wrong by a factor equal to the timestep
   in hours. For hourly data this is 1:1, but for daily data it's 24x.

3. **Format as SWMM TIMESERIES:**
   ```
   [TIMESERIES]
   ;;Name           Date       Time       Value
   RG1              01/15/2020 00:00      0.0
   RG1              01/15/2020 00:15      0.12
   RG1              01/15/2020 00:30      0.35
   ```

4. **Define rain gage:**
   ```
   [RAINGAGES]
   ;;Name           Type      Interval   SCF    Source
   RG1              INTENSITY 0:15       1.0    TIMESERIES RG1
   ```

   - `Type`: INTENSITY (rate) or VOLUME (depth per interval)
   - `Interval`: Must match timeseries resolution (e.g., 0:15 for 15-min)
   - `SCF`: Snow catch factor (1.0 if no snow correction)

5. **Set evaporation:**
   ```
   [EVAPORATION]
   CONSTANT     0.1      ;; 0.1 in/day (US) or mm/day (SI)
   DRY_ONLY     NO
   ```
   Or use monthly/timeseries values for better accuracy.

## Verification

- [ ] Rain gage interval matches timeseries resolution
- [ ] Rainfall values are intensity (rate), not cumulative depth
- [ ] Maximum intensity is physically plausible:
  - US: < 15 in/hr for 5-min, < 4 in/hr for 1-hr
  - SI: < 380 mm/hr for 5-min, < 100 mm/hr for 1-hr
- [ ] Total precipitation matches source data after unit conversion
- [ ] No gaps in timeseries during simulation period
- [ ] Evaporation units match flow unit system

## Traps

| Trap ID | Description                                          | Severity |
|---------|------------------------------------------------------|----------|
| UT-001  | Rainfall in mm/day instead of mm/hr → 24x too low   | CRITICAL |
| UT-001b | Rain depth (mm) when intensity (mm/hr) expected      | CRITICAL |
| UT-010  | Evaporation in in/hr instead of in/day → 24x too high| HIGH    |
| DT-007  | Rain gage interval ≠ timeseries resolution → missed rain | HIGH |
| DT-008  | TIMESERIES timestamps not monotonically increasing   | HIGH     |
| DT-009  | Missing rainfall during peak design storm            | MEDIUM   |

## Example

```ini
[RAINGAGES]
;;Name           Type      Interval   SCF    Source
RG1              INTENSITY 0:15       1.0    TIMESERIES SCS_24h_1in

[TIMESERIES]
;;Name           Date       Time       Value
SCS_24h_1in      01/01/2020 00:00      0.0175
SCS_24h_1in      01/01/2020 00:15      0.0175
SCS_24h_1in      01/01/2020 00:30      0.0175
;; ... continues for 24 hours
SCS_24h_1in      01/01/2020 09:30      0.236   ;; peak intensity
SCS_24h_1in      01/01/2020 09:45      0.612   ;; peak intensity
SCS_24h_1in      01/01/2020 10:00      0.136
;; ... tapers off
SCS_24h_1in      01/01/2020 24:00      0.0

[EVAPORATION]
CONSTANT     0.0
DRY_ONLY     NO
```

## Tool

```bash
python ki/tools/convert_forcing_to_inp.py \
    --input rain_data.csv \
    --output timeseries_block.txt \
    --gage-name "RG1" \
    --input-units "mm/hr" \
    --target-units "in/hr" \
    --interval 15
```
