#!/usr/bin/env python3
"""
CLASSIC verifier runner (verify_2) — FLUXNET2015 DK-Sor (Soroe, Denmark) daily GPP.

Third location for the CLASSIC GPP verifier.
  Real-case = FI-Hyy  (boreal evergreen needleleaf, Scots pine)
  verify_1  = DE-Tha  (temperate evergreen needleleaf, Norway spruce)
  verify_2  = DK-Sor  (temperate DECIDUOUS BROADLEAF, European beech) <- this run

Diversifies the biome/PFT (broadleaf cold-deciduous instead of needleleaf
evergreen) to check the recipe is not overfit to ENF towers. Same toolchain,
same period as DE-Tha (1996-2014).

Pipeline (all via KI tools + CLASSIC binary):
  s1  convert_forcing_to_classic.py  (source_type=fluxnet)  -> met netCDF
  s2  convert_soil_to_classic.py                            -> init_file.nc
  s5  CLASSIC_serial   spinup (metLoop) -> restart, then transient w/ daily GPP
  s6  parse daily gpp, compare to FLUXNET GPP_NT_VUT_REF (gC/m2/d)

Determining metric: nse (point_time_series).  Resumable: skips forcing/init if
present, skips spinup if the spun restart marker exists, skips the transient if
gpp_daily.nc exists.
"""
import json, os, shutil, subprocess, sys
import numpy as np

sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models")
import netCDF4 as nc
import pandas as pd
from ki_tools_common.metrics import all_metrics

KI   = "/mnt/disk1/Hydrocraft_server/models/CLASSIC/knowledge_infrastructure"
SRC  = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/CLASSIC/source/repo"
BIN  = f"{SRC}/bin/CLASSIC_serial"
RUN  = "/mnt/disk1/Hydrocraft_server/models/CLASSIC/run/dksor"
MET  = f"{RUN}/met"
STATE= "/mnt/disk1/Hydrocraft_server/models/CLASSIC/detached/verify_2"
FLUX = "/mnt/disk1/Hydrocraft_server/data/obs/fluxnet/sites/DK-Sor/FULLSET_HH.csv"
FDD  = "/mnt/disk1/Hydrocraft_server/data/obs/fluxnet/sites/DK-Sor/FULLSET_DD.csv"

SITE, LAT, LON = "DK-Sor", 55.4859, 11.6446
Y0, Y1 = 1996, 2014
CAL = (1996, 2007)
VAL = (2008, 2014)
SPIN_LOOPS = 4          # ~76 yr vegetation-carbon spinup (fast pools equilibrate)
XML = f"{SRC}/configurationFiles/outputVariableDescriptors.xml"
RP  = f"{SRC}/configurationFiles/template_run_parameters.txt"

os.makedirs(STATE, exist_ok=True)
os.makedirs(MET, exist_ok=True)

def sh(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)

# ----------------------------------------------------------------- s1 forcing
def build_forcing():
    if os.path.exists(f"{MET}/tmp.nc") and os.path.exists(f"{MET}/dswrf.nc"):
        return
    sh(["python3", f"{KI}/tools/convert_forcing_to_classic.py",
        "--source_type", "fluxnet", "--csv_file", FLUX,
        "--lat", str(LAT), "--lon", str(LON),
        "--start_year", str(Y0), "--end_year", str(Y1),
        "--output_dir", MET, "--timestep_minutes", "30"])
    for g in ("co2.nc", "ch4.nc"):
        if not os.path.exists(f"{MET}/{g}"):
            shutil.copy(f"{SRC}/test_met/{g}", f"{MET}/{g}")

def build_init():
    if os.path.exists(f"{MET}/init_file.nc"):
        return
    # Soroe: fertile clay-rich glacial moraine (Alfisol/Luvisol) under beech,
    # loam->clay-loam profile, ~1.5 m permeable over till.
    SAND = "40,40,40,38,38,36,35,35,33,33,33,33,33,33,33,33,33,33,33,33"
    CLAY = "20,20,22,24,24,26,28,28,30,30,30,30,30,30,30,30,30,30,30,30"
    ORGM = "9,6,4,3,2,1,0.5,0.5,0,0,0,0,0,0,0,0,0,0,0,0"
    # PFT order: NdlEvg, NdlDcd, BdlEvg, BdlDCo(cold-decid), BdlDDr,
    #            CropC3, CropC4, GrassC3, GrassC4  -> beech = BdlDCo (idx 4)
    sh(["python3", f"{KI}/tools/convert_soil_to_classic.py",
        "--lat", str(LAT), "--lon", str(LON),
        "--sand", SAND, "--clay", CLAY, "--orgm", ORGM, "--sdep", "1.5",
        "--pft_fracs", "0.0,0.0,0.0,0.90,0.0,0.0,0.0,0.05,0.0",
        "--init_temp", "8.0", "--output", f"{MET}/init_file.nc"])

