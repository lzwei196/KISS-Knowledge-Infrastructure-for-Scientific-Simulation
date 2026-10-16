#!/usr/bin/env python3
"""
Convert HWSD (Harmonized World Soil Database) soil data to SWAP
Mualem-van Genuchten hydraulic parameters.

SWAP requires these parameters per soil layer (in .swp file):
  ORES   - Residual water content [0..1 cm³/cm³]
  OSAT   - Saturated water content [0..1 cm³/cm³]
  ALFA   - van Genuchten shape parameter [0.0001..100 /cm]
  NPAR   - van Genuchten n parameter [1.001..9]
  KSATFIT - Fitted Ksat [1e-5..1e5 cm/d]
  LEXP   - Exponent in K function [-25..25]
  ALFAW  - Wetting curve alfa (hysteresis) [0.0001..100 /cm]
  H_ENPR - Air entry pressure head [-40..0 cm]
  KSATEXM - Measured Ksat [1e-5..1e5 cm/d]
  BDENS  - Dry bulk density [100..10000 mg/cm³ = kg/m³]

This tool uses the existing Carsel-Parrish texture-class lookup table,
not a fitted Rosetta model. Parameters are estimates, not measurements.

Soil comes from ONE source per run:
  * --hwsd: the dominant HWSD component at the point is read directly
    (read_hwsd_at_point; not ki_tools_common.lookup_hwsd). Any missing map
    unit, texture, bulk density or CRS stops the tool.
  * or manual texture: --texture / --sand --silt --clay (+ --subsoil-texture
    for more than one layer); bulk density is then a texture-class estimate.
Giving --hwsd together with any manual texture option is an error (since
2026-10-05): before, a failed HWSD read fell back to the manual texture
without a record in the summary, and a good HWSD read silently replaced it.

Usage:
    python convert_soil_to_swap.py \\
        --hwsd auto --hwsd-crs EPSG:4326 \\
        --lat 52.069 --lon 6.657 \\
        --output soil_params.txt
    (--hwsd auto = data/soil/HWSD_RASTER/hwsd.bil, which has no CRS metadata,
    so --hwsd-crs EPSG:4326 is required for it.)
"""

import argparse
import json
import sys
import os
from pathlib import Path

import numpy as np

from ki_tools_common.soil_utils import HWSD_RASTER, HWSD_CSV


# ---------------------------------------------------------------------------
# Texture-class lookup: USDA texture class → MvG parameters
# Carsel & Parrish (1988) class values (not a fitted Rosetta/Schaap model)
# ---------------------------------------------------------------------------
# Format: (ORES, OSAT, ALFA[1/cm], NPAR, KSAT[cm/d], LEXP)
TEXTURE_CLASS_MVG = {
    "sand":             (0.045, 0.430, 0.1450, 2.680, 712.8, 0.5),
    "loamy_sand":       (0.057, 0.410, 0.1240, 2.280, 350.2, 0.5),
    "sandy_loam":       (0.065, 0.410, 0.0750, 1.890, 106.1, 0.5),
    "loam":             (0.078, 0.430, 0.0360, 1.560, 24.96, 0.5),
    "silt":             (0.034, 0.460, 0.0160, 1.370, 6.00,  0.5),
    "silt_loam":        (0.067, 0.450, 0.0200, 1.410, 10.80, 0.5),
    "sandy_clay_loam":  (0.100, 0.390, 0.0590, 1.480, 31.44, 0.5),
    "clay_loam":        (0.095, 0.410, 0.0190, 1.310, 6.24,  0.5),
    "silty_clay_loam":  (0.089, 0.430, 0.0100, 1.230, 1.68,  0.5),
    "sandy_clay":       (0.100, 0.380, 0.0270, 1.230, 2.88,  0.5),
    "silty_clay":       (0.070, 0.360, 0.0050, 1.090, 0.48,  0.5),
    "clay":             (0.068, 0.380, 0.0080, 1.090, 4.80,  0.5),
}

