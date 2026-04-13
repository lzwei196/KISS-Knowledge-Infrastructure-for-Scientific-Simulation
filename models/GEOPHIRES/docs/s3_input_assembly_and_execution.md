# Stage 3–4: Input Assembly and Execution

## Purpose

Merge reservoir and economic parameters into a complete GEOPHIRES input file,
validate parameter compatibility, and execute the simulation.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| reservoir_params.txt | Stage 1 | Reservoir parameters in GEOPHIRES format |
| economics_params.txt | Stage 2 | Economic parameters in GEOPHIRES format |
| overrides.json | Optional | Parameter overrides (JSON) |
| GEOPHIRES installation | Phase 3 build | Installed geophires_x Python package |

## Outputs

| Output | Description |
|--------|-------------|
| complete_input.txt | Merged GEOPHIRES input file |
| HDR.out | Text-format simulation report |
| HDR.json | JSON-format simulation results |

## Procedure

### Part A: Input Assembly (Stage 3)

1. **Merge parameter files**:
   ```bash
   python generate_input_file.py \
       --reservoir reservoir_params.txt \
       --economics economics_params.txt \
       --output complete_input.txt
   ```

2. **Review compatibility warnings**:
   - Reservoir model / required parameter mismatches
   - End-use / plant type compatibility
   - Suspicious unit values (depth > 100, gradient < 1, etc.)

3. **Apply overrides** if needed:
   ```bash
   python generate_input_file.py \
       --reservoir reservoir_params.txt \
       --economics economics_params.txt \
       --overrides '{"Plant Lifetime": 40}' \
       --output complete_input.txt
   ```

### Part B: Execution (Stage 4)

4. **Run preflight checks**:
   - Input file exists and has valid format
   - geophires_x is importable in the target environment
   - All referenced external files exist (for Model 5, 6)

5. **Execute GEOPHIRES**:
   ```bash
   python run_geophires.py \
       --input complete_input.txt \
       --output results.out \
       --venv /path/to/venv \
       --timeout 300
   ```

   Or directly:
   ```bash
   python -m geophires_x complete_input.txt results.out
   ```

6. **Check execution status**:
   - Exit code 0 = success
   - Check for .out and .json output files
   - Review stderr for warnings

## Verification

- Output file is non-empty
- Output contains "SUMMARY OF RESULTS" section
- LCOE/LCOH values are within plausible ranges
- Production profile spans the full plant lifetime

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Input file not found | FileNotFoundError | Check path and working directory |
| geophires_x not installed | ModuleNotFoundError | pip install from source |
| Parameter conflicts | Silent default values | Review all warnings from assembly |
| Timeout on complex models | Process killed | Increase timeout, simplify model |
| Missing external data files | Runtime error | Ensure Model 5/6 data files exist |
| Default output path (HDR.out) | Overwrites previous results | Specify unique output path |

## Example

Complete workflow:
```bash
# Stage 1: Convert reservoir data
python convert_reservoir_params.py \
    --config reservoir_config.json \
    --output reservoir_params.txt

# Stage 2: Convert economic data
python convert_site_economics.py \
    --config economics_config.json \
    --output economics_params.txt

# Stage 3: Assemble input file
python generate_input_file.py \
    --reservoir reservoir_params.txt \
    --economics economics_params.txt \
    --output complete_input.txt

# Stage 4: Run GEOPHIRES
python -m geophires_x complete_input.txt results.out

# Verify output
head -50 results.out
```

Typical execution time: 0.2–5 seconds for standard models, up to 60 seconds for SBT.
