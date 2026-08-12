#!/usr/bin/env python3
"""
build_hrldas_setup.py -- stage s1 (domain / setup file) for a single-column
HRLDAS + Noah-MP run, including the managed-cropland extras (crop model and
irrigation) that the plain setup file does not carry.

Closes the s1 "(WPS/manual)" gap in SKILL.md: HRLDAS reads its static domain
from a WRF-style NetCDF ("wrfinput"), and for cropland it ALSO reads a SECOND,
separate agriculture file whose path is the namelist key AGDATA_FLNM.

Public API
----------
MODIS_IGBP                      FLUXNET BADM IGBP code -> MODIS-IGBP-MODIFIED
                                land-use index used by NoahmpTable.TBL
table_gvf(tbl_path, ivgtyp)     -> (SHDMAX %, SHDMIN %, annual-max LAI)
build_setup_file(...)           -> dict of what was written
build_agdata_file(...)          -> path
validate_setup_file(path)       -> list of problems (empty == OK)

Ground truth for every field/rank below is the HRLDAS reader itself:
  IO_code/module_hrldas_netcdf_io.F  read_crop_input / read_agriculture_data
  drivers/hrldas/NoahmpInitMainMod.F90        (CROPTYPE slot 5 >= 0.5 gate)
  drivers/hrldas/ConfigVarInTransferMod.F90   (CROPCAT -> CropType)
  src/GeneralInitMod.F90                      (FlagCropland on IVGTYP 12/14)

Traps this tool exists to prevent (KI diagnostics/triplets.yaml):
  dt_023  CROPTYPE must be rank 3 as (crop_cat, south_north, west_east) and
          PLANTING/HARVEST/SEASON_GDD rank 2 as (south_north, west_east) with
          NO leading Time dimension -- the reader calls nf90_get_var with a
          2-element start/count and silently falls back to table values
          otherwise.  IRFRACT/SIFRACT/MIFRACT/FIFRACT are NOT read from the
          setup file at all; they live in the separate AGDATA_FLNM file, and a
          blank AGDATA_FLNM leaves IRFRACT at 0.0 so irrigation can never fire
          (IrrigationPrepareMod needs IRFRACT >= IRR_FRAC, table default 0.10).
  dt_024  CROP_OPTION must be 1 for PLANTING/HARVEST to be read at all, and
          FlagCropland (hence BOTH the crop model and every irrigation method)
          is set only for MODIS-IGBP land use 12 or 14.
  dt_026  A cropped column must start BARE.  With CROP_OPTION=1 the driver
          turns the setup LAI into leaf biomass (LFMASSXY = LAI/0.015 for corn)
          and nothing resets it until the first HARVEST is crossed, so seeding
          a January cold start with the table's annual-maximum LAI grows a
          phantom winter canopy.
  dt_008  MMINLU in the setup file must match the NoahmpTable.TBL section.
"""
import os
import re

import numpy as np
import netCDF4 as nc

# FLUXNET BADM IGBP code -> MODIS-IGBP-MODIFIED-NOAH land-use index.
MODIS_IGBP = {"ENF": 1, "EBF": 2, "DNF": 3, "DBF": 4, "MF": 5, "CSH": 6,
              "OSH": 7, "WSA": 8, "SAV": 9, "GRA": 10, "WET": 11, "CRO": 12,
              "URB": 13, "CVM": 14, "SNO": 15, "BSV": 16, "WAT": 17}

# CROPTYPE slots 1-4 are class weights (largest wins); slot 5 is the
# "is this a crop cell" switch and must be >= 0.5 (NoahmpInitMainMod.F90:219).
CROP_SLOT = {"corn": 1, "maize": 1, "soybean": 2, "soy": 2}