# Typical bulk density by texture class (kg/m³ = mg/cm³)
TEXTURE_CLASS_BDENS = {
    "sand": 1550, "loamy_sand": 1500, "sandy_loam": 1450,
    "loam": 1400, "silt": 1350, "silt_loam": 1350,
    "sandy_clay_loam": 1500, "clay_loam": 1400,
    "silty_clay_loam": 1350, "sandy_clay": 1450,
    "silty_clay": 1300, "clay": 1250,
}


def validate_inputs(hwsd_path, lat, lon):
    """Pre-flight input validation."""
    errors = []
    if hwsd_path and not os.path.isfile(hwsd_path):
        errors.append(f"HWSD file not found: {hwsd_path}")
    if not (-90 <= lat <= 90):
        errors.append(f"Latitude {lat} out of range")
    if not (-180 <= lon <= 360):
        errors.append(f"Longitude {lon} out of range")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] Input validation passed: lat={lat}, lon={lon}")


def classify_texture(sand_pct, silt_pct, clay_pct):
    """
    Classify soil texture using USDA texture triangle.

    Parameters
    ----------
    sand_pct : float
        Sand content (0-100 %)
    silt_pct : float
        Silt content (0-100 %)
    clay_pct : float
        Clay content (0-100 %)

    Returns
    -------
    str : USDA texture class name (lowercase with underscores)
    """
    fractions = np.asarray([sand_pct,silt_pct,clay_pct],dtype=float)
    if not np.isfinite(fractions).all() or (fractions<0).any() or (fractions>100).any():
        raise ValueError('Texture fractions must be finite percentages in [0,100]')
    if abs(float(fractions.sum())-100) > .1:
        raise ValueError('Sand+silt+clay must sum to 100 percent (tolerance 0.1); no renormalization')
    s,si,c = fractions
    # USDA Soil Survey Manual 2017, chapter 3, textural-class definitions:
    # https://nrcspad.sc.egov.usda.gov/distributionCenter/pdf.aspx?productID=1363
    if si + 1.5*c < 15: return 'sand'
    if si + 2*c < 30: return 'loamy_sand'
    if (7 <= c < 20 and s > 52) or (c < 7 and si < 50): return 'sandy_loam'
    if 7 <= c < 27 and 28 <= si < 50 and s <= 52: return 'loam'
    if (si >= 50 and 12 <= c < 27) or (50 <= si < 80 and c < 12): return 'silt_loam'
    if si >= 80 and c < 12: return 'silt'
    if 20 <= c < 35 and si < 28 and s > 45: return 'sandy_clay_loam'
    if 27 <= c < 40 and 20 < s <= 45: return 'clay_loam'
    if 27 <= c < 40 and s <= 20: return 'silty_clay_loam'
    if c >= 35 and s > 45: return 'sandy_clay'
    if c >= 40 and si >= 40: return 'silty_clay'
    if c >= 40 and s <= 45 and si < 40: return 'clay'
    raise ValueError(f'Unclassified texture {fractions.tolist()}; supply a verified class explicitly')


