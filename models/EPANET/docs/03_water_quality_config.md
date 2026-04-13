# Stage 3-5: Water Quality Configuration and Simulation Options

## Purpose

Configure EPANET's water quality analysis (chemical fate/transport, water age, or source tracing), set reaction coefficients, define operational controls, and establish simulation timing parameters.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Quality type selection | Analysis objectives | NONE / CHEMICAL / AGE / TRACE |
| Bulk reaction coefficient | Lab tests, literature | 1/day (1st-order) |
| Wall reaction coefficient | Pipe material data, calibration | ft/day or m/day (1st-order) |
| Source quality data | Treatment plant records | mg/L or µg/L |
| Control rules | Operating procedures, SCADA logic | IF/THEN/ELSE text |
| Simulation period | Analysis objectives | Hours |

## Outputs

| Output | Format | Used By |
|--------|--------|---------|
| [QUALITY] section | .inp text | EPANET solver |
| [REACTIONS] section | .inp text | EPANET solver |
| [SOURCES] section | .inp text | EPANET solver |
| [CONTROLS]/[RULES] sections | .inp text | EPANET solver |
| [TIMES] section | .inp text | EPANET solver |
| [OPTIONS] section | .inp text | EPANET solver |

## Procedure

### 1. Select Quality Analysis Type

```
[OPTIONS]
Quality    NONE                   ; No quality analysis
Quality    Chlorine mg/L          ; Chemical analysis (name + units)
Quality    AGE                    ; Water age in hours
Quality    TRACE  NodeID          ; % water from specified source
```

### 2. Set Initial Quality (if chemical or trace)

```
[QUALITY]
;NodeID   InitQual
R1        1.0         ; 1.0 mg/L chlorine at reservoir
J1        0.5         ; 0.5 mg/L at junction (existing residual)
```

Nodes not listed default to 0.0 initial quality.

### 3. Configure Reaction Coefficients

```
[REACTIONS]
; Global coefficients apply to all pipes/tanks
Global Bulk    -0.5        ; Bulk decay: -0.5/day (negative = decay)
Global Wall    -1.0        ; Wall decay: -1.0 ft/day (negative = decay)

; Per-pipe overrides
Bulk    P101    -0.3        ; Override for pipe P101
Wall    P205    -2.0        ; Higher wall reaction in old pipe

; Reaction order
Order Bulk   1              ; 1st-order bulk reaction (default)
Order Wall   1              ; 1st-order wall reaction (default)
Order Tank   1              ; 1st-order tank reaction (default)

; Limiting concentration (for growth reactions)
Limiting Potential  2.0     ; Max concentration (mg/L)
Roughness Correlation  0   ; No roughness-reaction correlation
```

**Reaction sign convention**:
- Negative coefficient = decay (chlorine loss)
- Positive coefficient = growth (DBP formation)

### 4. Define Quality Sources

```
[SOURCES]
;NodeID   Type       Strength   Pattern
R1        CONCEN     1.5                ; Constant 1.5 mg/L at R1
WTP       SETPOINT   2.0        PAT_CL  ; Setpoint 2.0 mg/L, varying
BOOST1    FLOWPACED  0.5                ; Add 0.5 mg/L boost
INJ1      MASS       100                ; 100 mass-units/min
```

Source types:
- **CONCEN**: Sets concentration of external inflow entering a node
- **MASS**: Injects a given mass/minute into a node
- **SETPOINT**: Sets concentration leaving a node to a given value
- **FLOWPACED**: Adds a given value to the concentration leaving a node

### 5. Configure Tank Mixing

```
[MIXING]
;TankID   Model     Fraction
T1        MIXED                 ; Complete mixing (default)
T2        2COMP     0.2         ; 20% inlet/outlet, 80% dead zone
T3        FIFO                  ; Plug flow (first-in, first-out)
T4        LIFO                  ; Stacked plug flow
```

### 6. Set Controls and Rules

**Simple controls**:
```
[CONTROLS]
LINK PUMP1 OPEN  IF NODE TANK1 BELOW 10
LINK PUMP1 CLOSED IF NODE TANK1 ABOVE 20
LINK VALVE1 1.5  AT TIME 16
```

**Rule-based controls**:
```
[RULES]
RULE 1
IF TANK TANK1 LEVEL BELOW 5
AND SYSTEM CLOCKTIME >= 6 AM
AND SYSTEM CLOCKTIME <= 10 PM
THEN PUMP PUMP1 STATUS IS OPEN
ELSE PUMP PUMP1 STATUS IS CLOSED
PRIORITY 1
```

### 7. Set Timing Parameters

```
[TIMES]
Duration           72:00        ; 72-hour simulation
Hydraulic Timestep 1:00         ; 1-hour hydraulic step
Quality Timestep   0:05         ; 5-minute quality step
Pattern Timestep   6:00         ; 6-hour pattern step
Pattern Start      0:00         ; Patterns begin at time 0
Report Timestep    1:00         ; Report every 1 hour
Report Start       0:00         ; Start reporting at time 0
Statistic          NONE         ; Report all timesteps
```

**Quality timestep must be ≤ hydraulic timestep** for numerical stability.

### 8. Set Solver Options

```
[OPTIONS]
Units            GPM
Headloss         H-W
Demand Model     DDA          ; or PDA for pressure-driven
Trials           200          ; Max hydraulic iterations
Accuracy         0.001        ; Convergence criterion
Unbalanced       Continue 10  ; Continue 10 extra trials if unbalanced
Viscosity        1.0          ; Relative to water at 20°C
Diffusivity      1.0          ; Relative to chlorine in water
```

## Verification

- [ ] Quality type matches analysis objective (age, chemical, trace)
- [ ] Bulk reaction coefficient sign: negative for decay, positive for growth
- [ ] Wall reaction coefficient units match system (ft/day for US, m/day for SI)
- [ ] Quality timestep ≤ hydraulic timestep
- [ ] Source nodes exist in the network
- [ ] Control rules reference valid node/link IDs
- [ ] Pattern timestep divides evenly into simulation duration
- [ ] Tank mixing model chosen appropriately for tank geometry

## Traps

| Trap | Symptom | Prevention |
|------|---------|------------|
| **Positive bulk coeff for decay** | Chlorine grows instead of decaying | Use negative values for decay reactions |
| **Quality timestep > hydraulic** | Numerical instability, mass balance errors | Set quality step to 1/10 of hydraulic step |
| **Wrong wall reaction units** | Wall decay rate off by 3.28× | ft/day for US, m/day for SI |
| **CONCEN source on internal node** | Source only affects external inflow, not pass-through | Use SETPOINT or FLOWPACED for internal nodes |
| **Missing initial quality** | Simulation starts with zero concentration everywhere | Set [QUALITY] for all source/entry nodes |
| **Rule priority conflicts** | Unpredictable pump/valve behavior | Use explicit priorities (higher number = higher priority) |

## Example

Chlorine decay analysis for a 48-hour simulation:

```
[OPTIONS]
Quality    Chlorine mg/L
Tolerance  0.01

[QUALITY]
;Node  InitQual
R1     2.0

[REACTIONS]
Global Bulk  -0.5
Global Wall  -1.0

[SOURCES]
R1    CONCEN  2.0

[TIMES]
Duration           48:00
Hydraulic Timestep 1:00
Quality Timestep   0:05
```
