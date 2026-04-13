# S3: Physical Properties Configuration

## Purpose

Define fluid physical properties (viscosity, density), turbulence model
selection, and gravity vector for the simulation. Correct property values
are essential for matching the physical Reynolds number and flow regime.

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| Kinematic viscosity | Fluid tables | Scalar | m^2/s |
| Density | Fluid tables (compressible only) | Scalar | kg/m^3 |
| Turbulence model | Flow regime analysis | String | - |
| Gravity | Problem orientation | Vector (3) | m/s^2 |
| Surface tension | Fluid pair tables (VoF only) | Scalar | N/m |

## Outputs

| Output | Location | Format |
|--------|----------|--------|
| physicalProperties | constant/physicalProperties | OpenFOAM dictionary |
| momentumTransport | constant/momentumTransport | OpenFOAM dictionary |
| g | constant/g | uniformDimensionedVectorField |
| transportProperties | constant/transportProperties (VoF) | OpenFOAM dictionary |

## Procedure

### 1. Determine kinematic viscosity

**CRITICAL**: OpenFOAM uses kinematic viscosity nu [m^2/s], NOT dynamic
viscosity mu [Pa.s]. Convert: `nu = mu / rho`.

| Fluid | Temperature | nu [m^2/s] | mu [Pa.s] | rho [kg/m^3] |
|-------|-------------|------------|-----------|--------------|
| Water | 20C | 1.004e-6 | 1.002e-3 | 998.2 |
| Water | 10C | 1.307e-6 | 1.307e-3 | 999.7 |
| Water | 4C | 1.568e-6 | 1.567e-3 | 999.97 |
| Seawater | 15C | 1.19e-6 | 1.22e-3 | 1025 |
| Air | 20C | 1.516e-5 | 1.825e-5 | 1.204 |
| Oil (light) | 20C | 5.0e-6 | 4.25e-3 | 850 |

### 2. Select turbulence model

| Re Range | Flow Regime | Recommended Model |
|----------|-------------|-------------------|
| < 2300 (pipe) | Laminar | laminar |
| 2300-10000 | Transitional | kOmegaSST or laminar |
| > 10000 | Fully turbulent | kEpsilon, kOmegaSST |
| Complex geometry | Separated flow | kOmegaSST (best general) |
| High accuracy | Resolved turbulence | LES (fine mesh required) |

### 3. Set gravity

Standard conventions:
- **Y-up** (most common): g = (0 -9.81 0)
- **Z-up** (GIS/geoscience): g = (0 0 -9.81)
- **No gravity** (internal flow, no buoyancy): g = (0 0 0)

### 4. Run tool

```bash
python convert_properties_to_openfoam.py \
    --case-dir ./myCase \
    --fluid water \
    --turbulence-model kOmegaSST \
    --output result.json
```

For custom properties:
```bash
python convert_properties_to_openfoam.py \
    --case-dir ./myCase \
    --nu 1.307e-6 \
    --rho 999.7 \
    --turbulence-model kEpsilon
```

## Verification

1. Check nu value is kinematic (order 1e-6 for water, 1e-5 for air)
2. Verify Reynolds number: Re = U * L / nu (should match expected regime)
3. Confirm turbulence model matches Re regime
4. Gravity direction consistent with mesh orientation
5. For VoF: both phase properties defined with correct sigma

## Traps

| Trap | Symptom | Prevention |
|------|---------|------------|
| Dynamic viscosity (Pa.s) instead of kinematic (m^2/s) | Re off by factor ~1000, wrong flow regime | Always divide mu by rho |
| Wrong gravity axis | Heavy fluid floats, light fluid sinks | Match to mesh coordinate system |
| Gravity sign positive | Buoyancy reversed | Gravity must point downward (negative) |
| Missing sigma in VoF | No surface tension, phases don't separate | Always define sigma for multiphase |
| laminar model at high Re | No turbulent mixing, unrealistic results | Check Re before selecting model |

## Example

Configure water flow in an open channel (Z-up convention):
```bash
python convert_properties_to_openfoam.py \
    --case-dir ./openChannel \
    --properties-json - <<'EOF'
{
    "nu": 1.004e-6,
    "rho": 998.2,
    "turbulence_model": "kOmegaSST",
    "gravity": [0, 0, -9.81],
    "phases": {
        "water": {"nu": 1.004e-6, "rho": 998.2},
        "air":   {"nu": 1.516e-5, "rho": 1.204}
    },
    "sigma": 0.072
}
EOF
```