def read_hwsd_at_point(hwsd_path, lat, lon, *, hwsd_csv=None, require_subsoil=True, hwsd_crs=None):
    """Read the dominant HWSD component directly, with no shared-loader defaults.

    Max SHARE, then minimum SEQ, then CSV row order breaks ties. Missing
    dominant-component properties are errors, not a reason to select minor soil.
    """
    import pandas as pd
    import rasterio
    from rasterio.warp import transform
    raster = hwsd_path or HWSD_RASTER
    csv = hwsd_csv or HWSD_CSV
    with rasterio.open(raster) as src:
        declared_crs = rasterio.crs.CRS.from_user_input(hwsd_crs) if hwsd_crs else None
        if src.crs is not None and declared_crs is not None and src.crs != declared_crs:
            raise ValueError('Explicit HWSD CRS conflicts with raster metadata')
        crs = src.crs or declared_crs
        if crs is None:
            raise ValueError('HWSD raster lacks CRS; supply a verified --hwsd-crs explicitly')
        xs,ys=transform('EPSG:4326',crs,[lon],[lat])
        row,col=src.index(xs[0],ys[0])
        if not (0 <= row < src.height and 0 <= col < src.width):
            raise ValueError('Point outside HWSD raster coverage')
        cell=src.read(1,window=rasterio.windows.Window(col,row,1,1),masked=True)[0,0]
        if np.ma.is_masked(cell) or not np.isfinite(cell) or cell<=0 or cell!=int(cell):
            raise ValueError('No valid HWSD map unit at point')
        mu_id=int(cell)
    df=pd.read_csv(csv,low_memory=False)
    rows=df[df['MU_GLOBAL']==mu_id]
    if rows.empty:raise ValueError(f'HWSD map unit {mu_id} absent from attribute table')
    shares=pd.to_numeric(rows['SHARE'],errors='coerce')
    if not np.isfinite(shares).all() or (shares<=0).any():
        raise ValueError(f'HWSD map unit {mu_id}: missing/invalid component shares')
    rows=rows.loc[shares==shares.max()]
    if len(rows)>1:
        seq=pd.to_numeric(rows['SEQ'],errors='coerce')
        if not np.isfinite(seq).all():raise ValueError('Ambiguous HWSD component order')
        rows=rows.loc[seq==seq.min()]
    raw=rows.iloc[0]
    def horizon(prefix):
        fractions=[float(raw.get(prefix+'_'+key,np.nan)) for key in ['SAND','SILT','CLAY']]
        texture=classify_texture(*fractions)
        density=float(raw.get(prefix+'_REF_BULK_DENSITY',np.nan))*1000
        if not np.isfinite(density) or not 100 <= density <= 10000:
            raise ValueError(f'HWSD {mu_id}: missing/invalid {prefix} bulk density')
        return fractions,texture,density
    top,top_class,bdens=horizon('T')
    sub,sub_class,sub_bdens=horizon('S') if require_subsoil else ([None]*3,None,None)
    return dict(mu_id=mu_id,texture=top_class,subsoil_texture=sub_class,
                sand=top[0],silt=top[1],clay=top[2],sub_sand=sub[0],sub_silt=sub[1],sub_clay=sub[2],
                bdens=bdens,subsoil_bdens=sub_bdens,
                source=dict(raster=str(raster),csv=str(csv),crs=str(crs),crs_explicit=bool(hwsd_crs),share_pct=float(raw['SHARE']),
                            seq=int(raw['SEQ']) if pd.notna(raw.get('SEQ')) else None,
                            selection='dominant component; max SHARE, min SEQ, CSV row order'))


