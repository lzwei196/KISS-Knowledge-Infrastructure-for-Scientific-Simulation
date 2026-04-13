# Stage 3: Parameters — Material Properties and Constitutive Models

## Purpose

Define material properties for the simulation domain. OGS uses a hierarchical `<media>` system with medium → phase → component → property levels. Properties can be constant, spatially varying (from mesh data), or state-dependent (functions of pressure, temperature, saturation).

## Inputs

- Soil/rock texture data (HWSD, borehole logs, geotechnical reports)
- Laboratory measurements (permeability, porosity, thermal properties)
- Literature values for constitutive model parameters

## Outputs

- Material property definitions in OGS XML format (`<media>` block)
- Spatially heterogeneous fields as mesh data arrays (in VTU files)
- JSON parameter file from `convert_soil_to_ogs.py`

## Procedure

### Step 1: Define medium properties

Each material zone (MaterialID in mesh) gets a `<medium>` block:

```xml
<media>
  <medium id="0">  <!-- Matches MaterialID=0 in mesh -->
    <phases>
      <phase>
        <type>AqueousLiquid</type>
        <properties>
          <property><name>viscosity</name><type>Constant</type><value>1.0e-3</value></property>
          <property><name>density</name><type>Constant</type><value>998.2</value></property>
        </properties>
      </phase>
      <phase>
        <type>Solid</type>
        <properties>
          <property><name>density</name><type>Constant</type><value>2650</value></property>
          <property><name>thermal_conductivity</name><type>Constant</type><value>2.5</value></property>
          <property><name>specific_heat_capacity</name><type>Constant</type><value>800</value></property>
        </properties>
      </phase>
    </phases>
    <properties>
      <!-- Medium-scale (porous medium) properties -->
      <property><name>permeability</name><type>Constant</type><value>1e-12</value></property>
      <property><name>porosity</name><type>Constant</type><value>0.3</value></property>
      <property><name>storage</name><type>Constant</type><value>1e-9</value></property>
    </properties>
  </medium>
</media>
```

### Step 2: Choose constitutive models (for Richards/unsaturated flow)

**van Genuchten-Mualem** (most common for unsaturated zone):

```xml
<property>
  <name>saturation</name>
  <type>SaturationVanGenuchten</type>
  <residual_liquid_saturation>0.15</residual_liquid_saturation>
  <residual_gas_saturation>0.0</residual_gas_saturation>
  <exponent>0.6</exponent>  <!-- m = 1 - 1/n -->
  <p_b>5000</p_b>            <!-- Entry pressure in Pa -->
</property>
<property>
  <name>relative_permeability</name>
  <type>RelPermVanGenuchten</type>
  <residual_liquid_saturation>0.15</residual_liquid_saturation>
  <residual_gas_saturation>0.0</residual_gas_saturation>
  <exponent>0.6</exponent>
  <minimum_relative_permeability_liquid>1e-9</minimum_relative_permeability_liquid>
</property>
```

### Step 3: Convert from soil texture using pedotransfer functions

Use the tool: `python tools/convert_soil_to_ogs.py`

```bash
python tools/convert_soil_to_ogs.py \
  --sand 60 --clay 15 --organic 2.0 \
  --output soil_params.json
```

This produces:
- Intrinsic permeability (m²) from Saxton-Rawls Ksat
- van Genuchten parameters (m, p_b in Pa) from Carsel-Parrish
- Porosity, storage, thermal properties

### Step 4: Key parameter reference table

| Parameter | XML name | Unit | Typical Range | Notes |
|-----------|----------|------|---------------|-------|
| Intrinsic permeability | `permeability` | m² | 1e-18 – 1e-8 | NOT hydraulic conductivity |
| Porosity | `porosity` | – | 0.01 – 0.6 | Total porosity |
| Specific storage | `storage` | 1/Pa | 1e-12 – 1e-6 | Must be > 0 for transient |
| Liquid density | `density` (AqueousLiquid) | kg/m³ | 995 – 1025 | ~998 at 20°C |
| Liquid viscosity | `viscosity` (AqueousLiquid) | Pa·s | 2.8e-4 – 1.8e-3 | ~1e-3 at 20°C |
| Solid density | `density` (Solid) | kg/m³ | 2200 – 2800 | Grain density |
| Thermal conductivity | `thermal_conductivity` | W/(m·K) | 0.5 – 5.0 | Bulk or phase |
| Specific heat capacity | `specific_heat_capacity` | J/(kg·K) | 700 – 4200 | Phase-specific |
| vG entry pressure | `p_b` | Pa | 500 – 50000 | NOT α directly |
| vG exponent | `exponent` | – | 0.1 – 0.9 | m = 1 - 1/n |
| Residual saturation | `residual_liquid_saturation` | – | 0.0 – 0.3 | Irreducible water |
| Biot coefficient | `biot_coefficient` | – | 0 – 1 | For HydroMechanics |
| Young's modulus | (process-specific) | Pa | 1e7 – 1e11 | For mechanics |
| Poisson's ratio | (process-specific) | – | 0.1 – 0.45 | For mechanics |

## Verification

- [ ] Permeability in m² (not m/s, not Darcy): values should be 1e-18 to 1e-8
- [ ] vG entry pressure in Pa (not α in 1/cm): values should be 100 to 100,000
- [ ] Storage > 0 for transient simulations
- [ ] Density and viscosity physically reasonable
- [ ] MaterialIDs in mesh match medium IDs in `<media>`

## Traps

| Trap | Factor | Detection |
|------|--------|-----------|
| Ksat (m/s) used as permeability (m²) | ~1e7× too high | Check if value > 1e-6 |
| vG α (1/cm) used directly as p_b | Wrong by ~1e5 | Check if p_b < 10 Pa |
| Porosity = 0 | Zero storage, no flow | Check all media blocks |
| Missing `<storage>` property | Defaults may be wrong | Explicitly set for each medium |
| Temperature-dependent viscosity not set | Constant μ at wrong T | Use `ViscosityTemperatureDependent` for thermal |

## Example

Sandy loam aquifer with default water properties:

```xml
<medium id="0">
  <phases>
    <phase><type>AqueousLiquid</type>
      <properties>
        <property><name>viscosity</name><type>Constant</type><value>1.002e-3</value></property>
        <property><name>density</name><type>Constant</type><value>998.2</value></property>
      </properties>
    </phase>
  </phases>
  <properties>
    <property><name>permeability</name><type>Constant</type><value>1.08e-12</value></property>
    <property><name>porosity</name><type>Constant</type><value>0.41</value></property>
    <property><name>storage</name><type>Constant</type><value>1e-9</value></property>
    <property><name>reference_temperature</name><type>Constant</type><value>293.15</value></property>
  </properties>
</medium>
```
