# Stage 1: Case Definition (XML)

## Purpose

Create the XML case definition file that specifies geometry, physical constants, and simulation parameters. This is the primary input to DualSPHysics. The XML file defines WHAT to simulate — the domain geometry, fluid properties, boundary conditions, and numerical parameters.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Domain geometry | User-defined dimensions | meters (m) | Design drawings, GIS data |
| Particle spacing (dp) | Float | meters | Resolution requirement |
| Fluid density (rhop0) | Float | kg/m^3 | Physical property (1000 for water) |
| Gravity | Vector | m/s^2 | Typically (0, 0, -9.81) |
| Simulation time | Float | seconds | Study requirement |
| Viscosity | Float | dimensionless or m^2/s | Physical property |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `Case_Def.xml` | XML | Complete case definition |
| Geometry VTK | VTK (via GenCase) | Initial particle distribution for visualization |

## Procedure

1. **Choose dp** based on smallest feature to resolve. Rule: at least 10 particles across smallest dimension. Example: 0.1m gap needs dp <= 0.01m.

2. **Define constants** in `<constantsdef>`:
   - gravity: (0, 0, -9.81) for vertical z-axis
   - rhop0: 1000 kg/m^3 for fresh water, 1025 for seawater
   - gamma: 7 for water (polytropic constant)
   - coefsound: 10-20 (speed of sound multiplier)
   - coefh: 1.0 typical (smoothing length = coefh * sqrt(3*dp^2))
   - cflnumber: 0.2 (Courant number)

3. **Define geometry** using draw commands:
   - Use `setmkfluid` before drawing fluid regions
   - Use `setmkbound` before drawing boundary regions
   - Draw boxes, spheres, cylinders for domain
   - Use `boxfill` to specify which faces to fill (solid, bottom, left, etc.)

4. **Set execution parameters**:
   - StepAlgorithm: 2 (Symplectic) preferred for stability
   - Kernel: 2 (Wendland) preferred
   - ViscoTreatment: 1 (Artificial) for simplicity, 2 (Laminar+SPS) for accuracy
   - DensityDT: 2 (Fourtakas) recommended
   - TimeMax: simulation duration in seconds
   - TimeOut: output interval in seconds

5. **Validate XML** by running GenCase (Stage 2).

## Verification

- [ ] XML is well-formed (parseable)
- [ ] dp is in meters (not mm or cm)
- [ ] rhop0 is in kg/m^3 (not g/cm^3)
- [ ] Gravity points downward (-9.81 in vertical axis)
- [ ] Fluid and boundary regions don't overlap
- [ ] TimeMax and TimeOut are in seconds
- [ ] Visco value matches ViscoTreatment type

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dp in mm instead of m | Billions of particles, OOM | Divide dp by 1000 |
| rhop0 = 1.0 (g/cm^3) | Wrong pressure, instability | Use 1000 kg/m^3 |
| Missing boundary faces | Particle leakage | Add all needed faces to boxfill |
| Visco mismatch | Too viscous or inviscid | Match value to treatment type |
| coefsound too low | Density fluctuations > 1% | Increase to 15-20 |
| coefsound too high | Very small timesteps | Reduce to 10-15 |

## Example

```xml
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="-9.81" />
      <rhop0 value="1000" />
      <gamma value="7" />
      <coefsound value="20" />
      <coefh value="1.0" />
      <cflnumber value="0.2" />
    </constantsdef>
    <geometry>
      <definition dp="0.01" />
      <commands>
        <mainlist>
          <setmkfluid mk="0" />
          <drawbox>
            <boxfill>solid</boxfill>
            <point x="0" y="0" z="0" />
            <size x="0.4" y="0.67" z="0.3" />
          </drawbox>
        </mainlist>
      </commands>
    </geometry>
  </casedef>
</case>
```
