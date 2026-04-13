# Stage 0: Network Design

## Purpose

Define the physical topology of the water distribution system — junctions, pipes, tanks, reservoirs, pumps, and valves — as a graph of nodes and links. This is the foundation for all subsequent EPANET simulation stages.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Network topology | GIS shapefiles, CAD drawings, field surveys | Spatial data or tabular |
| Junction locations | GPS coordinates, as-built drawings | (x, y, elevation) |
| Pipe inventory | Asset management database | ID, diameter, length, material, age |
| Tank specifications | Engineering drawings | Elevation, diameter, levels |
| Reservoir data | SCADA, survey | Head (water surface elevation) |
| Pump curves | Manufacturer data sheets | Head vs. Flow points |
| Valve inventory | Asset records | Type, diameter, setting |

## Outputs

| Output | Format | Used By |
|--------|--------|---------|
| Network component lists | CSV tables | Stage 1 (convert_demands_to_inp) |
| Topology connections | Node1-Node2 pairs per link | INP assembly |
| Coordinate data | (x, y) per node | [COORDINATES] section (optional) |

## Procedure

1. **Identify system boundaries**: Determine where the modeled network starts (reservoirs/sources) and ends (dead-end junctions, system interconnections).

2. **Map junctions**: Every pipe intersection, demand point, change in pipe diameter, or change in pipe material should be a junction. Assign unique IDs and measure/estimate elevations above a common datum (typically mean sea level).

3. **Map pipes**: Record start node, end node, length, diameter, material, and age. Choose appropriate roughness coefficient based on material and age:
   - New cast iron: H-W C = 130
   - 20-year cast iron: H-W C = 100
   - New PVC: H-W C = 150
   - Ductile iron: H-W C = 140

4. **Map tanks**: Record bottom elevation, initial/min/max water levels, and diameter. For non-cylindrical tanks, prepare a volume curve.

5. **Map reservoirs**: Record hydraulic head (water surface elevation). For time-varying sources, prepare a head pattern.

6. **Map pumps**: Record suction (Node1) and discharge (Node2) nodes. Obtain pump curve (head vs. flow) from manufacturer or field test.

7. **Map valves**: Record upstream node, downstream node, diameter, valve type (PRV/PSV/PBV/FCV/TCV/GPV), and pressure/flow setting.

## Verification

- [ ] All pipes have both endpoints defined as junctions, reservoirs, or tanks
- [ ] Network is fully connected (no isolated subnetworks unless intentional)
- [ ] At least one reservoir or tank with fixed head exists (boundary condition)
- [ ] Elevations are consistent with local topography
- [ ] Pipe diameters are in correct units (inches for US, mm for SI)
- [ ] Tank levels: min_level < init_level < max_level

## Traps

| Trap | Symptom | Prevention |
|------|---------|------------|
| **Disconnected nodes** | Error 110: cannot solve hydraulics | Verify all nodes have at least one connected link |
| **Wrong elevation datum** | Unrealistic pressures (negative or >200 psi) | Use consistent datum (MSL) for all nodes |
| **Missing boundary** | Error 110: system has no fixed grade nodes | Ensure at least one reservoir or tank exists |
| **Duplicate IDs** | Error 200: node/link already exists | Use unique IDs (max 31 characters) |
| **Unit mismatch on diameters** | Pipes in mm with US units → impossibly small pipes | Match diameter units to flow unit system |

## Example

```
[JUNCTIONS]
;ID    Elev    Demand
J1     100     50
J2     120     10
J3     115     0

[RESERVOIRS]
;ID    Head
R1     700

[PIPES]
;ID    Node1  Node2  Length  Diam  Roughness
P1     R1     J1     3000    12    100
P2     J1     J2     5000    8     100
P3     J2     J3     5000    8     100
```
