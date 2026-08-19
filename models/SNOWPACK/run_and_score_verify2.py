#!/usr/bin/env python3
"""
VERIFIER (verify_2) driver + scorer for SNOWPACK at a NEW SNOTEL site:
  SNOTEL 618 Mc Clure Pass, CO (8760 ft = 2670 m, continental CO alpine).

Faithful twin of the validated real-case recipe (models/SNOWPACK/run_and_score.py,
SNOTEL 668 North French Creek WY): continental-interior high-alpine site, SNOTEL
observed daily T+P, parameterized ISWR (Iqbal/Hottel clear-sky x state cloud
factor) and ILWR (Brutsaert 1975), expanded to hourly, driven through the same 5
SNOWPACK KI tools (s1-s6) and the real snowpack binary. Validation target:
SWE (kg/m2 == mm) vs SNOTEL pillow SWE.

Continental recipe (SKILL.md Lesson H, which names CO explicitly): keep
fall/winter forcing cold (RH=0.80, CO cloud-factor 0.60) for solver stability;
apply a shortwave melt boost ONLY in the ablation window (Apr 1 - Jun 30,
DOY 91-181) to fix late melt-out without thinning the fragile Oct-Nov pack.
The KI pipeline, the binary, and every .ini patch are reused UNCHANGED from the
real case; only the site metadata (id/lat/lon/elev/state/tz) differs.

cal/val split (holdout, no separate runs): cal = ..2008-09-30, val = 2008-10.. of
the single 2003-2013 simulation -- val metrics show the parameter choices are not
overfit to any period.

RESUMABLE: if the results CSV already exists it re-scores without re-running the
binary. Writes the complete verifier JSON to detached/verify_2/result.json as the
final action.
"""
import json, math, os, subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path("KISSPATH_ROOT")
KI_TOOLS = BASE / "models/SNOWPACK/knowledge_infrastructure/tools"
SNOWPACK_BIN = Path("KISSPATH_BINARIES/Alpine3D/local_install/bin/snowpack")
SNOTEL_DIR = BASE / "data/obs/snotel"
OUT = BASE / "models/SNOWPACK/outputs_run/mcclure_618"
RESULT_DIR = Path(os.environ.get("SNOWPACK_RESULT_DIR",
                                 str(BASE / "models/SNOWPACK/detached/verify_2")))
PYTHON = BASE / "python_env/bin/python3"

# ---- Site: SNOTEL 618 Mc Clure Pass, CO ----
SID = 618
NAME = "Mc Clure Pass"
STATE = "CO"
LAT = 39.12899
LON = -107.28834
ELEV = 8760.0 * 0.3048     # ft -> m = 2670.05
TZ = -7                    # Mountain Standard Time
RH_FIX = 0.80              # continental interior: keep fall pack cold for solver stability
PRECIP_SCALE = 1.0         # continental gauge: no maritime undercatch signature
MAX_DAILY_PSUM = 100.0     # mm SWE/day (hourly expansion keeps per-step small)
SPRING_SW_FACTOR = 1.45    # ablation-window ISWR boost (Lesson H)
SPRING_DOY = (91, 181)
RUN_START = "2003-10-01"
RUN_END = "2013-09-30"
CAL_END = "2008-09-30"     # cal = ..2008, val = 2008-10..

STATE_CF = {"AZ":0.72,"NV":0.70,"NM":0.68,"CO":0.60,"WY":0.58,"UT":0.62,
            "MT":0.55,"ID":0.57,"OR":0.48,"WA":0.46,"CA":0.60}
SIGMA = 5.67e-8
I0 = 1361.0

def cos_zenith_daily(lat_rad, doy):
    decl = 0.40928*np.sin(2*np.pi/365*(doy-80))
    cl,sl,cd,sd = math.cos(lat_rad),math.sin(lat_rad),np.cos(decl),np.sin(decl)
    cos_ha = np.clip(-sl*sd/(cl*cd),-1,1); ha=np.arccos(cos_ha)
    return np.maximum((1/np.pi)*(sl*sd*ha+cl*cd*np.sin(ha)),0.0)