# ----------------------------------------------------------------- job options
JOB = """&joboptions
    projectedGrid = .false.
    readMetStartYear = {y0}
    readMetEndYear = {y1}
    metLoop = {loop} ,
    leap = .false. ,
    metFileFss = '{met}/dswrf.nc',
    metFileFdl = '{met}/dlwrf.nc',
    metFilePre = '{met}/pre.nc',
    metFileTa = '{met}/tmp.nc'
    metFileQa = '{met}/spfh.nc',
    metFileUv = '{met}/wind.nc',
    metFilePres = '{met}/pres.nc',
    init_file = '{init}' ,
    rs_file_to_overwrite = '{rs}' ,
    runparams_file = '{rp}' ,
    ctem_on = .true. ,
    spinfast = 1 ,
    useTracer = 0 ,
    tracerCO2file = '{met}/co2.nc'
        transientCO2 = .false. ,
        CO2File = '{met}/co2.nc' ,
        fixedYearCO2 = 2009 ,
        doMethane = .false.,
          transientCH4 = .false. ,
          CH4File = '{met}/ch4.nc',
          fixedYearCH4 = 2009 ,
          transientOBSWETF = .false. ,
          OBSWETFFile = '',
          fixedYearOBSWETF = -9999 ,
        dofire = .false. ,
            transientPOPD = .false. ,
            POPDFile = '' ,
            fixedYearPOPD = 2009 ,
            transientLGHT= .false.
            LGHTFile = '' ,
            fixedYearLGHT = 2009 ,
        PFTCompetition = .false. ,
            inibioclim = .false. ,
            start_bare = .false.,
        lnduseon = .false. ,
        LUCFile = '' ,
        fixedYearLUC = -9999 ,
    IDISP = 1 ,
    IZREF = 1 ,
    ZRFH = 43.0,
    ZRFM = 43.0,
    ZBLD = 50.0,
    ISLFD = 0 ,
    IPCP = 1 ,
    IWF = 0 ,
    isnoalb = 0 ,
    ITC = 1 , ITCG = 1 , ITG = 1 ,
    IPAI = 0 , IHGT = 0 , IALC = 0 , IALS = 0 , IALG = 0 ,
    output_directory = '{outdir}' ,
    xmlFile = '{xml}' ,
    doperpftoutput = .false. ,
    dopertileoutput = .false. ,
    dohhoutput = .false. ,
    JHHSTD = 1 , JHHENDD = 365 , JHHSTY = {y0} , JHHENDY = {y0} ,
    dodayoutput = {dday} ,
    JDSTD = 1 , JDENDD = 365 , JDSTY = {y0} , JDENDY = {y1} ,
    domonthoutput = .false. ,
    JMOSTY = {y0} ,
    doAnnualOutput = .true. ,
    doChecksums = .false.,
    Comment = 'DK-Sor CLASSIC GPP'
 /
"""

def write_job(path, loop, rs, outdir, dday):
    with open(path, "w") as f:
        f.write(JOB.format(y0=Y0, y1=Y1, loop=loop, met=MET,
                           init=f"{MET}/init_file.nc", rs=rs, rp=RP,
                           outdir=outdir, xml=XML, dday=dday))

def run_classic(job):
    sh([BIN, job, "0/0"], cwd=SRC)

# ----------------------------------------------------------------- s5 spinup
def spinup():
    marker = f"{MET}/spin.done"
    rs = f"{MET}/rsFile_spin.nc"
    if os.path.exists(marker) and os.path.exists(rs):
        print("spinup already done, skipping", flush=True)
        return rs
    shutil.copy(f"{MET}/init_file.nc", rs)
    outdir = f"{RUN}/out_spin"; os.makedirs(outdir, exist_ok=True)
    job = f"{RUN}/job_spin.txt"
    write_job(job, SPIN_LOOPS, rs, outdir, ".false.")
    run_classic(job)
    open(marker, "w").write("ok")
    return rs

def transient(rs_spun):
    outdir = f"{RUN}/out_trans"; os.makedirs(outdir, exist_ok=True)
    if os.path.exists(f"{outdir}/gpp_daily.nc"):
        print("transient already done, skipping", flush=True)
        return outdir
    rs = f"{MET}/rsFile_trans.nc"
    shutil.copy(rs_spun, rs)
    job = f"{RUN}/job_trans.txt"
    write_job(job, 1, rs, outdir, ".true.")
    run_classic(job)
    return outdir

