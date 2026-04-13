# Stage 7: Model Execution

## Purpose

Build and run the EPANET simulation engine on a prepared .inp file, producing a text report (.rpt) and optional binary output (.out) file. Includes preflight validation, binary discovery, shared library configuration, and post-run error checking.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| EPANET input file | Stage 6 (INP assembly) | .inp text file |
| runepanet binary | cmake build | ELF executable |
| libepanet2.so | cmake build | Shared library |

## Outputs

| Output | Format | Used By |
|--------|--------|---------|
| Report file (.rpt) | Text | Human review, report parser |
| Binary output (.out) | Binary (4-byte aligned) | parse_epanet_output.py |
| Console output | Text | Execution wrapper |

## Procedure

### 1. Build EPANET (if not already built)

```bash
cd /path/to/EPANET/source/repo/SRC_engines
mkdir -p build && cd build
cmake .. -DBUILD_SHARED_LIBS=ON
make -j$(nproc)
```

**Outputs**:
- `build/src/run/runepanet` — CLI executable
- `build/src/solver/libepanet2.so` — Shared library

### 2. Set Library Path

The runepanet binary links dynamically against libepanet2.so:

```bash
export LD_LIBRARY_PATH=/path/to/build/src/solver:$LD_LIBRARY_PATH
```

### 3. Run EPANET (Direct CLI)

```bash
./runepanet network.inp report.rpt output.out
```

Arguments:
1. `network.inp` — Input file (required)
2. `report.rpt` — Report file (required)
3. `output.out` — Binary output (optional, but recommended for post-processing)

### 4. Run EPANET (via Wrapper)

```bash
python tools/run_epanet.py \
    --inp network.inp \
    --rpt report.rpt \
    --out output.out \
    --binary /path/to/runepanet \
    --timeout 300
```

The wrapper performs:
1. Binary discovery (searches build dirs, PATH)
2. Input file validation (required sections, syntax)
3. LD_LIBRARY_PATH setup
4. Execution with timeout
5. Output validation (error detection, magic number check)

### 5. Interpret Exit Codes

| Exit Code | Meaning | Action |
|-----------|---------|--------|
| 0 | Success | Proceed to output analysis |
| 1-99 | Warning (e.g., system unbalanced at some timestep) | Check report file, results may still be usable |
| 100+ | Error (see Appendix B of EPANET manual) | Fix input file and re-run |

### 6. Check Report File

Open the .rpt file and verify:
- Network summary matches expected topology
- Energy usage section present (if pumps exist)
- Node/Link results present for all reporting periods
- No "WARNING" or "ERROR" messages

## Verification

- [ ] runepanet binary exists and is executable
- [ ] libepanet2.so is accessible (LD_LIBRARY_PATH set)
- [ ] Exit code is 0 (or < 100 for warnings)
- [ ] Report file created and contains results
- [ ] Binary output file created (if requested) with correct magic number (516114521)
- [ ] No error messages in report file
- [ ] Simulation completed for full duration (not halted early)

## Traps

| Trap | Symptom | Prevention |
|------|---------|------------|
| **Missing libepanet2.so** | `error while loading shared libraries` | Set LD_LIBRARY_PATH to include solver build dir |
| **Error 200: cannot find input file** | Wrong working directory or path | Use absolute paths or cd to correct directory |
| **Error 110: cannot solve hydraulics** | Disconnected network, no fixed-grade node | Check network connectivity, ensure reservoir/tank exists |
| **Unbalanced at timestep** | Pump/valve status oscillating | Increase Trials, add UNBALANCED CONTINUE, check controls |
| **Negative pressures** | Demands exceed supply capacity | Use PDA demand model, or reduce demands, or add supply |
| **Binary output incomplete** | Simulation halted early | Check UNBALANCED option, increase max trials |
| **Very slow execution** | Very small quality timestep on large network | Increase quality timestep (but keep ≤ hydraulic step) |

## Example

Complete build-and-run sequence:

```bash
# Build
cd SRC_engines
mkdir -p build && cd build
cmake .. && make -j4

# Set library path
export LD_LIBRARY_PATH=$(pwd)/src/solver:$LD_LIBRARY_PATH

# Run tutorial
./src/run/runepanet ../../User_Manual/docs/tutorial.inp tutorial.rpt tutorial.out

# Expected output:
# ... Running EPANET Version 2.2.0
# ... EPANET ran successfully.
```