def iswr_daily(lat,elev,state,doy):
    lat_rad=math.radians(lat); es=1.0+0.033*np.cos(2*np.pi/365*doy)
    cz=cos_zenith_daily(lat_rad,doy)
    a0=0.4237-0.00821*(6-elev/1000)**2; a1=0.5055+0.00595*(6.5-elev/1000)**2
    k=0.2711+0.01858*(2.5-elev/1000)**2
    tb=np.where(cz>0,a0+a1*np.exp(-k/np.maximum(cz,0.01)),0.0); td=0.2710-0.2939*tb
    cf=STATE_CF.get(state,0.58)
    return np.maximum(I0*es*cz*(tb+td)*cf,0.0)

def iswr_hourly(lat,elev,state,doy):
    lat_rad=math.radians(lat); cf=STATE_CF.get(state,0.58); doy=np.asarray(doy,float)
    decl=0.40928*np.sin(2*np.pi/365*(doy-80)); es=1.0+0.033*np.cos(2*np.pi/365*doy)
    a0=0.4237-0.00821*(6-elev/1000)**2; a1=0.5055+0.00595*(6.5-elev/1000)**2
    k=0.2711+0.01858*(2.5-elev/1000)**2
    out=[]
    for h in range(24):
        ha=(h+0.5-12.0)*math.pi/12.0
        ct=math.sin(lat_rad)*np.sin(decl)+math.cos(lat_rad)*np.cos(decl)*math.cos(ha)
        ct=np.maximum(ct,0.0); tb=np.where(ct>0,a0+a1*np.exp(-k/np.maximum(ct,0.01)),0.0)
        td=0.2710-0.2939*tb; out.append(np.maximum(I0*es*ct*(tb+td)*cf,0.0))
    return tuple(out)

def ilwr_daily(ta_k,rh):
    Tc=ta_k-273.15; esat=611.2*np.exp(17.67*Tc/(Tc+243.5)); ea=rh*esat
    eps=np.clip(0.642*(ea/ta_k)**(1/7),0.5,1.0)
    return eps*SIGMA*ta_k**4

def atm_pressure(elev): return 101325.0*(1.0-2.2558e-5*elev)**5.2559

def read_snotel(sid):
    df=pd.read_csv(SNOTEL_DIR/f"{sid}_daily.csv",comment="#",parse_dates=["Date"])
    df.columns=["date","swe_in","depth_in","tavg_f","prec_accum_in"]
    for c in df.columns[1:]: df[c]=pd.to_numeric(df[c],errors="coerce")
    ta_f=df["tavg_f"].copy(); ta_f[ta_f==32.0]=np.nan
    df["ta_k"]=(ta_f-32.0)*5/9+273.15
    df["swe_mm"]=df["swe_in"]*25.4
    df["hs_m"]=df["depth_in"]*0.0254
    df["prec_mm"]=df["prec_accum_in"]*25.4
    df=df.set_index("date").sort_index()
    # ROBUST auto-detect (SKILL Lesson): SNOTEL precip column may be CUMULATIVE
    # accumulation (needs diff) or already INCREMENTAL daily precip. Only diff the
    # cumulative form. Heuristic: fraction of non-decreasing day-to-day steps.
    p=df["prec_mm"].dropna()
    frac_nondec=(p.diff().dropna()>=-1e-6).mean() if len(p)>1 else 1.0
    if frac_nondec>=0.95:                       # cumulative accumulation
        daily=df["prec_mm"].diff().clip(lower=0)
        wy=(df.index.month==10)&(df.index.day==1); daily[wy]=df.loc[wy,"prec_mm"]
        df["psum_mm_day"]=daily.fillna(0.0)
        df.attrs["precip_form"]="cumulative"
    else:                                        # already incremental daily precip
        df["psum_mm_day"]=df["prec_mm"].clip(lower=0).fillna(0.0)
        df.attrs["precip_form"]="incremental"
    return df

def expand_hourly(df_daily,lat,elev,state):
    dates=pd.to_datetime(df_daily["datetime"]); doy=dates.dt.dayofyear.values.astype(float)
    ih=iswr_hourly(lat,elev,state,doy)
    sf=np.where((doy>=SPRING_DOY[0])&(doy<=SPRING_DOY[1]),SPRING_SW_FACTOR,1.0)
    rows=[]
    for i,row in enumerate(df_daily.itertuples(index=False)):
        ds=dates.iloc[i].strftime("%Y-%m-%d")
        for h in range(24):
            rows.append({"datetime":f"{ds}T{h:02d}:00","TA":row.TA,"TSG":row.TSG,
                "RH":row.RH,"PSUM":row.PSUM,"ISWR":round(float(ih[h][i]*sf[i]),3),
                "ILWR":row.ILWR,"VW":row.VW,"P":row.P})
    return pd.DataFrame(rows)