# Noah-MP crop categories that FlagCropland allows (GeneralInitMod.F90).
CROPLAND_IVGTYP = (12, 14)

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def table_gvf(tbl_path, ivgtyp):
    """Annual max/min green vegetation fraction consistent with the table LAI.

    DVEG=4 sets VegFrac = VegFracAnnMax = SHDMAX/100 (PhenologyMainMod.F90) and
    takes LAI from the MODIS monthly climatology in NoahmpTable.TBL.  Deriving
    SHDMAX/SHDMIN from that SAME table via Noah-MP's own FVEG closure,
    1 - exp(-0.52*(LAI+SAI)), keeps the canopy fraction and the canopy LAI
    self-consistent instead of pasting in an unrelated default.

    Returns (shdmax_percent, shdmin_percent, lai_annual_max).
    """
    txt = open(tbl_path).read()

    def row(prefix, mon):
        # The MODIS section is the LAST occurrence of the LAI_/SAI_ blocks.
        hits = re.findall(rf"^\s*{prefix}_{mon}\s*=\s*(.+)$", txt, re.M)
        if not hits:
            raise RuntimeError(f"{prefix}_{mon} not found in {tbl_path}")
        vals = [float(x) for x in hits[-1].replace(",", " ").split()]
        return vals[ivgtyp - 1]

    lai = np.array([row("LAI", m) for m in _MONTHS])
    sai = np.array([row("SAI", m) for m in _MONTHS])
    lai = np.where(lai < 0.05, 0.0, lai)
    sai = np.where(sai < 0.05, 0.0, sai)
    fveg = 1.0 - np.exp(-0.52 * (lai + sai))
    return float(fveg.max() * 100.0), float(fveg.min() * 100.0), float(lai.max())


def build_setup_file(path, lat, lon, hgt, ivgtyp, isltyp, tmn, smc0,
                     shdmax, shdmin, lai0,
                     croptype=None, planting=None, harvest=None,
                     season_gdd=None, title=None):
    """Write the single-column HRLDAS setup ("wrfinput") NetCDF.

    Fields follow the shipped single-point example create_point_data.f90.
    Passing `croptype` additionally writes the CROP_OPTION=1 inputs.

    croptype : "corn"/"maize"/"soybean" or an int 1-4, or None for a natural
               column (no CROPTYPE/PLANTING/HARVEST written at all).
    planting/harvest : day of year, from
               ki_tools_common.crop_calendar.get_planting_harvest -- NOT the
               NoahmpTable PLTDAY/HSDAY defaults (dt_024).
    """
    if croptype is not None and int(ivgtyp) not in CROPLAND_IVGTYP:
        raise ValueError(
            f"croptype={croptype!r} requested but IVGTYP={ivgtyp} is not a "
            f"MODIS-IGBP cropland class {CROPLAND_IVGTYP}; FlagCropland would "
            f"stay false and neither the crop model nor irrigation could ever "
            f"run (GeneralInitMod.F90, dt_024)")
    if croptype is not None and (planting is None or harvest is None):
        raise ValueError("croptype set but planting/harvest day-of-year missing "
                         "-- IRRIGATION_OPTION=2 would silently use the "
                         "NoahmpTable PLTDAY/HSDAY defaults (dt_024)")

    slot = None
    if croptype is not None:
        slot = CROP_SLOT.get(str(croptype).lower()) if not isinstance(croptype, int) \
            else int(croptype)
        if slot is None or not (1 <= slot <= 4):
            raise ValueError(f"unsupported croptype {croptype!r}; expected one of "
                             f"{sorted(CROP_SLOT)} or an int 1-4")

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with nc.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("Time", 1)
        ds.createDimension("soil_layers_stag", 4)
        ds.createDimension("south_north", 1)
        ds.createDimension("west_east", 1)

        def v2(n, val, dt="f4"):
            ds.createVariable(n, dt, ("Time", "south_north", "west_east"))[0, 0, 0] = val

        def vs(n, arr):
            ds.createVariable(n, "f4",
                              ("Time", "soil_layers_stag", "south_north",
                               "west_east"))[0, :, 0, 0] = arr

        v2("XLAT", lat); v2("XLONG", lon); v2("HGT", hgt); v2("TMN", tmn)
        v2("IVGTYP", int(ivgtyp), "i4"); v2("ISLTYP", int(isltyp), "i4")
        # VEGFRA / SHDMAX / SHDMIN are PERCENT, not fractions.
        v2("VEGFRA", shdmax); v2("LAI", lai0)
        v2("SHDMIN", shdmin); v2("SHDMAX", shdmax)
        v2("CANWAT", 0.0); v2("TSK", tmn); v2("SNOW", 0.0); v2("SNODEP", 0.0)
        v2("XLAND", 1.0); v2("SEAICE", 0.0)
        vs("TSLB", [tmn] * 4); vs("SMOIS", [smc0] * 4); vs("SH2O", [smc0] * 4)

        if croptype is not None:
            # read_crop_input: CROPTYPE is Fortran (x, 5, y) read via a
            # 3-element start/count -> NetCDF (crop_cat, south_north,
            # west_east); PLANTING/HARVEST/SEASON_GDD are Fortran (x, y) read
            # via a 2-element start/count -> NetCDF (south_north, west_east)
            # with NO Time dimension (dt_023).
            ds.createDimension("crop_cat", 5)
            ct = ds.createVariable("CROPTYPE", "f4",
                                   ("crop_cat", "south_north", "west_east"))
            w = np.zeros(5, dtype="f4")
            w[slot - 1] = 1.0     # slots 1-4: class weights, largest wins
            w[4] = 1.0            # slot 5: crop-cell switch, must be >= 0.5
            ct[:, 0, 0] = w
            ds.createVariable("PLANTING", "f4",
                              ("south_north", "west_east"))[0, 0] = float(planting)
            ds.createVariable("HARVEST", "f4",
                              ("south_north", "west_east"))[0, 0] = float(harvest)
            # SEASON_GDD is read but not consumed downstream in v5.x; write the
            # table GDDS5 (seeding -> physiological maturity) for the category
            # so the field is at least self-consistent.
            gdd = season_gdd if season_gdd is not None else (1555.0 if slot == 1 else 1605.0)
            ds.createVariable("SEASON_GDD", "f4",
                              ("south_north", "west_east"))[0, 0] = float(gdd)

        ds.DX = 1000.0; ds.DY = 1000.0
        ds.TRUELAT1 = 30.0; ds.TRUELAT2 = 60.0
        ds.STAND_LON = float(lon); ds.MAP_PROJ = 6; ds.GRID_ID = 1
        ds.ISWATER = 17; ds.ISURBAN = 13; ds.ISICE = 15; ds.ISLAKE = 21
        # Must match the NoahmpTable.TBL section the LAI/SAI came from (dt_008).
        ds.MMINLU = "MODIFIED_IGBP_MODIS_NOAH"
        ds.TITLE = title or "HYDROCRAFT NOAHMP SETUP"

    info = {"path": path, "ivgtyp": int(ivgtyp), "isltyp": int(isltyp),
            "vegfra_pct": float(shdmax), "shdmin_pct": float(shdmin),
            "lai_init": float(lai0), "tmn_K": float(tmn),
            "smc_init": float(smc0), "crop": None}
    if croptype is not None:
        info["crop"] = {"croptype": croptype, "slot": slot,
                        "planting_doy": int(planting),
                        "harvest_doy": int(harvest)}
    return info