def get_mvg_params(sand_pct=None, silt_pct=None, clay_pct=None,
                   texture_class=None, n_layers=2,
                   subsoil_texture_class=None, bdens_override=None,
                   subsoil_bdens_override=None):
    """
    Get Mualem-van Genuchten parameters for SWAP.

    Parameters
    ----------
    sand_pct, silt_pct, clay_pct : float, optional
        Texture percentages (0-100). If None, uses texture_class.
    texture_class : str, optional
        USDA texture class name. If None, classified from percentages.
    n_layers : int
        Number of soil layers (topsoil + subsoil)

    Returns
    -------
    list of dict : One dict per layer with all MvG parameters
    """
    fractions=[sand_pct,silt_pct,clay_pct]
    has_fractions=any(v is not None for v in fractions)
    if has_fractions:
        classified=classify_texture(*fractions)
        if texture_class is not None and texture_class!=classified:
            raise ValueError('Explicit texture disagrees with supplied fractions')
        texture_class=classified
    if texture_class not in TEXTURE_CLASS_MVG:
        raise ValueError('Supply a valid explicit texture or complete sand/silt/clay percentages')
    if not isinstance(n_layers,(int,np.integer)) or n_layers < 1:
        raise ValueError('n_layers must be a positive integer')
    if subsoil_texture_class is not None and subsoil_texture_class not in TEXTURE_CLASS_MVG:
        raise ValueError('Unknown subsoil texture class')
    if n_layers > 1 and subsoil_texture_class is None:
        raise ValueError('Supply subsoil_texture_class for a multilayer profile; no invented compaction')
    for density in [bdens_override,subsoil_bdens_override]:
        if density is not None and (not np.isfinite(density) or not 100 <= density <= 10000):
            raise ValueError('Bulk density must be finite and within [100,10000] mg/cm3')

    print(f"[INFO] Topsoil texture class: {texture_class}")
    if subsoil_texture_class:
        print(f"[INFO] Subsoil texture class: {subsoil_texture_class}")

    layers = []
    for i in range(n_layers):
        cls = texture_class if i == 0 else subsoil_texture_class
        ores, osat, alfa, npar, ksat, lexp = TEXTURE_CLASS_MVG[cls]
        supplied_density = bdens_override if i == 0 else subsoil_bdens_override
        bdens = supplied_density if supplied_density is not None else TEXTURE_CLASS_BDENS[cls]

        layer = {
            "layer": i + 1,
            "texture": cls,
            "ORES": round(ores, 3),
            "OSAT": round(osat, 3),
            "ALFA": round(alfa, 4),
            "NPAR": round(npar, 3),
            "KSATFIT": round(ksat, 2),
            "LEXP": round(lexp, 3),
            "ALFAW": round(alfa * 2.0, 4),
            "H_ENPR": 0.0,
            "KSATEXM": round(ksat, 2),
            "BDENS": round(bdens, 1),
        }
        print(f"[INFO] Layer {i + 1} ({cls}): ORES={layer['ORES']}, "
              f"OSAT={layer['OSAT']}, KSATFIT={layer['KSATFIT']} cm/d, "
              f"BDENS={layer['BDENS']} mg/cm3")
        layers.append(layer)

    return layers


def format_swap_table(layers):
    """Format MvG parameters as SWAP .swp input table string."""
    header = " ORES  OSAT    ALFA   NPAR  KSATFIT    LEXP   ALFAW  H_ENPR  KSATEXM   BDENS"
    lines = [header]
    for lay in layers:
        line = (
            f" {lay['ORES']:.3f}  {lay['OSAT']:.3f}  {lay['ALFA']:.4f}  "
            f"{lay['NPAR']:.3f}  {lay['KSATFIT']:8.2f}  {lay['LEXP']:6.3f}  "
            f"{lay['ALFAW']:.4f}  {lay['H_ENPR']:6.1f}  {lay['KSATEXM']:8.2f}  "
            f"{lay['BDENS']:.1f}"
        )
        lines.append(line)
    lines.append("* End of table")
    return "\n".join(lines)


