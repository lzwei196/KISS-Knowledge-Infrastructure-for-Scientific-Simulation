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
| to run the pipeline stages | `tools/` (4 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (18 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (20 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_soil_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_params.py --help` |
| `tools/convert_solution_input.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_solution_input.py --help` |
| `tools/parse_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output.py --help` |
| `tools/run_phreeqc.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_phreeqc.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# PHREEQC Knowledge Infrastructure

| Field             | Value                                                    |
|-------------------|----------------------------------------------------------|
| Package           | hydrocraft-phreeqc-geochem                               |
| Version           | 1.0.0                                                    |
| Target Model      | PHREEQC 3.8.9 (USGS)                                    |
| Domain            | Groundwater geochemistry, aqueous speciation, transport  |
| Language          | C++ (C++11), ~96,000 LOC                                 |
| Build System      | CMake / Autoconf                                         |
| License           | Public Domain (USGS)                                     |
| Validation Tier   | analytic                                                 |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for recharge forcing documentation.
See `data_ki/GLHYMPS/SKILL.md` for hydrogeology data.
See `data_ki/FanWTD/SKILL.md` for water table depth.
See `data_ki/GRACE/SKILL.md` for GRACE TWS validation data.


## 1. Overview

PHREEQC (pH-REdox-EQuilibrium in C) is the USGS standard program for simulating
chemical reactions and transport processes in natural or polluted water. It performs:

- **Aqueous speciation** using ion-association, Pitzer, or SIT activity models
- **Batch-reaction equilibrium** with minerals, gases, ion exchange, and surface complexation
- **1-D reactive transport** via operator-splitting (advection-dispersion-reaction)
- **Kinetic reactions** with Runge-Kutta / CVODE ODE integration
- **Inverse modeling** using linear programming (CL1/CL1MP)
- **Isotope tracking** (C-13, C-14, S-34, etc.)

Input is a keyword-based free-format text file. Output includes full speciation tables,
saturation indices, mass balances, and optional CSV-style selected output.

---

## 2. Installation

### 2.1 Build from Source (CMake)

```bash
cd /path/to/phreeqc3/source/repo
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
# Binary: build/phreeqc
```

### 2.2 Dependencies

| Dependency | Required | Purpose                        |
|------------|----------|--------------------------------|
| C++11      | Yes      | Core compilation               |
| CMake 3.x  | Yes      | Build system                   |
| libm       | Yes      | Math library                   |
| GMP        | No       | Advanced inverse modeling      |

### 2.3 Databases

PHREEQC ships with multiple thermodynamic databases in `database/`:

| Database       | Coverage                                     | Use Case                   |
|----------------|----------------------------------------------|----------------------------|
| phreeqc.dat    | Al,B,Ba,Br,C,Ca,Cd,Cl,Cu,F,Fe,H,K,Li,Mg... | General freshwater         |
| wateq4f.dat    | Extended: Ag,As,Cs,I,Ni,Rb,Se,U,organics    | Trace elements, organics   |
| minteq.dat     | MINTEQA2-derived                             | EPA regulatory modeling    |
| llnl.dat       | LLNL geothermal                              | High-T systems (>100 C)   |
| pitzer.dat     | Pitzer ion-interaction parameters            | Brines, high ionic str.    |
| sit.dat        | SIT parameters                               | Nuclear waste applications |
| iso.dat        | Isotope fractionation factors                | Isotope geochemistry       |
| core10.dat     | Core thermodynamic data                      | Minimal, fast simulations  |

---

## 3. Pipeline

| Stage | Name                  | Description                                 | Tools                    | Parallel |
|-------|-----------------------|---------------------------------------------|--------------------------|----------|
| s0    | Configuration         | Select database and define project scope     | (manual)                 | -        |
| s1    | Solution Definition   | Define aqueous solution compositions         | convert_solution_input   | Yes      |
| s2    | Database Selection    | Choose thermodynamic database for elements   | (manual)                 | Yes      |
| s3    | Reaction Setup        | Define equilibrium phases, kinetics, etc.    | convert_soil_params      | Yes      |
| s4    | Input Assembly        | Assemble complete PHREEQC input file         | (tools s1+s3 output)     | No       |
| s5    | Execution             | Run PHREEQC binary                           | run_phreeqc              | No       |
| s6    | Output Parsing        | Extract results to structured format         | parse_output             | No       |
| s7    | Validation            | Compare against benchmarks or observations   | (analysis scripts)       | No       |

---

## 4. Execution

### 4.1 Command Line

```bash
phreeqc input.pqi output.pqo database/phreeqc.dat [screen_log]
```

**Arguments:**
1. `input.pqi` - Input file (keyword blocks)
2. `output.pqo` - Full output (speciation tables, mass balances)
3. `database` - Thermodynamic database file (default: phreeqc.dat)
4. `screen_log` - Optional screen output file

### 4.2 Input File Format

PHREEQC uses keyword-driven blocks in free format:

```
TITLE Example: Calcite dissolution
DATABASE database/phreeqc.dat

SOLUTION 1  Rainwater
    temp    15.0
    pH      5.6
    pe      12.0
    units   mg/L
    Ca      0.5
    C(4)    1.2    as HCO3
    Cl      0.3
    Na      0.2

EQUILIBRIUM_PHASES 1
    Calcite    0.0   10.0    # SI=0, initial moles=10

SELECTED_OUTPUT
    -file      results.sel
    -totals    Ca  C(4)
    -saturation_indices  Calcite  Dolomite
    -pH
    -pe

END
```

### 4.3 Key Input Keywords

| Keyword              | Purpose                                          |
|----------------------|--------------------------------------------------|
| SOLUTION             | Define aqueous solution (pH, pe, T, composition) |
| EQUILIBRIUM_PHASES   | Mineral equilibrium (SI targets, mole limits)    |
| EXCHANGE             | Ion exchange (e.g., clay CEC)                    |
| SURFACE              | Surface complexation (e.g., ferrihydrite)        |
| GAS_PHASE            | Gas-water equilibrium                            |
| SOLID_SOLUTION       | Solid solution phases                            |
| KINETICS / RATES     | Time-dependent reactions with rate expressions   |
| REACTION             | Irreversible reaction (add reagent stepwise)     |
| REACTION_TEMPERATURE | Temperature sweep                                |
| REACTION_PRESSURE    | Pressure sweep                                   |
| MIX                  | Mix multiple solutions                           |
| TRANSPORT            | 1-D advection-dispersion-reaction                |
| INVERSE_MODELING     | Find mole transfers via linear programming       |
| SELECTED_OUTPUT      | Choose output variables for CSV-like .sel file   |
| USER_PUNCH           | Custom output via Basic-like expressions         |
| PRINT                | Control output verbosity                         |

---

## 5. Output Format

### 5.1 Full Output (.pqo)

Contains for each simulation step:
- Solution composition (molality of each element)
- Species distribution (activity, molality, log activity for each aqueous species)
- Saturation indices for all phases in database
- Charge balance and percent error
- Phase assemblage (moles transferred, delta moles)

### 5.2 Selected Output (.sel)

Tab-delimited file with user-chosen columns. Controlled by SELECTED_OUTPUT keyword:
- `-totals`: Element totals in mol/kgw
- `-molalities`: Individual species molalities
- `-activities`: Species log activities
- `-saturation_indices`: Phase SI values
- `-pH`, `-pe`, `-temperature`, `-ionic_strength`
- `-equilibrium_phases`: Phase mole changes

### 5.3 Key Output Variables

| Variable          | Unit       | Description                              |
|-------------------|------------|------------------------------------------|
| pH                | -          | Negative log hydrogen activity           |
| pe                | -          | Negative log electron activity           |
| Temperature       | Celsius    | Solution temperature                     |
| Ionic strength    | mol/kgw    | Solution ionic strength                  |
| Totals            | mol/kgw    | Element concentration (molal)            |
| Activity          | -          | Dimensionless activity of species        |
| Molality          | mol/kgw    | Molal concentration of species           |
| Saturation Index  | -          | log(IAP/K) for mineral phases            |
| Charge balance    | eq         | Anion-cation balance residual            |
| Water mass        | kg         | Mass of solvent water                    |

## 6. Output Description (from dag.yaml)

This section restates `dag.yaml`; if this text and the dag disagree, the dag wins.

**Headline output** (`validation_rank: 1`):

> `pH` - Negative log of hydrogen-ion activity in the modeled water solution (dimensionless)

| Output variable (dag `var`) | Rank | Unit | Description |
|-----------------------------|------|------|-------------|
| pH | 1 | dimensionless | Negative log of hydrogen-ion activity in the modeled water solution |

Other dag outputs: `pe`, `element_totals`, `species_distribution`, `saturation_index`,
`ionic_strength`, `specific_conductance`, `phase_amounts`, `transport_profiles`.

---

## 7. Unit Trap Table

These are the most common unit-related errors when preparing PHREEQC input:

| Trap ID | Input Variable     | Wrong Unit       | Correct Unit    | Effect                              | Fix                                   |
|---------|--------------------|------------------|-----------------|--------------------------------------|---------------------------------------|
| ut_001  | Concentration      | mg/L (ppm)       | mol/kgw (molal) | Off by molar-mass factor             | Use `units mg/L` or convert manually  |
| ut_002  | Temperature        | Fahrenheit        | Celsius          | Wrong equilibrium constants          | Convert: C = (F-32)*5/9              |
| ut_003  | Alkalinity         | mg/L as CaCO3    | meq/L            | 2x error (CaCO3 = 2 eq/mol)         | Use `as CaCO3` qualifier or divide   |
| ut_004  | Pressure           | bar               | atm              | ~1.3% error in gas fugacity          | 1 atm = 1.01325 bar                  |
| ut_005  | pe vs Eh           | mV                | pe (dimless)     | pe = Eh(mV)/(59.16 at 25C)          | Convert or use `-Eh` keyword          |
| ut_006  | Density            | g/cm3             | kg/L (same)      | Usually OK, but verify               | PHREEQC expects kg/L = g/cm3         |
| ut_007  | Dispersivity       | cm                | m                | Transport dispersion 100x wrong      | Convert cm to m                       |
| ut_008  | Time steps         | seconds           | varies           | KINETICS uses seconds by default     | Check `-step` units in KINETICS      |
| ut_009  | Exchange capacity  | meq/100g          | mol/kgw          | CEC must be in mol (not meq)         | Divide meq by 1000                   |
| ut_010  | Surface area       | cm2/g             | m2/g             | Surface site density off 10,000x     | 1 m2/g = 10,000 cm2/g               |

---

## 8. Tools Reference

| Tool                       | Stage | Purpose                                        |
|----------------------------|-------|------------------------------------------------|
| convert_solution_input.py  | s1    | Water chemistry data to PHREEQC SOLUTION block |
| convert_soil_params.py     | s3    | HWSD/SoilGrids to EXCHANGE/SURFACE blocks      |
| run_phreeqc.py             | s5    | Execute PHREEQC with preflight checks          |
| parse_output.py            | s6    | Parse .pqo/.sel output to CSV/JSON             |

---

## 9. Critical Domain Knowledge

### dk_001: Database must cover all elements in solution
If an element in the SOLUTION block is not defined as a SOLUTION_MASTER_SPECIES in the
database, PHREEQC will terminate with an error. Always verify element coverage before
running. Use `wateq4f.dat` for trace elements (As, U, Se) and `llnl.dat` for high-T systems.

### dk_002: Charge balance closure
PHREEQC requires charge balance. If measured water analyses have >5% charge balance error,
adjust one ion (typically Cl or SO4) using the `charge` keyword. Failing to do this causes
the Newton-Raphson solver to fail or converge to unphysical solutions.

### dk_003: pe and Eh are equivalent but not interchangeable
pe = Eh(V) * F / (2.303 * R * T). At 25C, pe = Eh(mV) / 59.16. Mixing these up shifts
redox speciation dramatically (e.g., Fe2+/Fe3+ ratio inverted).

### dk_004: Saturation Index sign convention
SI > 0 means supersaturated (mineral should precipitate). SI < 0 means undersaturated
(mineral should dissolve). SI = 0 is equilibrium. PHREEQC dissolves phases with SI < target
and precipitates with SI > target in EQUILIBRIUM_PHASES.

### dk_005: Pitzer model requires Pitzer database
Using `pitzer.dat` activates the Pitzer activity model automatically. Using `phreeqc.dat`
with Pitzer keywords will silently fall back to ion-association, producing incorrect results
for brines (ionic strength > 0.7 mol/kg).

### dk_006: Transport cell numbering starts at 1
Cell 0 is the boundary (influent). Cells 1 through n are the domain. Confusing 0-based and
1-based indexing leads to shifted concentration profiles in transport simulations.

### dk_007: KINETICS time units
The `-steps` keyword in KINETICS defines time in seconds by default. Rate expressions
in RATES blocks must also use seconds. Mixing hours/days into rate constants without
conversion produces rates that are 3600x or 86400x too fast/slow.

### dk_008: SELECTED_OUTPUT creates tab-delimited files
The .sel file uses tabs, not commas. Parsing with `pd.read_csv(..., sep=',')` creates a
single mangled column. Always use `sep='\t'`.

### dk_009: Mineral mole limits in EQUILIBRIUM_PHASES
The second number after SI in `EQUILIBRIUM_PHASES` is the initial mole amount. Setting it
to 0 means the mineral can only precipitate (not dissolve). Setting it to a large number
(e.g., 10) allows both dissolution and precipitation.

---

## 10. Validation

### Benchmark: Calcite Dissolution to Equilibrium

A standard analytical test case: pure water equilibrated with calcite at 25C should reach:
- pH ~8.3
- Ca ~1.3 mmol/L (52 mg/L)
- SI(Calcite) = 0.0

This can be verified against published values in Appelo & Postma (2005) and Parkhurst & Appelo (2013).

### Benchmark: Theis Drawdown (Transport)

For 1-D transport validation, PHREEQC's advection-dispersion transport can reproduce the
analytical Ogata-Banks solution for conservative tracer breakthrough.

## 11. Validated Results (from validation_convention.yaml)

This section restates `docs/validation_convention.yaml`; if this text and the convention
file disagree, the convention wins. The bars below are the cited field thresholds available
for the dag variables. Null convention bands are written as `no cited threshold`.

| Dag variable | Metric | Direction | Very good band | Good band | Satisfactory band | Citation keys |
|--------------|--------|-----------|----------------|-----------|-------------------|---------------|
| pH | absolute_error | minimize | no cited threshold (parkhurst1999, parkhurst1995) | no cited threshold (parkhurst1999, parkhurst1995) | <= 0.05 (parkhurst1999, parkhurst1995) | parkhurst1999, parkhurst1995 |
| pH | mae | minimize | no cited threshold (parkhurst1999, parkhurst1995) | no cited threshold (parkhurst1999, parkhurst1995) | <= 0.05 (parkhurst1999, parkhurst1995) | parkhurst1999, parkhurst1995 |
| pe | absolute_error | minimize | no cited threshold | no cited threshold | no cited threshold | no citation keys supplied by convention |

No achieved run metric is stated here unless it is present in the KI's validation outputs or
convention files. A PHREEQC run should be judged against these convention bars rather than
against intuition or remembered thresholds.

---

## 12. Calibration Parameters

| Parameter           | Keyword            | Typical Range      | Sensitivity |
|---------------------|--------------------|--------------------|-------------|
| log_k (minerals)    | PHASES             | varies by mineral  | High        |
| Dispersivity        | TRANSPORT          | 0.01-100 m         | High        |
| Exchange capacity   | EXCHANGE           | 0.001-1 mol/kgw    | Medium      |
| Surface site density| SURFACE            | 0.001-1 mol/kgw    | Medium      |
| Kinetic rate const. | RATES              | 10^-12 to 10^-6    | High        |
| Diffusion coeff.    | TRANSPORT          | 10^-10 to 10^-9 m2/s | Medium   |
| Porosity            | TRANSPORT          | 0.01-0.5           | High        |
| Number of cells     | TRANSPORT          | 10-1000            | Low (grid)  |

---

## 13. Coupling Points

| Integration Point     | Direction | Format              | Notes                         |
|-----------------------|-----------|---------------------|-------------------------------|
| MODFLOW-PHREEQC       | Bidir     | PHT3D linkage       | Flow field drives transport   |
| Reactive transport    | Input     | TRANSPORT keyword   | 1-D built-in                  |
| Surface water mixing  | Input     | MIX keyword         | Mix groundwater + surface     |
| Isotope models        | Output    | iso.dat database    | C-14 age dating               |
| TOUGHREACT            | Compare   | Same thermodynamics | Cross-validation              |
| Python (IPhreeqc)     | API       | COM/Python bindings | Scripted batch runs           |

---

## 14. Data Requirements

| Data Type          | Source                  | Format         | Key Fields                |
|--------------------|------------------------|----------------|---------------------------|
| Water chemistry    | Lab analysis / field   | CSV/Excel      | pH, T, major ions, trace  |
| Thermodynamic DB   | PHREEQC distribution   | .dat text      | log_k, delta_h, analytic  |
| Soil CEC           | HWSD / SoilGrids       | Raster/CSV     | CEC (cmol+/kg)            |
| Mineralogy         | XRD / GLiM             | Text/Shapefile  | Mineral fractions         |
| Hydraulic params   | GLHYMPS                | Shapefile       | K, porosity               |
| DEM                | SRTM / Copernicus      | GeoTIFF        | Elevation                 |
| Water table depth  | Fan et al.             | GeoTIFF        | WTD (m)                   |

---

## 15. Quick Start

```bash
# 1. Build PHREEQC
cd source/repo && mkdir build && cd build
cmake .. && make -j$(nproc)

# 2. Run example 1 (seawater speciation)
./phreeqc ../examples/ex1 ex1.out ../database/phreeqc.dat

# 3. Run with selected output
./phreeqc input.pqi output.pqo ../database/phreeqc.dat

# 4. Parse selected output
python3 ki/tools/parse_output.py --input results.sel --output results.csv
```

---

## 16. Diagnostic Triplets Reference

See `diagnostics/triplets.yaml` for the complete set. Key entries:

| ID     | Symptom                              | Root Cause                     |
|--------|--------------------------------------|--------------------------------|
| dt_001 | Concentrations 1000x too high        | mg/L not converted to mol/kgw  |
| dt_002 | Solver fails at first step           | Charge balance > 10%           |
| dt_003 | pe/Eh mismatch                       | Forgot pe = Eh/59.16 at 25C   |
| dt_004 | Missing element error                | Element not in database         |
| dt_005 | SI always 0 for target mineral       | Initial moles set to 0         |
| dt_006 | Transport profile shifted            | Cell indexing 0 vs 1           |

---

## 17. File Structure

```
ki/
├── SKILL.md                        # This file
├── knowledge_infrastructure.yaml   # Machine-readable package spec
├── tools/
│   ├── convert_solution_input.py   # Water chemistry → SOLUTION block
│   ├── convert_soil_params.py      # HWSD → EXCHANGE/SURFACE blocks
│   ├── run_phreeqc.py              # Execution wrapper
│   └── parse_output.py             # Output parser (.pqo/.sel → CSV)
├── docs/
│   ├── s1_solution_definition.md   # Solution input preparation
│   ├── s2_database_selection.md    # Database selection guide
│   ├── s3_reaction_setup.md        # Reaction configuration
│   ├── s4_execution.md             # Running PHREEQC
│   └── s5_output_analysis.md       # Output interpretation
└── diagnostics/
    └── triplets.yaml               # 15+ symptom-diagnosis-remedy entries
```