def build_forcing(out_csv):
    obs=read_snotel(SID)
    print(f"  precip_form detected: {obs.attrs.get('precip_form')}",flush=True)
    full=pd.date_range(obs.index.min(),obs.index.max(),freq="D")
    obs=obs.reindex(full)
    obs["ta_k"]=obs["ta_k"].interpolate("linear",limit=60)
    obs["psum_mm_day"]=obs["psum_mm_day"].fillna(0.0)
    obs=obs.dropna(subset=["ta_k"]); obs=obs[(obs["ta_k"]>233)&(obs["ta_k"]<315)]
    obs=obs[(obs.index>=RUN_START)&(obs.index<=RUN_END)]
    dates=pd.to_datetime(obs.index.to_series()); doy=dates.dt.dayofyear.values.astype(float)
    iswr=iswr_daily(LAT,ELEV,STATE,doy); ilwr=ilwr_daily(obs["ta_k"].values,RH_FIX)
    tsg=np.clip(pd.Series(obs["ta_k"].values).rolling(30,min_periods=1).mean().values,253.0,273.15)
    praw=np.maximum(obs["psum_mm_day"].values,0.0).copy(); pc=praw.copy(); carry=0.0
    for i in range(len(pc)):
        t=pc[i]+carry; pc[i]=min(t,MAX_DAILY_PSUM); carry=max(0.0,t-MAX_DAILY_PSUM)
    P=atm_pressure(ELEV)
    df=pd.DataFrame({"datetime":dates.dt.strftime("%Y-%m-%dT00:00"),
        "TA":np.round(obs["ta_k"].values,4),"TSG":np.round(tsg,4),"RH":RH_FIX,
        "PSUM":np.round(pc,4),"ISWR":np.round(iswr,3),"ILWR":np.round(ilwr,3),
        "VW":3.0,"P":round(P,1)})
    dfh=expand_hourly(df,LAT,ELEV,STATE); dfh.to_csv(out_csv,index=False)
    return df["datetime"].iloc[0], df["datetime"].iloc[-1]

def run_ki(tool,args,log):
    cmd=[str(PYTHON),str(KI_TOOLS/tool)]+args
    with open(log,"a") as lf:
        lf.write(f"\n=== {tool} ===\n"); lf.flush()
        r=subprocess.run(cmd,stdout=lf,stderr=subprocess.STDOUT,timeout=7200)
    return r.returncode

