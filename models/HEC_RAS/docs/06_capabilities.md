# Stage 06 — Full Capability Inventory

HEC-RAS does far more than a single steady run. This page inventories every major
capability, its status in this headless WINE environment, and the tool/route.

## Validated & drivable (steady core)

| Capability | Tool | Notes |
|------------|------|-------|
| Steady water-surface profiles | `run_hecras.py` | PRIMARY; real `RasSteady.exe`; NSE 0.9965 vs observed |
| Multiple flow profiles | `convert_flow_to_hecras.py` | one discharge per profile in the run file |
| Subcritical / supercritical / **mixed** regime | plan `.pNN` (`Mixed Flow`) | jumps captured; Froude reported per XS |
| Manning roughness sensitivity | `edit_geometry.py` | scale/set n |
| Expansion / contraction losses | `edit_geometry.py` (`--exp/--contr`) | |
| Normal-depth / known-WS / critical boundaries | `edit_boundaries.py` | type codes 1/2/3/4 |
| Stage-discharge **rating curves** | `rating_curve.py` | sweep Q through the real solver |
| Full hydraulic output (V, depth, width, area, shear, conveyance, …) | `parse_output_hecras.py` | 50+ variables in the HDF |
| Validation vs observed WS | `validate_hecras.py` | metrics + figure |

## Present but needing orchestration (Wine Mono / Ras.exe)

| Capability | Solver | Blocker |
|------------|--------|---------|
| Unsteady 1-D flow (Saint-Venant) | `RasUnsteady.exe` | needs plan-HDF skeleton with boundary time series (Ras.exe) |
| 2-D shallow-water flow | `RasUnsteady.exe` | as above + 2-D mesh build in GUI |
| Geometry preprocessing | `RasGeomPreprocess.exe` | standalone run needs Ras.exe run-control files |
| Sediment transport (quasi-unsteady) | `RasQuasiSediment.exe` | sediment data + Ras.exe orchestration |
| Sediment transport (unsteady) | `RasUnsteadySediment.exe` | as above |
| Water quality (temperature, nutrients) | `RasWaterQuality.exe` | WQ data + Ras.exe orchestration |

These solvers **load and start** under wine (verified: `RasUnsteady.exe` prints
its 6.7 Beta 5 banner and enters the HDF setup), but cannot finish without the
`.NET` `Ras.exe` controller, which requires **Wine Mono** (absent;
`dl.winehq.org` unreachable in the sandbox). On a licensed Windows install or
with Wine Mono installed, run them via `Ras.exe -c <project>.prj <plan>.pNN`.

## Structural capabilities (within steady, via geometry/flow files)

Bridges, culverts, inline/lateral structures, gates, weirs, storage areas, and
junctions are all expressed in the `.gNN`/`.uNN` files and solved by the same
engines. The shipped example library (`Example_Projects_6_6.zip`, 68 projects)
covers each — e.g. *ConSpan Culvert*, *Bridge Hydraulics*, *Inline Structure
with Gated Spillways*. For steady projects that ship a `.rNN` + `.gNN.hdf`, the
`run_hecras.py` recipe applies unchanged.

## What is intentionally NOT here

- **No rainfall-runoff / meteorological forcing.** HEC-RAS consumes discharge,
  not precip/temp. The prior GR4J surrogate was removed (see SKILL.md banner).
- **No DEM-to-cross-section delineation.** Geometry authoring is a GUI/RAS-Mapper
  task; this KI parameterises and runs existing geometry.
