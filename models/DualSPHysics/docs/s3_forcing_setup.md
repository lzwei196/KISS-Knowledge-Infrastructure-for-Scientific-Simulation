# Stage 3: Forcing and Boundary Condition Setup

## Purpose

Configure external forcing (waves, currents, tides) and advanced boundary conditions for the simulation. This includes inlet/outlet zones, wave paddles, relaxation zones, and prescribed motions. All forcing data must be in SI units (m, s, m/s).

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Wave data | CSV or time series | Hs (m), Tp (s) | Observations, SWAN, WW3 |
| Current data | CSV or constant | m/s | Observations, models |
| Water level | CSV or constant | m | Tide gauges, models |
| Wind data | CSV | m/s, degrees | Meteorological data |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Inlet/outlet XML | XML snippet | `<special><inout>` configuration |
| Wave paddle XML | XML snippet | `<special><wavepaddles>` configuration |
| Relaxation zone XML | XML snippet | `<special><relaxationzones>` configuration |
| Forcing CSV files | CSV | Time series for variable boundary conditions |

## Procedure

### A. Inlet/Outlet Configuration

1. **Define inlet zone geometry** (line for 2D, plane for 3D)
2. **Set velocity mode**:
   - Fixed: constant velocity
   - Variable: time-varying from file
   - Extrapolated: computed from interior
3. **Set density mode**:
   - Fixed: constant density
   - Hydrostatic: computed from depth
   - Extrapolated: computed from interior
4. **Configure layers**: 6-8 particle layers at inlet

### B. Wave Paddle Configuration

1. **Select paddle type**: piston (horizontal), flap (rotating)
2. **Set wave parameters**: height (m), period (s), order (1st/2nd)
3. **Configure AWAS** (Active Wave Absorption System) to prevent re-reflection
4. **Set still water level** (SWL) for correct wave generation

### C. Relaxation Zones

1. **Define zone geometry**: start/end positions, width
2. **Set wave theory**: regular, irregular (spectrum)
3. **Configure absorption ramp**: gradual damping factor

## Verification

- [ ] All lengths in meters (not cm, mm, or feet)
- [ ] All velocities in m/s (not cm/s or knots)
- [ ] Wave height is significant height Hs (not peak-to-trough)
- [ ] Wave period is peak period Tp (not zero-crossing Tz)
- [ ] Inlet layers ≥ 6
- [ ] SWL matches actual water depth in domain
- [ ] AWAS gauge position is inside the domain

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Wave height in cm | Tiny waves, no visible effect | Divide by 100 to get meters |
| Current in cm/s | Very slow flow | Divide by 100 to get m/s |
| Velocity in knots | 2x too fast | Multiply by 0.5144 |
| SWL mismatch | Waves propagate incorrectly | Match SWL to domain water depth |
| Too few inlet layers | Pressure oscillations at inlet | Use ≥ 6 layers |
| Missing AWAS | Wave re-reflection builds up | Enable AWAS on piston |
| Refilling mode wrong | Particles appear above free surface | Use mode 1 (BelowZsurf) |

## Example: Inlet with Fixed Velocity

```xml
<special>
  <inout>
    <memoryresize size0="2" size="4" />
    <inoutzone>
      <refilling value="1" />
      <inputtreatment value="0" />
      <layers value="8" />
      <zone3d>
        <plane>
          <point x="0" y="0" z="0" />
          <point2 x="0" y="1.0" z="0" />
          <point3 x="0" y="0" z="0.5" />
          <direction x="1" y="0" z="0" />
        </plane>
      </zone3d>
      <imposevelocity mode="0">
        <velocity v="2.0" />  <!-- m/s -->
      </imposevelocity>
      <imposerhop mode="2" />
    </inoutzone>
  </inout>
</special>
```

## Unit Conversion Quick Reference

| Source | DualSPHysics | Conversion |
|--------|-------------|------------|
| Hs (cm) | Hs (m) | / 100 |
| Hs (ft) | Hs (m) | * 0.3048 |
| Tp (s) | Tp (s) | none |
| U (cm/s) | U (m/s) | / 100 |
| U (knots) | U (m/s) | * 0.5144 |
| Water level (cm) | WL (m) | / 100 |
| Depth (ft) | Depth (m) | * 0.3048 |