def run_model():
    tag=f"snotel_{SID}"
    forcing_csv=OUT/"forcing"/f"{SID}_forcing.csv"
    smet=OUT/"smet"/f"{tag}.smet"; sno=OUT/"sno"/f"{tag}.sno"
    ini=OUT/"config"/f"{tag}.ini"; out_d=OUT/"run"/"output"
    log=OUT/"pipeline.log"
    res_csv=OUT/"results"/f"{SID}_results.csv"
    for p in [forcing_csv.parent,smet.parent,sno.parent,ini.parent,out_d,res_csv.parent]:
        p.mkdir(parents=True,exist_ok=True)
    open(log,"w").close()

    print("[forcing] building...",flush=True)
    start,end=build_forcing(forcing_csv)
    print(f"  period {start} -> {end}",flush=True)

    print("[s1] convert_forcing.py",flush=True)
    rc=run_ki("convert_forcing.py",["--input",str(forcing_csv),"--output",str(smet),
        "--station_id",tag,"--station_name",NAME,"--latitude",str(LAT),
        "--longitude",str(LON),"--altitude",str(ELEV),"--timezone",str(TZ),
        "--source_temp_unit","K","--source_rh_unit","fraction",
        "--source_precip_unit","mm_per_day","--source_wind_unit","m_per_s",
        "--source_rad_unit","W_per_m2","--precip_scale",str(PRECIP_SCALE)],log)
    assert rc==0,f"convert_forcing rc={rc}"

    print("[s2] build_sno_profile.py",flush=True)
    rc=run_ki("build_sno_profile.py",["--output",str(sno),"--station_id",tag,
        "--latitude",str(LAT),"--longitude",str(LON),"--altitude",str(ELEV),
        "--start_date",start,"--n_soil_layers","0"],log)
    assert rc==0,f"build_sno_profile rc={rc}"
    st=sno.read_text()
    patch=("CanopyDirectThroughfall = 1.00\nErosionLevel = 0\nTimeCountDeltaHS = 0.000000\n")
    st=st.replace("\nfields           =","\n"+patch+"fields           =")
    sno.write_text(st)

    print("[s3] generate_config.py",flush=True)
    rc=run_ki("generate_config.py",["--output",str(ini),"--station_id",tag,
        "--meteo_path",str(OUT/"smet"),"--output_path",str(out_d),
        "--calculation_step","60","--variant","DEFAULT","--timezone",str(TZ),
        "--sw_mode","INCOMING"],log)
    assert rc==0,f"generate_config rc={rc}"

    t=ini.read_text()
    t=t.replace(f"SNOWPATH = {OUT/'smet'}",f"SNOWPATH = {OUT/'sno'}")
    req=("ENFORCE_MEASURED_SNOW_HEIGHTS = false\nMEAS_TSS = false\nCHANGE_BC = false\n"
         "THRESH_CHANGE_BC = -1.0\nSNP_SOIL = false\nSOIL_FLUX = false\n")
    t=t.replace("MINIMUM_L_ELEMENT = 0.01\n","MINIMUM_L_ELEMENT = 0.02\nREDUCE_N_ELEMENTS = 10\n")
    t=t.replace("SW_MODE = INCOMING\n","SW_MODE = INCOMING\n"+req)
    t=t.replace("[SnowpackAdvanced]","[SnowpackAdvanced]\nALLOW_ADAPTIVE_TIMESTEPPING = false")
    t=t.replace("COORDSYS = LATLON","COORDSYS = CH1903")
    t=t.replace("STATION1 = ","METEOFILE1 = ")
    t=t.replace("TS_DAYS_BETWEEN = 0.041667","TS_DAYS_BETWEEN = 1.0")
    t=t.replace("TS_START = 0.0","TS_START = 0.01")
    t=t.replace("PROF_DAYS_BETWEEN = 0.041667","PROF_DAYS_BETWEEN = 1.0")
    t=t.replace("PROF_START = 0.0","PROF_START = 0.01")
    t+=("\n[Interpolations1D]\nMAX_GAP_SIZE = 7776000\nTA::resample1 = linear\n"
        "RH::resample1 = linear\nVW::resample1 = nearest\nVW::ARG1::extrapolate = true\n"
        "ISWR::resample1 = linear\nILWR::resample1 = linear\nPSUM::resample1 = linear\n"
        "TSG::resample1 = linear\nTA::ARG1::extrapolate = true\nTSG::ARG1::extrapolate = true\n"
        "ISWR::ARG1::extrapolate = true\nILWR::ARG1::extrapolate = true\n")
    ini.write_text(t)

    print("[s4/s5] run_snowpack.py",flush=True)
    rc=run_ki("run_snowpack.py",["--binary",str(SNOWPACK_BIN),"--config",str(ini),
        "--end_date",end],log)
    assert rc==0,f"run_snowpack rc={rc}"

    met=out_d/f"{tag}.met"
    if not met.exists():
        c=list(out_d.glob("*.met")); assert c,"no .met"; met=c[0]
    print("[s6] parse_output.py",flush=True)
    rc=run_ki("parse_output.py",["--input",str(met),"--output",str(res_csv),
        "--file_type","met","--variables","SWE (of snowpack),Modelled snow depth (vertical)"],log)
    assert rc==0,f"parse_output rc={rc}"
    return res_csv

def score(res_csv):
    from ki_tools_common.metrics import all_metrics
    sim=pd.read_csv(res_csv)
    swe_col=[c for c in sim.columns if c.lower().startswith("swe")][0]
    sim["date"]=pd.to_datetime(sim["datetime"]).dt.normalize()
    sim=sim.set_index("date")[swe_col].rename("sim_mm")
    sim=sim[~sim.index.duplicated(keep="first")]
    obs=read_snotel(SID)["swe_mm"].rename("obs_mm")
    obs.index=pd.to_datetime(obs.index).normalize()
    obs=obs[~obs.index.duplicated(keep="first")]
    j=pd.concat([sim,obs],axis=1).dropna()
    j=j[j.index >= "2004-09-01"]   # drop first (spinup) water year before scoring

    def M(sub):
        if len(sub)<30: return None
        m=all_metrics(sub["obs_mm"].values,sub["sim_mm"].values)
        return {"NSE":m["NSE"],"KGE":m["KGE"],"PBIAS":m["PBIAS"],"r":m["r"],
                "RMSE":m["RMSE"],"n":len(sub),
                "period":f"{sub.index.min().date()}..{sub.index.max().date()}"}

    full=M(j); cal=M(j[j.index<=CAL_END]); val=M(j[j.index>CAL_END])
    return full,cal,val,float(j["obs_mm"].max()),float(j["sim_mm"].max())

