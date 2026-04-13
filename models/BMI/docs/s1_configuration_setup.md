# S1: Configuration Setup

## Purpose

Generate a valid configuration file for any BMI-wrapped model. BMI requires that models read their parameters from a configuration file passed to `initialize(config_file)`. This stage creates that file from user-supplied parameters, using YAML format (recommended by CSDMS).

## Inputs

| Input              | Type   | Units         | Description                              |
|--------------------|--------|---------------|------------------------------------------|
| Model type         | string | —             | Template identifier (e.g., `heat`)       |
| Grid shape         | [int]  | nodes         | [ny, nx] in **ij-order** (NOT xy-order)  |
| Grid spacing       | [float]| model units   | [dy, dx] in **ij-order**                 |
| Grid origin        | [float]| model units   | [y0, x0] lower-left corner               |
| Start time         | float  | model time    | Usually 0.0                              |
| End time           | float  | model time    | Must be > start time                     |
| Time step (dt)     | float  | model time    | Must be > 0                              |
| Initial conditions | dict   | variable-specific | Keyed by CSDMS Standard Name          |
| Boundary conditions| dict   | variable-specific | Model-dependent                       |

## Outputs

| Output       | Format | Description                                  |
|--------------|--------|----------------------------------------------|
| Config file  | YAML   | Ready for `bmi.initialize(config_file)`      |

## Procedure

1. **Select template**: Choose from built-in templates (`heat`, `custom`) or provide a custom dict
2. **Apply overrides**: Merge user parameters into the template (deep merge)
3. **Validate grid parameters**: Check shape has ≥2 positive-integer dimensions, spacing is positive
4. **Validate time parameters**: Check dt > 0, end > start
5. **Generate YAML**: Write with `yaml.dump()`, `default_flow_style=False`
6. **Verify**: Re-read YAML, confirm required sections exist

```bash
# Example usage
python config_generator.py --model-type heat --nx 20 --ny 10 --dt 0.5 --end-time 200 -o heat_config.yaml
```

## Verification

- [ ] Output file exists and is valid YAML
- [ ] Contains `grid` section with `shape`, `spacing`, `origin`
- [ ] Contains `time` section with `start`, `end`, `dt`
- [ ] Grid shape is in ij-order: `[ny, nx]`, NOT `[nx, ny]`
- [ ] All values are within physical bounds

## Traps

| Trap | Description | Detection | Fix |
|------|-------------|-----------|-----|
| **xy vs ij ordering** | Passing shape as [nx, ny] instead of [ny, nx] | Grid looks transposed in output | Swap dimensions: shape=[ny, nx] |
| **Zero time step** | dt=0 causes infinite loop in `update()` | Model hangs | Set dt > 0 |
| **Missing config file** | `initialize()` called with nonexistent path | RuntimeError from model | Verify path before calling |
| **Non-YAML format** | Config in INI/JSON/namelist but model expects YAML | Parse error in initialize | CSDMS recommends YAML; convert if needed |

## Example

```yaml
# heat_config.yaml
grid:
  shape: [10, 20]       # [ny, nx] — BMI ij-order
  spacing: [1.0, 1.0]   # [dy, dx]
  origin: [0.0, 0.0]    # [y0, x0]
time:
  start: 0.0
  end: 100.0
  dt: 0.25
initial_conditions:
  temperature: 0.0
boundary_conditions:
  top: 0.0
  bottom: 0.0
  left: 0.0
  right: 0.0
alpha: 1.0
```
