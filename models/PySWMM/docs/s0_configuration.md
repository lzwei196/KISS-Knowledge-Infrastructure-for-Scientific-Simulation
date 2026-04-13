# s0 — Configuration

## Purpose

Set up the SWMM model configuration: define simulation period, time steps,
flow units, routing method, and file paths. This stage produces the [OPTIONS],
[EVAPORATION], and [REPORT] sections of the .inp file.

## Inputs

| Input              | Source               | Format                    |
|--------------------|----------------------|---------------------------|
| Study area metadata| Site investigation   | Coordinates, timezone     |
| Simulation period  | User/project scope   | Start/end dates           |
| Time step settings | Engineering judgment | Seconds (routing), minutes (wet/dry) |
| Flow unit system   | Regional convention  | US (CFS) or SI (CMS)     |

## Outputs

| Output             | File           | Format                    |
|--------------------|----------------|---------------------------|
| [OPTIONS] section  | model.inp      | SWMM .inp text            |
| [EVAPORATION]      | model.inp      | SWMM .inp text            |
| [REPORT]           | model.inp      | SWMM .inp text            |

## Procedure

1. **Choose flow units:**
   - US Customary: CFS (cubic feet per second) is most common
   - SI Metric: CMS (cubic meters per second) or LPS (liters per second)
   - This choice determines ALL other unit expectations throughout the model

2. **Set simulation period:**
   ```
   START_DATE           01/01/2020
   START_TIME           00:00:00
   END_DATE             12/31/2020
   END_TIME             23:59:00
   REPORT_START_DATE    01/01/2020
   REPORT_START_TIME    00:00:00
   ```

3. **Configure time steps:**
   ```
   REPORT_STEP          00:05:00    ;; 5-min reporting interval
   WET_STEP             00:05:00    ;; Runoff step during wet periods
   DRY_STEP             01:00:00    ;; Runoff step during dry periods
   ROUTING_STEP         30          ;; Routing step in seconds
   ```

4. **Select routing method:**
   - `KINWAVE` — Fast, 1D kinematic wave. Good for steep, well-drained systems.
   - `DYNWAVE` — Full Saint-Venant. Required for surcharging, backwater, pressurized flow.
   - `STEADY` — Steady-state routing. Only for planning-level screening.

5. **Set infiltration model:**
   - `HORTON` — Exponential decay (most common)
   - `GREEN_AMPT` — Physics-based, needs soil data
   - `CURVE_NUMBER` — SCS method, simple but less dynamic

## Verification

- [ ] FLOW_UNITS matches all input data (rain, areas, elevations)
- [ ] Routing step satisfies Courant condition (Δt ≤ Δx / v_max)
- [ ] Report step is a multiple of routing step
- [ ] Simulation period covers all rainfall events of interest
- [ ] Dry-weather step is ≥ wet-weather step

## Traps

| Trap ID | Description                                      | Severity |
|---------|--------------------------------------------------|----------|
| UT-003  | Mixing feet/meters when setting elevations       | CRITICAL |
| UT-013  | Weir coefficient wrong for unit system            | HIGH     |
| DT-001  | ROUTING_STEP too large for DYNWAVE → instability | HIGH     |
| DT-003  | Missing ALLOW_PONDING with flat systems          | MEDIUM   |

## Example

```ini
[OPTIONS]
FLOW_UNITS           CFS
INFILTRATION         HORTON
FLOW_ROUTING         DYNWAVE
START_DATE           11/01/2015
START_TIME           00:00:00
END_DATE             11/04/2015
END_TIME             00:00:00
REPORT_STEP          00:05:00
WET_STEP             00:05:00
DRY_STEP             00:05:00
ROUTING_STEP         30
ALLOW_PONDING        NO
INERTIAL_DAMPING     PARTIAL
VARIABLE_STEP        0.75
MIN_SURFAREA         12.557
NORMAL_FLOW_LIMITED  BOTH
THREADS              1
```