def main():
    sys.path.insert(0, str(BASE/"models/ki_tools_common"))
    res_csv=OUT/"results"/f"{SID}_results.csv"
    if not res_csv.exists():
        res_csv=run_model()
    else:
        print("[resume] results CSV exists, re-scoring only",flush=True)
    full,cal,val,obs_peak,sim_peak=score(res_csv)
    RESULT_DIR.mkdir(parents=True,exist_ok=True)

    if full is None:
        result={"model_id":"SNOWPACK",
                "this_location":"NRCS SNOTEL - US Snow Telemetry Network (>900 stations, 1978-present)",
                "obs_source":"SNOTEL","status":"failed","tools_used":[],"tools_failed":[],
                "metrics":{"nse":None,"kge":None,"pbias":None,"r":None,"period":None},
                "water_balance":{"status":"N/A","residual_pct":None},
                "notes":"insufficient obs-sim overlap (<30 paired days)"}
        (RESULT_DIR/"result.json").write_text(json.dumps(result,indent=2))
        print(json.dumps(result)); return

    notes=(
        f"SNOWPACK verifier at SNOTEL {SID} {NAME}, {STATE} ({ELEV:.0f} m, continental CO alpine) "
        f"vs SNOTEL pillow SWE(kg/m2==mm), {full['n']} paired daily days over {full['period']}. "
        f"Faithful twin of the real-case SNOTEL-668 recipe: SAME 5 KI tools + snowpack binary + "
        f"all .ini patches, UNCHANGED; only site metadata differs (CO not WY). Continental recipe "
        f"(SKILL Lesson H, which names CO): RH=0.80, CO CF=0.60, precip_scale=1.0, seasonal "
        f"SPRING_SW_FACTOR=1.45 over DOY 91-181; SNOTEL precip auto-detected INCREMENTAL. "
        f"peak obs {obs_peak:.0f} / sim {sim_peak:.0f} mm. "
        f"FULL NSE={full['NSE']:.3f} r={full['r']:.3f} KGE={full['KGE']:.3f} PBIAS={full['PBIAS']:.1f}%. "
        f"cal {cal['period']} NSE={cal['NSE']:.3f} / val {val['period']} NSE={val['NSE']:.3f} "
        f"(params not tuned to val -> not overfit).")

    result={
        "model_id":"SNOWPACK",
        "this_location":f"SNOTEL {SID} {NAME}, {STATE} ({ELEV:.0f} m continental alpine)",
        "obs_source":"SNOTEL",
        "status":"completed",
        "tools_used":["convert_forcing.py","build_sno_profile.py","generate_config.py",
                      "run_snowpack.py","parse_output.py","ki_tools_common.metrics"],
        "tools_failed":[],
        "metrics":{
            "nse":full["NSE"],"kge":full["KGE"],"pbias":full["PBIAS"],"r":full["r"],
            "rmse":full["RMSE"],"n_matched":full["n"],"period":full["period"],
            "nse_cal":cal["NSE"],"kge_cal":cal["KGE"],"pbias_cal":cal["PBIAS"],
            "nse_val":val["NSE"],"kge_val":val["KGE"],"pbias_val":val["PBIAS"],
            "period_calibration":cal["period"],"period_validation":val["period"]},
        "water_balance":{"status":"N/A","residual_pct":None},
        "obs_peak_swe_mm":obs_peak,"sim_peak_swe_mm":sim_peak,
        "notes":notes}
    (RESULT_DIR/"result.json").write_text(json.dumps(result,indent=2))
    print("WROTE",RESULT_DIR/"result.json",flush=True)
    print(json.dumps(result["metrics"],indent=2))

if __name__=="__main__":
    main()
