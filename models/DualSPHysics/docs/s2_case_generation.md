# Stage 2: Case Generation (GenCase)

## Purpose

Convert the XML case definition into initial particle distribution files (bi4 format). GenCase reads the geometry commands, creates particles at spacing dp, assigns material markers (MK values), and writes the binary output that DualSPHysics reads.

## Inputs

| Input | Format | Source |
|-------|--------|--------|
| `Case_Def.xml` | XML | Stage 1 output |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `Case.bi4` | Binary | Initial particle positions, types, MK values |
| `Case_Actual.xml` | XML | Resolved XML with computed values |
| `Case_MkCells.xml` | XML | MK cell definitions |
| `Case_*.vtk` | VTK | Geometry visualization files |
| `Case.ibi4` | Text | Header/metadata |

## Procedure

1. **Run GenCase**:
   ```bash
   GenCase_linux64 CaseDef output/CaseName -save:all
   ```
   - First argument: input XML (without .xml extension)
   - Second argument: output path prefix
   - `-save:all`: save all auxiliary files (VTK, XML)

2. **Check output**:
   - Verify particle counts in stdout
   - Check that fluid and boundary particles are reasonable
   - Visualize VTK files in ParaView to check geometry

3. **Common GenCase options**:
   - `-save:all`: Save all files (recommended)
   - `-save:vtk`: Save VTK only
   - `-save:binx`: Save binary only

## Verification

- [ ] GenCase exits with code 0
- [ ] `Case.bi4` file exists and is non-empty
- [ ] Total particle count is reasonable for dp (not OOM)
- [ ] Fluid particles > 0
- [ ] Boundary particles form complete enclosure
- [ ] VTK visualization shows expected geometry

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dp too small | GenCase runs out of memory | Increase dp |
| Geometry extends beyond pointmin/pointmax | Particles clipped | Expand domain |
| Overlapping fluid and bound regions | Duplicate particles | Fix geometry order |
| Missing GenCase binary | "command not found" | Check bin/linux/ path |
| GenCase not executable | Permission denied | chmod +x GenCase_linux64 |
| Wrong LD_LIBRARY_PATH | Shared library errors | Export LD_LIBRARY_PATH |

## Example

```bash
export dirbin=bin/linux
export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:${dirbin}

# Generate case
${dirbin}/GenCase_linux64 CaseDambreak_Def output/CaseDambreak -save:all

# Expected output:
# Total particles: 245832
# Boundary particles: 183456
# Fluid particles: 62376
```

## Particle Count Estimation

For 3D: `N ≈ Volume / dp^3`

| dp (m) | 1m^3 volume | 10m^3 volume | 100m^3 volume |
|--------|-------------|--------------|---------------|
| 0.1 | 1,000 | 10,000 | 100,000 |
| 0.05 | 8,000 | 80,000 | 800,000 |
| 0.01 | 1,000,000 | 10,000,000 | 100,000,000 |
| 0.005 | 8,000,000 | 80,000,000 | 800,000,000 |
