# Stage 03 — Soil profile

## Purpose
Build the `<run>.SOL` file with layer-by-layer physical and chemical
soil properties.

## Inputs
- Site lat, lon (for HWSD query)
- Optional: number of layers (default 6)

## Outputs
`<workspace>/<run>.SOL` with:
- Row 0: soil series name and order
- Row 1: albedo, slope, hydrologic group, CN2
- Row 2: global soil params
- Rows 3+: 6×F10.2 per physical/chemical property, 6 layers

## Procedure
1. Copy `templates/umstead.SOL` as `<run>.SOL`.
2. `ki_tools_common.soil_utils.lookup_hwsd(lat, lon)` returns dict.
3. Build per-layer arrays (6 values each):
   - depth_bottom (m): 0.10, 0.20, 0.30, 0.50, 0.75, 1.00
   - bulk_density (t/m3)
   - wilting point (0.05 + 0.006·clay)
   - field capacity (0.10 + 0.008·clay + 0.002·silt)
   - sand_pct, silt_pct, rock_frag (%)
   - org_C (%) = HWSD g/g × 100 (once!)
   - pH, CEC
4. Overwrite matching rows; write back with CRLF.

## Verification
- Line count matches template.
- `awk 'NR==5 {print NF}' <run>.SOL` shows 6 fields.
- `.OUT` echo shows correct soil name and depth.
- `.ANN` Q and ET are physically plausible.

## Traps
- **Organic C units**: HWSD g/g → percent by ×100 once (triplet EPIC_016).
- **Row order is fixed**: depth_bottom must stay at row 3.
- **HWSD lookup may fail**: tool keeps template on failure (valid NC clay loam).
- **Layer count**: tool uses 6 layers. To extend, all rows must grow.

## Example
```bash
python tools/build_soil_file.py --name raleigh \
    --lat 35.86 --lon -78.74 --workspace /tmp/epic_run
```
