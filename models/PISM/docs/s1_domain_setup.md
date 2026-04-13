# S1: Domain Setup — Grid and Projection Configuration

## Purpose

Define the computational domain for a PISM simulation: spatial extent, grid resolution,
vertical layering, and map projection. Incorrect domain setup leads to grid mismatches,
distorted geometry, or memory exhaustion.

## Inputs

| Input | Format | Example |
|-------|--------|---------|
| Target ice sheet/glacier extent | Geographic knowledge | Greenland: ~2600 km × 1400 km |
| Desired horizontal resolution | km | 5, 10, 20, 40 |
| Map projection | PROJ string | `+proj=stere +lat_0=90 +lat_ts=71 +lon_0=-39 ...` |
| Vertical extent | meters | 4000 (ice), 2000 (bedrock thermal) |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Grid parameters | CLI flags | `-Mx`, `-My`, `-Mz`, `-Lz`, `-dx`, `-dy` |
| Projection metadata | NetCDF attribute | `proj` global attribute in input file |
| Grid registration | CLI flag | `-grid.registration corner` or `center` |

## Procedure

### Step 1: Choose Projection

For polar ice sheets, use polar stereographic:
- **Greenland**: `+proj=stere +lat_0=90 +lat_ts=71 +lon_0=-39 +k=1 +x_0=0 +y_0=0 +ellps=WGS84`
- **Antarctica**: `+proj=stere +lat_0=-90 +lat_ts=-71 +lon_0=0 +k=1 +x_0=0 +y_0=0 +ellps=WGS84`
- **Mountain glaciers**: UTM zone or local stereographic

### Step 2: Set Horizontal Grid

PISM can accept grid specification in two ways:

```bash
# Method 1: By resolution (recommended for bootstrap)
-dx 5km -dy 5km

# Method 2: By grid point count and domain half-widths
-Mx 301 -My 561 -Lx 750km -Ly 1400km
```

Grid point recommendations by resolution:

| Resolution | Greenland Mx×My | Antarctica Mx×My | Memory (approx) |
|-----------|----------------|-----------------|-----------------|
| 40 km | 38×69 | 141×141 | ~100 MB |
| 20 km | 76×138 | 281×281 | ~500 MB |
| 10 km | 151×276 | 561×561 | ~2 GB |
| 5 km | 301×551 | 1121×1121 | ~8 GB |
| 2 km | 751×1376 | 2801×2801 | ~50 GB |

### Step 3: Set Vertical Grid

```bash
# Coarse (20-40 km horizontal)
-Mz 101 -Lz 4000 -Mbz 11 -Lbz 2000 -z_spacing equal

# Fine (5-10 km horizontal)
-Mz 201 -Lz 4000 -Mbz 21 -Lbz 2000 -z_spacing equal

# Very fine (2-3 km horizontal)
-Mz 401 -Lz 4000 -Mbz 41 -Lbz 2000 -z_spacing equal
```

- `Mz`: Vertical ice layers (more = better thermal resolution)
- `Lz`: Top of computational domain (meters above bedrock, must exceed max ice thickness)
- `Mbz`: Bedrock thermal layers
- `Lbz`: Bedrock thermal depth (meters below ice-bedrock interface)

### Step 4: Grid Registration

```bash
-grid.registration corner   # Grid points at cell corners (default for bootstrap)
```

### Step 5: Skip Mechanism

For efficiency, PISM can skip expensive computations on some time steps:

```bash
-skip -skip_max 10   # Coarse grids
-skip -skip_max 50   # Fine grids
```

## Verification

1. Check grid dimensions appear in PISM's startup log:
   ```
   * Grid parameters: Lx = 750 km, Ly = 1400 km, ...
   ```

2. Verify domain covers the ice sheet:
   ```bash
   ncdump -h output.nc | grep -E "^.*(x|y) ="
   ```

3. Confirm memory fits available RAM:
   ```
   Total memory = Mx × My × Mz × 8 bytes × ~20 fields ÷ nprocs
   ```

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| Lz too small | FATAL | Ice thickness exceeds domain height → crash |
| Coordinates in km not m | FATAL | Grid mismatch with input data |
| Wrong projection | SILENT | Ice placed in wrong location |
| Too many grid points | FATAL | Out of memory |
| Grid registration mismatch | DEGRADED | Half-cell offset in all fields |

## Example

```bash
# Standard Greenland at 20 km resolution
mpiexec -n 8 pism \
  -i pism_Greenland_5km_v1.1.nc -bootstrap \
  -grid.registration corner \
  -dx 20km -dy 20km \
  -Mz 101 -Lz 4000 \
  -Mbz 11 -Lbz 2000 \
  -z_spacing equal \
  -skip -skip_max 10 \
  -y 1000 \
  -o greenland_20km.nc
```