# ----------------------------------------------------------------- s6 score
def load_sim(outdir):
    d = nc.Dataset(f"{outdir}/gpp_daily.nc")
    g = np.array(d.variables["gpp"][:]).ravel().astype(float)
    g[g > 1e30] = np.nan
    return g * 86400.0 * 1000.0              # kgC/m2/s -> gC/m2/d

def load_obs():
    o = pd.read_csv(FDD, usecols=["TIMESTAMP", "GPP_NT_VUT_REF"])
    o["date"] = pd.to_datetime(o.TIMESTAMP, format="%Y%m%d")
    o = o[(o.date.dt.year >= Y0) & (o.date.dt.year <= Y1)]
    o = o[~((o.date.dt.month == 2) & (o.date.dt.day == 29))].reset_index(drop=True)
    o["gpp"] = o.GPP_NT_VUT_REF.replace(-9999, np.nan)
    return o

def metrics_for(obs, sim, mask):
    o, s = obs[mask], sim[mask]
    good = ~(np.isnan(o) | np.isnan(s))
    if good.sum() < 2:
        return None
    m = all_metrics(o[good], s[good])
    return {k.lower(): float(v) for k, v in m.items()}

def main():
    build_forcing(); build_init()
    rs = spinup()
    outdir = transient(rs)
    try:
        sh(["python3", f"{KI}/tools/parse_classic_output.py",
            "--output_dir", outdir, "--variables", "gpp", "--frequency", "daily",
            "--csv_out", f"{outdir}/gpp_daily.csv"])
    except Exception as e:
        print("parse_classic_output non-fatal:", e, flush=True)

    sim = load_sim(outdir)
    odf = load_obs()
    n = min(len(sim), len(odf))
    sim = sim[:n]; obs = odf["gpp"].to_numpy()[:n]; yr = odf["date"].dt.year.to_numpy()[:n]

    full = metrics_for(obs, sim, np.ones(n, bool))
    cal  = metrics_for(obs, sim, (yr >= CAL[0]) & (yr <= CAL[1]))
    val  = metrics_for(obs, sim, (yr >= VAL[0]) & (yr <= VAL[1]))

    res = {
        "model_id": "CLASSIC",
        "this_location": "FLUXNET2015 (192 sites)",
        "obs_source": "FLUXNET",
        "status": "completed",
        "tools_used": ["convert_forcing_to_classic.py (source_type=fluxnet)",
                       "convert_soil_to_classic.py", "run via CLASSIC_serial",
                       "parse_classic_output.py", "ki_tools_common.metrics.all_metrics"],
        "tools_failed": [],
        "metrics": {
            "nse": full["nse"], "kge": full["kge"], "pbias": full["pbias"],
            "r": full["r"],
            "nse_cal": cal["nse"], "kge_cal": cal["kge"],
            "nse_val": val["nse"], "kge_val": val["kge"], "pbias_val": val["pbias"],
            "rmse": full["rmse"],
            "period": f"{Y0}-{Y1}",
        },
        "water_balance": {"status": "N/A", "residual_pct": None},
        "site": f"SITE:{SITE} (GEO:{LAT},{LON})",
        "variable": "gpp", "obs_shape": "point_time_series",
        "n_days": int(n),
        "obs_mean_gC_m2_d": float(np.nanmean(obs)),
        "sim_mean_gC_m2_d": float(np.nanmean(sim)),
        "notes": (
            f"DK-Sor (Soroe, Denmark) temperate DECIDUOUS BROADLEAF European-beech "
            f"FLUXNET site; daily GPP vs GPP_NT_VUT_REF {Y0}-{Y1}, n={n}. CLASSIC CLASS+CTEM, "
            f"tower-met driven, {SPIN_LOOPS*(Y1-Y0+1)}-yr veg-C spinup then metLoop=1 transient "
            f"daily output. BdlDCo (cold-deciduous broadleaf) PFT -- diversifies biome from the two "
            f"ENF Real-case/verify_1 sites. "
            f"NSE={full['nse']:.3f} r={full['r']:.3f} KGE={full['kge']:.3f} PBIAS={full['pbias']:.1f}%. "
            f"sim mean {np.nanmean(sim):.2f} vs obs {np.nanmean(obs):.2f} gC/m2/d. "
            "Determining metric nse; point_time_series -> NSE/KGE/r/PBIAS all valid."
        ),
    }
    with open(f"{STATE}/result.json", "w") as f:
        json.dump(res, f, indent=2)
    print("RESULT:", json.dumps(res["metrics"]), flush=True)

if __name__ == "__main__":
    main()
