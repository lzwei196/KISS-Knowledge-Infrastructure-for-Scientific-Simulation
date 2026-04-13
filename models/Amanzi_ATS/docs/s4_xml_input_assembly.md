# S4: XML Input File Assembly

## Purpose

Assemble the complete XML input file that defines the Amanzi/ATS simulation. This is the central configuration step where mesh, materials, boundary conditions, initial conditions, solver settings, and output specifications are combined into a single XML file.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Mesh specification | Stage 3 | XML block or .exo file path |
| Material parameters | Stage 2 | JSON from convert_soil_to_amanzi.py |
| Recharge/BC parameters | Stage 1 | JSON from convert_forcing_to_amanzi.py |
| Solver settings | User / defaults | GMRES + Hypre AMG |
| Output specification | User | Observation points, vis frequency |

## Outputs

| Output | Format | Destination |
|--------|--------|-------------|
| Complete XML input file | .xml | `amanzi --xml_file=input.xml` |

## Procedure

### 1. Choose Input Format Version

**Version 2.x (recommended)** — cleaner, XML-native syntax:
```xml
<amanzi_input version="2.3.2" type="unstructured">
  <model_description name="My Simulation">
    <units>
      <length_unit>m</length_unit>
      <time_unit>s</time_unit>
      <mass_unit>kg</mass_unit>
      <conc_unit>molar</conc_unit>
    </units>
  </model_description>
  ...
</amanzi_input>
```

**Version 1.x** — Teuchos ParameterList format:
```xml
<ParameterList name="Main">
  <Parameter name="Amanzi Input Format Version" type="string" value="1.2.2"/>
  ...
</ParameterList>
```

### 2. Define Process Kernels

```xml
<process_kernels>
  <flow state="on" model="richards"/>
  <transport state="on" algorithm="explicit first-order" sub_cycling="on"/>
  <chemistry engine="none" state="off" process_model="none"/>
</process_kernels>
```

Available flow models: `richards`, `saturated`, `constant`
Transport algorithms: `explicit first-order`, `explicit second-order`
Chemistry engines: `amanzi`, `pflotran`, `crunchflow`, `none`

### 3. Define Execution Control

```xml
<execution_controls>
  <verbosity level="high"/>
  <!-- Steady-state initialization -->
  <execution_control start="0.0" end="0.0" init_dt="1.0" max_dt="1e8"
                     increase_factor="1.25" mode="steady"/>
  <!-- Transient simulation -->
  <execution_control start="0.0" end="3.156e8" init_dt="100"
                     max_dt="1e6" increase_factor="1.4"
                     reduction_factor="0.8" mode="transient"/>
</execution_controls>
```

Time values are in the unit declared in `<time_unit>` (typically seconds).
- `init_dt`: Initial timestep (start small: 1-100 s)
- `max_dt`: Maximum timestep (typically 1e5-1e7 s)
- `increase_factor`: Timestep growth factor per step (1.2-1.5)
- `reduction_factor`: Timestep cut on non-convergence (0.5-0.8)

### 4. Set Numerical Controls

```xml
<numerical_controls>
  <unstructured_controls>
    <unstr_flow_controls>
      <preconditioning_strategy>linearized_operator</preconditioning_strategy>
    </unstr_flow_controls>
    <unstr_linear_solver>
      <method>gmres</method>
      <max_iterations>100</max_iterations>
      <tolerance>1.0e-15</tolerance>
    </unstr_linear_solver>
    <unstr_preconditioners>
      <hypre_amg>
        <hypre_cycle_applications>5</hypre_cycle_applications>
        <hypre_smoother_sweeps>3</hypre_smoother_sweeps>
        <hypre_tolerance>0.0</hypre_tolerance>
        <hypre_strong_threshold>0.5</hypre_strong_threshold>
      </hypre_amg>
    </unstr_preconditioners>
  </unstructured_controls>
</numerical_controls>
```

### 5. Define Materials (from Stage 2 output)

```xml
<materials>
  <material name="Soil">
    <assigned_regions>Entire Domain</assigned_regions>
    <mechanical_properties>
      <porosity model="constant" value="0.41"/>
      <specific_storage model="constant" value="1e-5"/>
    </mechanical_properties>
    <permeability x="1.25e-12" y="1.25e-12" z="1.25e-12"/>
    <cap_pressure model="van_genuchten">
      <parameters alpha="7.65e-05" m="0.4709" sr="0.1585"/>
    </cap_pressure>
    <rel_perm model="mualem"/>
  </material>
</materials>
```

### 6. Define Initial and Boundary Conditions

```xml
<initial_conditions>
  <initial_condition name="Hydrostatic">
    <assigned_regions>Entire Domain</assigned_regions>
    <liquid_phase name="water">
      <liquid_component name="water">
        <linear_pressure gradient="0.0,0.0,-9806.65"
                        reference_coord="0.0,0.0,10.0" value="101325"/>
      </liquid_component>
    </liquid_phase>
  </initial_condition>
</initial_conditions>

<boundary_conditions>
  <boundary_condition name="Recharge">
    <assigned_regions>Top Surface</assigned_regions>
    <liquid_phase name="water">
      <liquid_component name="water">
        <inward_mass_flux function="constant" start="0.0" value="9.49e-6"/>
      </liquid_component>
    </liquid_phase>
  </boundary_condition>
  <boundary_condition name="Water Table">
    <assigned_regions>Bottom</assigned_regions>
    <liquid_phase name="water">
      <liquid_component name="water">
        <uniform_pressure function="constant" start="0.0" value="101325"/>
      </liquid_component>
    </liquid_phase>
  </boundary_condition>
</boundary_conditions>
```

### 7. Configure Output

```xml
<output>
  <vis>
    <base_filename>plot</base_filename>
    <num_digits>5</num_digits>
    <time_macros>Every_year</time_macros>
  </vis>
  <observations>
    <filename>observations.out</filename>
    <liquid_phase name="water">
      <aqueous_pressure>
        <assigned_regions>Well_1</assigned_regions>
        <functional>point</functional>
        <time_macros>Monthly</time_macros>
      </aqueous_pressure>
    </liquid_phase>
  </observations>
</output>
```

## Verification

- XML validates against Amanzi's schema (well-formed, required blocks present).
- All region names in BCs/ICs/materials match defined regions.
- Physical constants consistent (ρg = 9806.65 Pa/m in linear_pressure gradient).
- Time range covers intended simulation period.

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| **dt_008** | Gravity vector wrong sign | Upward flow |
| **dt_016** | Missing required XML block | Fatal parse error |
| **dt_017** | Zero-flux BC where recharge intended | No water input |
| **dt_006** | Mixed time units | Wrong simulation duration |

## Example

A minimal Richards equation XML for a 1D column with recharge:

```xml
<amanzi_input version="2.3.2" type="unstructured">
  <model_description name="1D_Richards_Column">
    <units>
      <length_unit>m</length_unit>
      <time_unit>s</time_unit>
      <mass_unit>kg</mass_unit>
      <conc_unit>molar</conc_unit>
    </units>
  </model_description>

  <process_kernels>
    <flow state="on" model="richards"/>
    <transport state="off"/>
    <chemistry engine="none" state="off"/>
  </process_kernels>

  <execution_controls>
    <verbosity level="medium"/>
    <execution_control start="0.0" end="3.156e7" init_dt="10"
                       max_dt="1e5" mode="transient"/>
  </execution_controls>

  <!-- Mesh, regions, materials, ICs, BCs, output as above -->
</amanzi_input>
```