def build_agdata_file(path, irfract=1.0, sifract=1.0, mifract=0.0, fifract=0.0):
    """Write the SEPARATE agriculture file addressed by namelist AGDATA_FLNM.

    read_agriculture_data reads all four as Fortran (x, y) via a 2-element
    start/count -> NetCDF (south_north, west_east), no Time dimension (dt_023).
    IRFRACT must be >= IRR_FRAC (NoahmpTable default 0.10) or the trigger in
    IrrigationPrepareMod never fires.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with nc.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("south_north", 1)
        ds.createDimension("west_east", 1)
        for name, val in (("IRFRACT", irfract), ("SIFRACT", sifract),
                          ("MIFRACT", mifract), ("FIFRACT", fifract)):
            ds.createVariable(name, "f4", ("south_north", "west_east"))[0, 0] = float(val)
        ds.TITLE = "HYDROCRAFT NOAHMP AGDATA (irrigation fractions)"
    return path


def validate_setup_file(path):
    """Re-open the written file and return a list of problems (empty == OK).

    Catches exactly the silent traps: wrong rank/dimension order on the crop
    fields, VEGFRA written as a fraction instead of a percent, and a CROPTYPE
    slot 5 below the 0.5 activation threshold.
    """
    problems = []
    if not os.path.exists(path):
        return [f"setup file {path} does not exist"]
    with nc.Dataset(path) as ds:
        for req in ("XLAT", "XLONG", "HGT", "TMN", "IVGTYP", "ISLTYP",
                    "VEGFRA", "LAI", "SHDMAX", "SHDMIN", "TSLB", "SMOIS", "SH2O"):
            if req not in ds.variables:
                problems.append(f"missing required variable {req}")
        for req in ("XLAT", "IVGTYP", "VEGFRA"):
            if req in ds.variables and ds[req].dimensions != (
                    "Time", "south_north", "west_east"):
                problems.append(f"{req} dims {ds[req].dimensions} != "
                                f"('Time','south_north','west_east')")

        if "VEGFRA" in ds.variables:
            vf = float(ds["VEGFRA"][:].ravel()[0])
            if vf <= 1.5:
                problems.append(f"VEGFRA={vf:.3g} looks like a FRACTION; "
                                f"HRLDAS expects PERCENT (0-100)")
            elif vf > 100.0:
                problems.append(f"VEGFRA={vf:.3g} exceeds 100 percent")
        for nm in ("SHDMAX", "SHDMIN"):
            if nm in ds.variables:
                v = float(ds[nm][:].ravel()[0])
                if not (0.0 <= v <= 100.0):
                    problems.append(f"{nm}={v:.3g} outside 0-100 percent")

        if "IVGTYP" in ds.variables:
            ivg = int(ds["IVGTYP"][:].ravel()[0])
            if not (1 <= ivg <= 20):
                problems.append(f"IVGTYP={ivg} outside the MODIS-IGBP range")
        if getattr(ds, "MMINLU", "") != "MODIFIED_IGBP_MODIS_NOAH":
            problems.append(f"MMINLU={getattr(ds, 'MMINLU', None)!r} does not "
                            f"match the NoahmpTable MODIS section (dt_008)")

        if "CROPTYPE" in ds.variables:
            if ds["CROPTYPE"].dimensions != ("crop_cat", "south_north", "west_east"):
                problems.append(
                    f"CROPTYPE dims {ds['CROPTYPE'].dimensions} != "
                    f"('crop_cat','south_north','west_east') -- read_crop_input "
                    f"would read garbage or fall back to table values (dt_023)")
            ct = np.asarray(ds["CROPTYPE"][:]).ravel()
            if ct.size != 5:
                problems.append(f"CROPTYPE has {ct.size} values, expected 5")
            elif ct[4] < 0.5:
                problems.append(
                    f"CROPTYPE slot 5 = {ct[4]:.3g} < 0.5 -- the crop category "
                    f"is never activated (NoahmpInitMainMod.F90:219)")
            for nm in ("PLANTING", "HARVEST"):
                if nm not in ds.variables:
                    problems.append(f"CROPTYPE present but {nm} missing; "
                                    f"the table PLTDAY/HSDAY would be used (dt_024)")
                elif ds[nm].dimensions != ("south_north", "west_east"):
                    problems.append(f"{nm} dims {ds[nm].dimensions} != "
                                    f"('south_north','west_east') (dt_023)")
                else:
                    d = float(ds[nm][:].ravel()[0])
                    if not (1.0 <= d <= 366.0):
                        problems.append(f"{nm}={d:.4g} is not a day of year")
            if "LAI" in ds.variables:
                lai = float(ds["LAI"][:].ravel()[0])
                if lai > 0.5:
                    problems.append(
                        f"LAI={lai:.3g} on a CROP run: the driver converts the "
                        f"setup LAI into leaf biomass and does not reset it "
                        f"before the first harvest -> phantom pre-planting "
                        f"canopy; start bare at 0.05 (dt_026)")
    return problems


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", required=True, help="setup NetCDF to write")
    ap.add_argument("--table", required=True, help="NoahmpTable.TBL")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--elev", type=float, required=True)
    ap.add_argument("--igbp", required=True, choices=sorted(MODIS_IGBP))
    ap.add_argument("--isltyp", type=int, required=True)
    ap.add_argument("--tmn", type=float, required=True, help="deep soil temperature [K]")
    ap.add_argument("--smc0", type=float, default=0.30)
    ap.add_argument("--croptype", default=None)
    ap.add_argument("--planting", type=int, default=None)
    ap.add_argument("--harvest", type=int, default=None)
    ap.add_argument("--agdata", default=None, help="also write this AGDATA_FLNM file")
    ap.add_argument("--irfract", type=float, default=1.0)
    ap.add_argument("--sifract", type=float, default=1.0)
    a = ap.parse_args()

    ivgtyp = MODIS_IGBP[a.igbp]
    shdmax, shdmin, laimax = table_gvf(a.table, ivgtyp)
    lai0 = 0.05 if a.croptype else laimax
    info = build_setup_file(a.output, a.lat, a.lon, a.elev, ivgtyp, a.isltyp,
                            a.tmn, a.smc0, shdmax, shdmin, lai0,
                            croptype=a.croptype, planting=a.planting,
                            harvest=a.harvest)
    problems = validate_setup_file(a.output)
    if a.agdata:
        build_agdata_file(a.agdata, irfract=a.irfract, sifract=a.sifract)
        info["agdata"] = a.agdata
    info["validation_problems"] = problems
    print(json.dumps(info, indent=2))
    raise SystemExit(1 if problems else 0)