def validate_outputs(layers):
    """Post-processing validation of MvG parameters."""
    errors = []
    if not layers:errors.append('No soil layers')
    for lay in layers:
        for key,value in lay.items():
            if key != 'texture' and not np.isfinite(value):
                errors.append(f'Layer {lay.get("layer")}: nonfinite {key}')
        i = lay["layer"]
        if lay["ORES"] >= lay["OSAT"]:
            errors.append(f"Layer {i}: ORES ({lay['ORES']}) >= OSAT ({lay['OSAT']})")
        if lay["NPAR"] <= 1.0:
            errors.append(f"Layer {i}: NPAR ({lay['NPAR']}) must be > 1.0")
        if lay["ALFA"] <= 0:
            errors.append(f"Layer {i}: ALFA ({lay['ALFA']}) must be > 0")
        if lay["KSATFIT"] <= 0:
            errors.append(f"Layer {i}: KSATFIT ({lay['KSATFIT']}) must be > 0")
        if not (100 <= lay["BDENS"] <= 10000):
            errors.append(f"Layer {i}: BDENS ({lay['BDENS']}) out of range [100, 10000]")

    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)

    if errors:
        print(f"[FAIL] Validation failed with {len(errors)} errors")
        return False
    print(f"[OK] All {len(layers)} soil layers pass validation")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Convert HWSD soil data to SWAP MvG parameters"
    )
    parser.add_argument("--hwsd", type=str, default="",
                        help="HWSD MU_GLOBAL raster path, or 'auto' for the shared hwsd.bil. "
                             "Cannot be combined with --texture/--sand/--silt/--clay/--subsoil-texture")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--sand", type=float, default=None,
                        help="Sand content (%%)")
    parser.add_argument("--silt", type=float, default=None,
                        help="Silt content (%%)")
    parser.add_argument("--clay", type=float, default=None,
                        help="Clay content (%%)")
    parser.add_argument("--texture", type=str, default=None,
                        help="USDA texture class (e.g., 'sandy_loam')")
    parser.add_argument("--n-layers", type=int, default=2,
                        help="Number of soil layers")
    parser.add_argument("--output", type=str, required=True,
                        help="Output file path (txt or json)")
    parser.add_argument("--hwsd-csv", default=None, help="HWSD attribute CSV (defaults to shared dataset path)")
    parser.add_argument("--hwsd-crs", default=None, help="Verified CRS for raster missing metadata; no implicit CRS assignment")
    parser.add_argument("--subsoil-texture", default=None, help="Explicit deeper-layer class")
    args = parser.parse_args()

    manual=[name for name,value in [('--texture',args.texture),('--sand',args.sand),('--silt',args.silt),
            ('--clay',args.clay),('--subsoil-texture',args.subsoil_texture)] if value is not None]
    if args.hwsd and manual:
        parser.error('--hwsd cannot be combined with manual texture ('+', '.join(manual)+'). '
                     'Use one soil source per run: HWSD alone, or manual texture alone.')

    # `--hwsd auto` lets the shared reader resolve its own raster path.
    hwsd_arg = "" if args.hwsd.lower() == "auto" else args.hwsd
    validate_inputs(hwsd_arg, args.lat, args.lon)

    texture = args.texture
    subsoil_texture = args.subsoil_texture
    bdens_override = None
    subsoil_bdens_override = None
    hwsd_result = None
    if args.hwsd:
        # Any HWSD failure raises (ValueError/OSError) and stops the tool in
        # the __main__ handler; there is no fallback texture.
        hwsd_result = read_hwsd_at_point(hwsd_arg, args.lat, args.lon, hwsd_csv=args.hwsd_csv, require_subsoil=args.n_layers>1, hwsd_crs=args.hwsd_crs)
        texture = hwsd_result["texture"]
        subsoil_texture = hwsd_result["subsoil_texture"]
        bdens_override = hwsd_result["bdens"]
        subsoil_bdens_override = hwsd_result["subsoil_bdens"]

    layers = get_mvg_params(
        sand_pct=args.sand, silt_pct=args.silt, clay_pct=args.clay,
        texture_class=texture, n_layers=args.n_layers,
        subsoil_texture_class=subsoil_texture,
        bdens_override=bdens_override, subsoil_bdens_override=subsoil_bdens_override,
    )

    if not validate_outputs(layers):
        raise ValueError("Soil parameter validation failed; no output written")

    # Write output only after validation.
    if args.output.endswith(".json"):
        with open(args.output, "w") as f:
            json.dump(layers, f, indent=2, allow_nan=False)
    else:
        table = format_swap_table(layers)
        with open(args.output, "w") as f:
            f.write(table + "\n")

    print(f"[OK] Wrote soil parameters to {args.output}")
    meta = dict(source=hwsd_result.get("source") if hwsd_result else "explicit texture input",
                mu_id=hwsd_result.get("mu_id") if hwsd_result else None,
                texture_class=texture, subsoil_texture_class=subsoil_texture,
                fractions=[args.sand,args.silt,args.clay],
                method="Carsel-Parrish class MvG lookup; no artificial subsoil multipliers",
                bulk_density="HWSD horizon values" if hwsd_result else "texture-class estimates",
                note="KSATEXM mirrors the class estimate for SWAP format compatibility; it is not measured Ksat. ALFAW=2*ALFA is the existing hysteresis parameterization.")
    Path(args.output+".summary.json").write_text(json.dumps(meta,indent=2,allow_nan=False)+"\n")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
