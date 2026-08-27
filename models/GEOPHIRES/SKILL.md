> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model.
>
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (6 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (6 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (18 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (2 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_reservoir_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_reservoir_params.py --help` |
| `tools/convert_site_economics.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_site_economics.py --help` |
| `tools/generate_input_file.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/generate_input_file.py --help` |
| `tools/parse_geophires_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_geophires_output.py --help` |
| `tools/run_geophires.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_geophires.py --help` |
| `tools/validate_geophires_results.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/validate_geophires_results.py --help` |

*6 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# GEOPHIRES-X Knowledge Infrastructure

**Package**: `hydrocraft-geophires` v1.0.0
**Model**: GEOPHIRES-X (v3.11.25) — Geothermal Techno-Economic Simulator
**Developer**: NREL (National Renewable Energy Laboratory)
**License**: MIT
**Stats**: 6 tools | 6 skill documents | 18 diagnostic triplets | ~1,800 lines of Python
**Validation Status**: Production-validated (built-in examples, Fervo Cape Station case study)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/DTB/SKILL.md` for depth-to-bedrock data.


## 1. What GEOPHIRES Does

GEOPHIRES is a free, open-source geothermal techno-economic simulator that combines:
- **Reservoir models**: Thermal drawdown modeling (EGS, hydrothermal, CLGS, SUTRA, SBT)
- **Wellbore models**: Temperature/pressure drop along production and injection wells
- **Surface plant models**: Energy conversion (ORC, flash, direct-use, heat pump, district heating)
- **Economic models**: LCOE/LCOH calculation (FCR, standard levelized cost, BICYCLE, CLGS, SAM)

GEOPHIRES estimates capital costs, O&M costs, energy production profiles, and levelized costs
of energy over a geothermal project's lifetime (typically 25–50 years).

### Key Capabilities
- 9 reservoir model types (parallel fractures, linear heat sweep, percentage drawdown, TOUGH2, SBT, etc.)
- 9 surface plant types (subcritical/supercritical ORC, single/double flash, heat pump, district heating, etc.)
- 5 economic models (FCR, standard, BICYCLE, CLGS, SAM PPA)
- Co-generation options (topping, bottoming, parallel cycle)
- Monte Carlo uncertainty analysis
- HIP-RA (Heat in Place Resource Assessment)

---

## 2. Installation

### Prerequisites
- Python 3.8+
- Git
- pip

### Method 1: Editable Install (Recommended)
```bash
python -m venv venv
source venv/bin/activate
pip install -e git+https://github.com/NREL/GEOPHIRES-X.git#egg=geophires-x --src .
```

### Method 2: Direct Install
```bash
pip install https://github.com/NREL/GEOPHIRES-X/archive/main.zip
```

### Method 3: From Local Source
```bash
cd /path/to/GEOPHIRES-X
pip install -e .
```

### Key Dependencies
| Package | Purpose |
|---------|---------|
| numpy | Numerical computation |
| pint | Unit conversion system |
| scipy | Scientific computing, interpolation |
| matplotlib | Plotting and visualization |
| pandas | Data handling |
| h5py | HDF5 file I/O (AGS/SBT) |
| iapws | Water/steam thermodynamic properties |
| coolprop | Fluid thermodynamic properties |
| nrel-pysam | SAM economic model integration |
| rich | Terminal output formatting |

---

## 3. Pipeline Stages

| Stage | Tool | Purpose |
|-------|------|---------|
| s0 | (manual) | Site characterization: reservoir type, depth, gradient, end-use |
| s1 | `convert_reservoir_params.py` | Convert reservoir parameters to GEOPHIRES input format |
| s2 | `convert_site_economics.py` | Convert economic/financial parameters to input format |
| s3 | `generate_input_file.py` | Assemble complete GEOPHIRES .txt input file |
| s4 | `run_geophires.py` | Execute GEOPHIRES simulation |
| s5 | `parse_geophires_output.py` | Extract results to structured CSV/JSON |
| s6 | (analysis) | Validation, sensitivity analysis, Monte Carlo |

### Stage Dependencies
- s1 and s2 can run in parallel (independent parameter preparation)
- s3 depends on s1 and s2 (assembles parameters from both)
- s4 depends on s3 (needs complete input file)
- s5 depends on s4 (needs simulation output)
- s6 depends on s5 (needs parsed results)

---

## 4. Input Format

GEOPHIRES uses a **comma-separated text file** (.txt) with the format:
```
Parameter Name, Value, ---Optional comment
```

### Format Rules
1. One parameter per line
2. Fields separated by commas
3. Comments start with `---` (triple dash)
4. Lines starting with `#` are full-line comments
5. Parameters can appear in any order
6. Units are implicit (documented per parameter)
7. Unknown parameters are silently ignored
8. Output units can be overridden: `Units:Parameter Name, NewUnit`

### Example Input
```
Reservoir Model,1,                        ---Multiple Parallel Fractures model
Reservoir Depth,3,                        ---[km]
Number of Segments,1,                     ---[-]
Gradient 1,50,                            ---[deg.C/km]
Maximum Temperature,400,                  ---[deg.C]
Number of Production Wells,2,             ---[-]
Number of Injection Wells,2,              ---[-]
Production Well Diameter,7,               ---[inch]
Injection Well Diameter,7,                ---[inch]
Production Flow Rate per Well,55,         ---[kg/s]
Injection Temperature,50,                 ---[deg.C]
Reservoir Heat Capacity,1000,             ---[J/kg/K]
Reservoir Density,2700,                   ---[kg/m3]
Reservoir Thermal Conductivity,2.7,       ---[W/m/K]
End-Use Option,1,                         ---Electricity
Power Plant Type,2,                       ---Supercritical ORC
Economic Model,1,                         ---FCR
Fixed Charge Rate,0.05,                   ---[-]
Plant Lifetime,30,                        ---[yr]
```

---

## 5. Output Format

GEOPHIRES generates two output files:
1. **Text report** (`HDR.out` or custom path): Human-readable formatted report
2. **JSON export** (`HDR.json` or custom path): Machine-readable structured data

### Output Sections
| Section | Key Variables |
|---------|---------------|
| Summary of Results | End-Use Option, Average Net Power/Heat, LCOE/LCOH, Well depths |
| Economic Parameters | Economic Model, Discount Rate, NPV, IRR, MOIC, Payback Period |
| Engineering Parameters | Well counts, Pump efficiency, Injection temperature |
| Resource Characteristics | Max reservoir temperature, Gradient, Segments |
| Reservoir Parameters | Model type, Bottom-hole temperature, Fracture geometry |
| Reservoir Simulation | Production temperatures (max/avg/min), Heat extraction, Pressure drops |
| Capital Costs | Drilling, Surface plant, Exploration, Total CAPEX (MUSD) |
| O&M Costs | Wellfield, Power plant, Water, Total OPEX (MUSD/yr) |
| Production Profile | Year-by-year: Drawdown, Temperature, Net Power, Efficiency |
| Energy Profile | Annual kWh/GWh, Cumulative production, Heat mined |
| Revenue & Cashflow | Annual revenues, OPEX, Net cashflow, Cumulative position |

---

## 6. Output Description

**Source of truth**: `dag.yaml`. The dag is the model identity for observable outputs; if this section ever disagrees with `dag.yaml`, the dag wins.

**Headline output**: the dag's `validation_rank: 1` variable, and the output this model is judged by:

> `geofluid_production_temperature` -- Year-by-year subsurface produced-geofluid temperature profile reflecting thermal drawdown. (`degC`)

### Dag Outputs

| Output variable (dag `var`) | Rank | Unit | Description / note |
|-----------------------------|------|------|--------------------|
| `geofluid_production_temperature` | 1 | `degC` | Year-by-year subsurface produced-geofluid temperature profile reflecting thermal drawdown. |
| `LCOE` | dag output | see `dag.yaml` | Listed by the dag as an additional observable output. |
| `LCOH` | dag output | see `dag.yaml` | Listed by the dag as an additional observable output. |
| `Average Net Power` | dag output | see `dag.yaml` | Listed by the dag as an additional observable output. |
| `total_capex` | dag output | see `dag.yaml` | Listed by the dag as an additional observable output. |
| `annual_energy_production` | dag output | see `dag.yaml` | Listed by the dag as an additional observable output. |

### Output Unit Table

| Output variable | Unit stated by KI source | Source |
|-----------------|--------------------------|--------|
| `geofluid_production_temperature` | `degC` | `dag.yaml` |
| `LCOE` | cents/kWh | Existing GEOPHIRES validation summary in this file |
| `LCOH` | $/MMBTU or cents/kWh(th) | Existing GEOPHIRES validation summary in this file |
| `Average Net Power` | see `dag.yaml` | Dag output name supplied without a unit in this body |
| `total_capex` | see `dag.yaml` | Dag output name supplied without a unit in this body |
| `annual_energy_production` | see `dag.yaml` | Dag output name supplied without a unit in this body |

---

## 6b. Critical Domain Knowledge

### DK-1: Reservoir Depth in km, NOT meters
GEOPHIRES expects `Reservoir Depth` in **kilometers**. Common trap: providing depth in meters
(e.g., 3000 instead of 3) produces wildly unrealistic results—the model may still run but
the calculated bottom-hole temperature will be astronomical.
- **Check**: Depth values should typically be 0.5–10 km
- **Conversion**: meters / 1000 = km

### DK-2: Temperature Gradient in degC/km, NOT degC/m
The `Gradient` parameter uses **degrees Celsius per kilometer**. Providing degC/m (e.g., 0.05
instead of 50) results in near-zero temperature at depth.
- **Check**: Typical gradients are 20–100 degC/km
- **Conversion**: degC/m * 1000 = degC/km

### DK-3: Flow Rate in kg/s, NOT m3/s or L/s
`Production Flow Rate per Well` is in **kilograms per second**. Confusion with volumetric
flow rates (m3/s or L/s) changes results dramatically.
- **Check**: Typical flow rates are 20–150 kg/s per well
- **Conversion**: m3/s * density_kg_m3 = kg/s (water at ~100°C: density ≈ 958 kg/m3)

### DK-4: Well Diameter in inches, NOT meters or cm
Production and injection well diameters are specified in **inches**.
- **Check**: Typical diameters are 5–12 inches
- **Conversion**: cm / 2.54 = inches; m * 39.37 = inches

### DK-5: Injection Temperature affects LCOE significantly
The injection temperature is the temperature of the reinjected fluid after heat extraction.
Lower injection temperatures extract more heat but can cause mineral scaling.
- **Typical range**: 40–80°C for electricity, 50–90°C for direct-use
- **Trap**: Setting injection temperature close to production temperature yields near-zero power

### DK-6: Economic Model choice changes output dramatically
Different economic models (FCR=1, Standard=2, BICYCLE=3, CLGS=4, SAM=5) require different
parameter sets and produce different LCOE values for the same physical system.
- **FCR**: Simplest; needs only Fixed Charge Rate
- **Standard**: Needs Discount Rate
- **BICYCLE**: Needs Bond/Equity rates, Inflation, Tax rates
- **SAM**: Full financial model with PPA structure

### DK-7: Reservoir Model 4 (Percentage Drawdown) is the DEFAULT
If no reservoir model is specified, GEOPHIRES uses Model 4 (Annual Percentage Thermal Drawdown).
This is a simple model that assumes a fixed fractional temperature decline per year.
- **Key parameter**: `Drawdown Parameter` (fraction/year, e.g., 0.005 = 0.5%/year)
- **Trap**: Forgetting to set the drawdown parameter uses the default, which may not match your site

### DK-8: Maximum Temperature caps reservoir temperature
The `Maximum Temperature` parameter (default 400°C) limits the calculated bottom-hole
temperature regardless of depth × gradient. If depth × gradient > Maximum Temperature,
the bottom-hole temperature is clamped.
- **Trap**: For deep/hot systems, too-low Maximum Temperature silently limits results

### DK-9: Plant Lifetime affects LCOE nonlinearly
Changing Plant Lifetime (default 30 years) affects LCOE through both energy production
(more years = more kWh) and O&M costs (more years = more costs). The relationship is
nonlinear due to thermal drawdown over time.

---

## 7. Unit Conversion Table (Unit Table)

This is the unit table for GEOPHIRES inputs and pipeline conversions. Exact I/O shapes live in `docs/format_spec.yaml`; for observable output units, use `dag.yaml` first and the output unit table in Section 6 as the body restatement.

| Parameter | GEOPHIRES Unit | Common Mistake | Factor | Symptom |
|-----------|---------------|----------------|--------|---------|
| Reservoir Depth | km | meters | ×0.001 | Extreme temperature, impossible costs |
| Gradient | degC/km | degC/m | ×1000 | Near-zero bottom-hole temperature |
| Flow Rate per Well | kg/s | L/s or m3/s | varies | Wrong power output, cost errors |
| Well Diameter | inches | cm or m | ×0.3937 or ×39.37 | Pressure drop errors |
| Reservoir Heat Capacity | J/kg/K | kJ/kg/K | ×1000 | Wrong thermal drawdown rate |
| Reservoir Density | kg/m3 | g/cm3 | ×1000 | Wrong reservoir volume calculations |
| Thermal Conductivity | W/m/K | mW/m/K | ×0.001 | Wrong heat transfer calculations |
| Pressure | kPa | MPa or bar | ×1000 or ×100 | Pressure drop/pumping errors |
| Fixed Charge Rate | fraction | percent | ×0.01 | LCOE 100× too high |
| Discount Rate | fraction | percent | ×0.01 | NPV calculation errors |
| Fracture Area | m2 | km2 | ×1e6 | Wrong heat exchange area |

---

## 8. Reservoir Model Reference

| Model ID | Name | Key Parameters | Best For |
|----------|------|----------------|----------|
| 0 | Cylindrical | Reservoir length, width | Simple cylindrical reservoirs |
| 1 | Multiple Parallel Fractures (Gringarten) | Fracture shape, height, count, separation | EGS with discrete fractures |
| 2 | 1D Linear Heat Sweep | Porosity | Sedimentary/porous media |
| 3 | Single Fracture m/A Drawdown | Fracture area | Single fracture EGS |
| 4 | Percentage Thermal Drawdown (DEFAULT) | Drawdown parameter | Quick screening studies |
| 5 | User-Provided Temperature | Temperature vs time file | Known production data |
| 6 | TOUGH2 | TOUGH2 output files | Complex reservoir simulation |
| 7 | SUTRA | SUTRA configuration | Thermal energy storage |
| 8 | SBT (Slender Body Theory) | SBT parameters | Advanced CLGS |

---

## 9. Surface Plant Type Reference

| Type ID | Name | End-Use | Temperature Range |
|---------|------|---------|-------------------|
| 1 | Subcritical ORC | Electricity | 100–180°C |
| 2 | Supercritical ORC | Electricity | 150–250°C |
| 3 | Single-Flash | Electricity | >180°C |
| 4 | Double-Flash | Electricity | >200°C |
| 5 | Absorption Chiller | Cooling | >80°C |
| 6 | Heat Pump | Heat | <80°C (upgraded) |
| 7 | District Heating | Heat | 60–120°C |
| 8 | SUTRA/RTES | Storage | Variable |
| 9 | Industrial Heat (DEFAULT) | Heat | Variable |

---

## 10. Economic Model Reference

| Model ID | Name | Key Inputs | Output |
|----------|------|------------|--------|
| 1 | Fixed Charge Rate (FCR) | Fixed Charge Rate | LCOE = FCR × CAPEX / Annual Energy |
| 2 | Standard Levelized Cost | Discount Rate | Standard NPV-based LCOE |
| 3 | BICYCLE | Bond/Equity rates, Inflation, Tax | Inflation-adjusted LCOE |
| 4 | Simple (CLGS) | Basic rates | Simplified LCOE for CLGS |
| 5 | SAM Single Owner PPA | Full PPA parameters | PPA-based LCOE, detailed cashflow |

---

## 11. Tool Reference

### convert_reservoir_params.py
Converts site characterization data (depth, gradient, rock properties) to GEOPHIRES parameter format.
Handles unit conversions from common field units to GEOPHIRES internal units.

### convert_site_economics.py
Converts economic assumptions and site-specific financial data to GEOPHIRES economic parameters.
Supports all 5 economic models with appropriate parameter mapping.

### generate_input_file.py
Assembles a complete GEOPHIRES .txt input file from reservoir and economic parameter sets.
Validates parameter combinations and warns about incompatible settings.

### run_geophires.py
Executes GEOPHIRES simulation with preflight checks. Validates input file, runs the model,
captures output and error logs. Handles timeouts and error recovery.

### parse_geophires_output.py
Parses GEOPHIRES .out text report into structured CSV and JSON. Extracts summary metrics,
production profiles, cost breakdowns, and cashflow tables.

### validate_geophires_results.py
Validates simulation results against expected ranges and published benchmarks.
Computes domain-appropriate metrics and generates comparison figures.

---

## 12. Validated Results

**Source of truth**: `docs/validation_convention.yaml` for field bars, and `dag.yaml` for the output names. The convention wins over remembered thresholds. Null bands are written as `no cited threshold`; do not substitute Moriasi-style or other thresholds unless the convention file cites them for this dag variable.

### Built-in Examples Tested
| Example | Type | LCOE/LCOH | Status |
|---------|------|-----------|--------|
| example1 | EGS Electricity (MPF) | ~5 ¢/kWh | PASS |
| example2 | EGS Direct-Use Heat (LHS) | ~10 $/MMBTU | PASS |
| example4 | Hydrothermal Electricity (PTD) | ~4 ¢/kWh | PASS |
| Fervo Cape | 500 MW EGS | Published comparison | PASS |

### Key Metrics
- **LCOE** (Levelized Cost of Electricity): cents/kWh
- **LCOH** (Levelized Cost of Heat): $/MMBTU or cents/kWh(th)
- **NPV** (Net Present Value): MUSD
- **IRR** (Internal Rate of Return): %
- **Capacity Factor**: fraction (0.85–0.95 typical for geothermal)

### Performance Metrics -- Convention Bars

The supplied convention entries for these GEOPHIRES outputs use `pbias` with `zero_centered` direction. Their `very_good`, `good`, and `satisfactory` bands are null in the convention, and the convention lists no citation keys.

| Dag variable | Metric | Direction | Satisfactory band | Good band | Very good band | Convention cites |
|--------------|--------|-----------|-------------------|-----------|----------------|------------------|
| `LCOE` | `pbias` | `zero_centered` | no cited threshold | no cited threshold | no cited threshold | none listed |
| `LCOH` | `pbias` | `zero_centered` | no cited threshold | no cited threshold | no cited threshold | none listed |
| `Average Net Power` | `pbias` | `zero_centered` | no cited threshold | no cited threshold | no cited threshold | none listed |

No convention band for `geofluid_production_temperature` is stated in this body; the rank-1 output is still the dag's `validation_rank: 1` variable and must be checked against `docs/validation_convention.yaml` before assigning any pass/fail verdict.

---

## 13. Common Workflows

### Workflow 1: Quick EGS Screening
1. Set Reservoir Model = 4 (Percentage Drawdown)
2. Set depth, gradient, drawdown parameter
3. Set Economic Model = 1 (FCR) with Fixed Charge Rate = 0.05
4. Run GEOPHIRES → get approximate LCOE

### Workflow 2: Detailed EGS Analysis
1. Set Reservoir Model = 1 (Multiple Parallel Fractures)
2. Specify full fracture geometry (shape, height, count, separation)
3. Set Economic Model = 3 (BICYCLE) with full financial parameters
4. Run GEOPHIRES → get detailed LCOE, NPV, IRR, cashflow

### Workflow 3: Direct-Use Heat Assessment
1. Set End-Use Option = 2 (Direct-Use Heat)
2. Set appropriate surface temperature and injection temperature
3. Choose economic model
4. Run GEOPHIRES → get LCOH

### Workflow 4: Monte Carlo Uncertainty
1. Prepare base input file
2. Add Monte Carlo parameter ranges
3. Run Monte Carlo wrapper
4. Analyze distribution of LCOE/LCOH

---

## 14. Calibration Parameters (Sensitivity Order)

| Parameter | Range | Sensitivity | Impact On |
|-----------|-------|-------------|-----------|
| Reservoir Depth | 1–10 km | VERY HIGH | Temperature, drilling cost, LCOE |
| Gradient | 20–100 degC/km | VERY HIGH | Temperature, power output |
| Flow Rate per Well | 20–150 kg/s | HIGH | Power output, pumping cost |
| Number of Wells | 1–20 | HIGH | CAPEX, total production |
| Injection Temperature | 40–90°C | HIGH | Heat extraction, thermal efficiency |
| Plant Lifetime | 20–50 yr | MEDIUM | LCOE, cumulative production |
| Discount Rate | 0.03–0.12 | MEDIUM | LCOE, NPV |
| Drawdown Parameter | 0.001–0.01 | MEDIUM | Long-term production decline |
| Well Diameter | 5–12 in | LOW | Pressure drop, pumping |
| Pump Efficiency | 0.6–0.9 | LOW | Parasitic power, net output |

---

## 15. File Structure

```
GEOPHIRES-X/
├── src/
│   └── geophires_x/
│       ├── GEOPHIRESv3.py          # Main entry point
│       ├── __main__.py             # CLI interface
│       ├── Model.py                # Orchestrator
│       ├── Parameter.py            # Parameter classes
│       ├── Units.py                # Unit system (pint-based)
│       ├── OptionList.py           # Enums for all options
│       ├── Reservoir.py            # Base reservoir model
│       ├── MPFReservoir.py         # Multiple Parallel Fractures
│       ├── LHSReservoir.py         # Linear Heat Sweep
│       ├── SFReservoir.py          # Single Fracture
│       ├── TDPReservoir.py         # Percentage Thermal Drawdown
│       ├── CylindricalReservoir.py # Cylindrical
│       ├── UPPReservoir.py         # User-Provided Profile
│       ├── TOUGH2Reservoir.py      # TOUGH2 coupling
│       ├── SUTRAReservoir.py       # SUTRA coupling
│       ├── SBTReservoir.py         # Slender Body Theory
│       ├── WellBores.py            # Wellbore model
│       ├── SurfacePlant.py         # Base surface plant
│       ├── SurfacePlant*.py        # 9 surface plant variants
│       ├── Economics.py            # Base economics model
│       ├── EconomicsAddOns.py      # Add-on economics
│       ├── EconomicsSam.py         # SAM integration
│       ├── Outputs.py              # Output generation
│       └── GeoPHIRESUtils.py       # Utilities
├── tests/
│   └── examples/
│       ├── example1.txt / .out     # EGS Electricity
│       ├── example2.txt / .out     # EGS Direct-Use Heat
│       ├── example3.txt / .out     # EGS Co-generation
│       ├── example4.txt / .out     # Hydrothermal Electricity
│       └── ...                     # 30+ examples
├── setup.py
├── INSTALL.rst
└── README.rst
```
