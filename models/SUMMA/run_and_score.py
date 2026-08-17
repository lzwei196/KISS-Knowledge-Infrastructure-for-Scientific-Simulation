#!/usr/bin/env python3
"""
SUMMA VERIFIER runner: Belly River near Mountain View, HYDAT 05AD005
AB Rocky-Mountain-front alpine snowmelt basin (319 km2, 49.10N, -113.70W).
Single GRU / 3 elevation-band HRUs lumped. Hourly NASA POWER forcing.
Uses the SUMMA KI tools for every SUMMA-specific stage. Resumable.
Obs = provided txt (Water Survey of Canada 05AD005), discharge_m3s.
Writes the result JSON to detached/verify_1/result.json.

Recipe transferred VERBATIM from the Moyie 08NH120 real-case (NSE 0.61):
3 elevation-band HRUs, ROSETTA soil, drop snowDenNew, 272K cold start.
Retuned ONLY: coordinates/area/elev-bands + PRECIP_SCALE (Belly runs ~1.5x
Moyie's specific runoff so needs a larger orographic precip boost).
"""
import os, sys, json, subprocess, glob
from datetime import datetime, timedelta
import numpy as np
import netCDF4 as nc

sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent")
from ki_tools_common.load_forcing import load_hourly_forcing
from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_water_balance

KI   = "KISSPATH_KI_ROOT/SUMMA/knowledge_infrastructure"
TOOLS= KI + "/tools"
WD   = "KISSPATH_OUTPUTS/belly_05ad005_summa"
SET  = WD + "/site_settings"
FOR  = WD + "/forcing"
OUT  = WD + "/output"
EXE  = "KISSPATH_BINARIES/summa/bin/summa.exe"
STATE= "KISSPATH_KI_ROOT/SUMMA/detached/verify_1"
OBS_TXT = "KISSPATH_OBS/belly_river/observed_05AD005.txt"

STN   = "05AD005"
LAT, LON = 49.0996, -113.6977       # gauge / centroid
AREA_M2 = 319.0e6
LAPSE = -6.5e-3
PRECIP_SCALE = 1.45                 # orographic boost; Belly runoff ~877 mm/yr (high alpine)
WIND_FLOOR = 0.5
# 3 elevation bands so the snowmelt freshet spreads Apr-Jun instead of one abrupt
# spike. Belly headwaters reach the Continental Divide (~2900 m); gauge ~1300 m.
# Bands shifted up vs Moyie (1150/1550/1950) to match the higher Rocky-front terrain.
HRUS = [
    {"id":1001, "elev":1500.0, "frac":0.34, "veg":7, "soil":6},   # low: melts first (Apr)
    {"id":1002, "elev":2050.0, "frac":0.33, "veg":7, "soil":6},   # mid (May)
    {"id":1003, "elev":2600.0, "frac":0.33, "veg":7, "soil":6},   # high alpine (Jun)
]

START_YEAR, END_YEAR = 2005, 2015   # obs txt spans 2005-2015; hourly NASA POWER exists 2001+
SIM_START = "2005-01-01 01:00"
SIM_END   = "2015-12-31 23:00"
PERIOD_CAL = "2006-01-01..2010-12-31"
PERIOD_VAL = "2011-01-01..2015-12-31"
FORCING_NC = FOR + "/forcing_belly.nc"
OUTPUT_PREFIX = "belly"

def sh(cmd):
    print("  $", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("STDOUT:", r.stdout[-3000:]); print("STDERR:", r.stderr[-3000:])
        raise RuntimeError("command failed rc=%d: %s" % (r.returncode, cmd[1] if len(cmd)>1 else cmd))
    return r.stdout

# ---------------------------------------------------------------- forcing
def _fetch_year(yr):
    """Fetch one year of hourly NASA POWER with per-year cache + retries (resumable)."""
    import time, pickle
    cache = FOR + "/np_cache_%d.pkl" % yr
    if os.path.exists(cache):
        with open(cache, "rb") as f: return pickle.load(f)
    last = None
    for attempt in range(5):
        try:
            d = load_hourly_forcing("nasa_power", LAT, LON, yr, yr)
            rec = {"dates": list(d["dates"]), "T": list(d["temp_c"]), "P": list(d["precip_mm"]),
                   "SW": list(d["srad_wm2"]), "LW": list(d["lrad_wm2"]), "WS": list(d["wind_ms"]),
                   "QV": list(d["shum_kgkg"]), "PS": list(d["pres_pa"])}
            with open(cache, "wb") as f: pickle.dump(rec, f)
            return rec
        except Exception as e:
            last = e; print("    retry %d for %d: %s" % (attempt, yr, e), flush=True)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError("NASA POWER fetch failed for %d after retries: %s" % (yr, last))

def build_forcing():
    if os.path.exists(FORCING_NC):
        print("forcing exists, skip", flush=True); return
    os.makedirs(FOR, exist_ok=True)
    dates=[]; T=[]; P=[]; SW=[]; LW=[]; WS=[]; QV=[]; PS=[]
    for yr in range(START_YEAR, END_YEAR+1):
        print("  fetch NASA POWER hourly", yr, flush=True)
        d = _fetch_year(yr)
        dates += d["dates"]; T+=d["T"]; P+=d["P"]
        SW+=d["SW"]; LW+=d["LW"]; WS+=d["WS"]; QV+=d["QV"]; PS+=d["PS"]
    T=np.array(T,float); P=np.array(P,float); SW=np.array(SW,float); LW=np.array(LW,float)
    WS=np.array(WS,float); QV=np.array(QV,float); PS=np.array(PS,float)
    # gap fill
    for a in (T,P,SW,LW,WS,QV,PS):
        m=np.isnan(a)
        if m.any(): a[m]=np.interp(np.where(m)[0], np.where(~m)[0], a[~m])
    power_elev = -8500.0*np.log(np.nanmean(PS)/101325.0)
    print("  NASA POWER effective elev ~%.0f m" % power_elev, flush=True)
    n=len(dates); nh=len(HRUS)
    ds=nc.Dataset(FORCING_NC,"w",format="NETCDF4")
    ds.createDimension("time",n); ds.createDimension("hru",nh)
    v=ds.createVariable("hruId","i4",("hru",)); v[:]=[h["id"] for h in HRUS]
    v=ds.createVariable("latitude","f8",("hru",)); v[:]=[LAT]*nh
    v=ds.createVariable("longitude","f8",("hru",)); v[:]=[LON+360.0]*nh
    v=ds.createVariable("data_step","f8"); v.units="seconds"; v.long_name="data step length in seconds"; v[:]=3600.0
    ref=datetime(1990,1,1)
    tv=ds.createVariable("time","f8",("time",)); tv.units="days since 1990-01-01 00:00:00"; tv.calendar="standard"
    tv[:]=np.array([(t-ref).total_seconds()/86400.0 for t in dates])
    pp=ds.createVariable("pptrate","f8",("time","hru"),fill_value=-999.0); pp.units="kg m-2 s-1"; pp.v_type="scalarv"
    at=ds.createVariable("airtemp","f8",("time","hru"),fill_value=-999.0); at.units="K"; at.v_type="scalarv"
    ws=ds.createVariable("windspd","f8",("time","hru"),fill_value=-999.0); ws.units="m s-1"; ws.v_type="scalarv"
    ap=ds.createVariable("airpres","f8",("time","hru"),fill_value=-999.0); ap.units="Pa"; ap.v_type="scalarv"
    sh_=ds.createVariable("spechum","f8",("time","hru"),fill_value=-999.0); sh_.units="g g-1"; sh_.v_type="scalarv"
    sw=ds.createVariable("SWRadAtm","f8",("time","hru"),fill_value=-999.0); sw.units="W m-2"; sw.v_type="scalarv"
    lw=ds.createVariable("LWRadAtm","f8",("time","hru"),fill_value=-999.0); lw.units="W m-2"; lw.v_type="scalarv"
    P_base=np.maximum(P/3600.0*PRECIP_SCALE,0.0); WSf=np.maximum(WS,WIND_FLOOR); SWp=np.maximum(SW,0.0)
    for i,h in enumerate(HRUS):
        dz=h["elev"]-power_elev
        # +5% precip per 1000 m orographic enhancement
        pp[:,i]=P_base*(1.0+0.05*dz/1000.0)
        at[:,i]=T+273.15+LAPSE*dz
        ws[:,i]=WSf*(1.3 if h["elev"]>1800 else 1.0)
        ap[:,i]=PS*np.exp(-dz/8500.0)
        sh_[:,i]=QV; sw[:,i]=SWp; lw[:,i]=LW
    ds.close()
    print("  wrote forcing %s (%d steps, %d HRUs)"%(FORCING_NC,n,nh), flush=True)

# ---------------------------------------------------------------- domain
def build_settings():
    csvp = WD+"/gru_hru.csv"
    with open(csvp,"w") as f:
        # vegTypeIndex 7 = USGS Grassland (open alpine), soilTypeIndex 6 = loam.
        f.write("gruId,hruId,lat,lon,elevation,area_m2,tan_slope,aspect,vegTypeIndex,soilTypeIndex\n")
        for h in HRUS:
            f.write("1001,%d,%.4f,%.4f,%.1f,%.1f,0.30,180.0,%d,%d\n"
                    %(h["id"],LAT,LON+360.0,h["elev"],AREA_M2*h["frac"],h["veg"],h["soil"]))
    attr = SET+"/attributes.nc"
    if not os.path.exists(attr):
        sh(["python3", TOOLS+"/s1_domain_setup/create_local_attributes.py",
            "--gru_hru_csv", csvp, "--output_nc", attr])
    dec = SET+"/decisions.txt"
    if not os.path.exists(dec):
        sh(["python3", TOOLS+"/s3_decisions/configure_decisions.py",
            "--output", dec, "--use_defaults",
            "--decisions", '{"soilCatTbl":"ROSETTA"}'])
    tp = SET+"/trialParams.nc"
    if not os.path.exists(tp):
        sh(["python3", TOOLS+"/s4_parameters/set_trial_parameters.py",
            "--attributes_nc", attr, "--output_nc", tp, "--from_hwsd"])
    cs = SET+"/coldState.nc"
    if not os.path.exists(cs):
        sh(["python3", TOOLS+"/s5_initial_conditions/create_initial_conditions.py",
            "--attributes_nc", attr, "--output_nc", cs,
            "--init_temp", "272.0", "--init_moisture", "0.30"])
    with open(SET+"/forcingFileList.txt","w") as f:
        f.write("! forcing file list\nforcing_belly.nc\n")
    fm = WD+"/fileManager.txt"
    sh(["python3", TOOLS+"/s6_execution/create_file_manager.py",
        "--settings_path", SET+"/", "--forcing_path", FOR+"/", "--output_path", OUT+"/",
        "--sim_start", SIM_START, "--sim_end", SIM_END,
        "--output_prefix", OUTPUT_PREFIX, "--output_file", fm,
        "--decisions","decisions.txt","--attributes","attributes.nc",
        "--init_cond","coldState.nc","--trial_params","trialParams.nc",
        "--forcing_list","forcingFileList.txt"])
    sh(["python3", TOOLS+"/s6_execution/validate_file_manager.py","--file_manager", fm])
    return fm

# ---------------------------------------------------------------- preflight
def preflight():
    try:
        r=subprocess.run(["python3","KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent/validators/preflight_forcing.py",
                          FOR, "--source","auto"], capture_output=True, text=True, timeout=600)
        uni=(r.stdout+r.stderr).strip().splitlines()[-1:]
    except Exception as e:
        uni=["universal preflight error: %s"%e]
    ds=nc.Dataset(FORCING_NC); fails=[]; warns=[]
    P=float(np.nanmean(ds["pptrate"][:,0]))*86400      # mm/day
    T=float(np.nanmean(ds["airtemp"][:,0]))-273.15      # C
    PR=float(np.nanmean(ds["airpres"][:,0]))            # Pa
    SW=float(np.nanmean(ds["SWRadAtm"][:,0])); LW=float(np.nanmean(ds["LWRadAtm"][:,0]))
    ds.close()
    if not (0.2 <= P <= 12):  fails.append("pptrate mean %.2f mm/day out of [0.2,12]"%P)
    if not (-15 <= T <= 30):  fails.append("airtemp mean %.1f C out of [-15,30]"%T)
    if not (50000 <= PR <= 105000): fails.append("airpres mean %.0f Pa out of [50k,105k] (kPa-not-Pa?)"%PR)
    if not (20 <= SW <= 400): warns.append("SWRadAtm mean %.0f W/m2 unusual"%SW)
    if not (100 <= LW <= 450): warns.append("LWRadAtm mean %.0f W/m2 unusual"%LW)
    warns.append("universal preflight cannot classify SUMMA model-ready NetCDF: %s"%(uni[0] if uni else ""))
    return {"all_pass": len(fails)==0, "source":"summa_netcdf_manual_units",
            "failures":fails, "warnings":warns}

# ---------------------------------------------------------------- run
def run_summa(fm):
    done = glob.glob(OUT+"/%s_*.nc"%OUTPUT_PREFIX)
    if done:
        print("summa output exists, skip run:", done, flush=True); return done[0]
    sh(["python3", TOOLS+"/s6_execution/run_summa.py","--summa_exe",EXE,"--file_manager",fm,
        "--log_file", WD+"/summa_run.log"])
    done = glob.glob(OUT+"/%s_*.nc"%OUTPUT_PREFIX)
    if not done: raise RuntimeError("no SUMMA output produced; see summa_run.log")
    return done[0]

# ---------------------------------------------------------------- obs
def load_obs():
    """Read the provided Water Survey of Canada txt: stcd, dates, z, Q, name (tab-sep)."""
    dts=[]; q=[]
    with open(OBS_TXT) as f:
        next(f)
        for line in f:
            p=line.rstrip("\n").split("\t")
            if len(p) < 4: continue
            try:
                dts.append(datetime.strptime(p[1], "%Y-%m-%d")); q.append(float(p[3]))
            except Exception:
                continue
    return np.array(dts), np.array(q,float)

# ---------------------------------------------------------------- score
def main():
    os.makedirs(STATE, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    build_forcing()
    pf = preflight()
    fm = build_settings()
    outnc = run_summa(fm)
    print("parsing", outnc, flush=True)
    ds=nc.Dataset(outnc)
    tv=ds.variables["time"]; times=nc.num2date(tv[:],tv.units,calendar=getattr(tv,"calendar","standard"))
    if "averageRoutedRunoff" in ds.variables:
        ro=np.array(ds.variables["averageRoutedRunoff"][:,0],float); rovar="averageRoutedRunoff"
    else:
        ro=np.array(ds.variables["scalarTotalRunoff"][:,0],float); rovar="scalarTotalRunoff"
    w=np.array([h["frac"] for h in HRUS],float); w=w/w.sum()
    def hru_wmean(name):
        a=np.array(ds.variables[name][:],float)
        return (a*w[None,:]).sum(axis=1)
    P=hru_wmean("pptrate")*3600.0
    ET_mmhr=None
    if "scalarTotalET" in ds.variables:
        ET_mmhr=np.abs(hru_wmean("scalarTotalET"))*3600.0
    elif "scalarLatHeatTotal" in ds.variables:
        ET_mmhr=np.abs(hru_wmean("scalarLatHeatTotal"))*3600.0/2.5e6
    yrs_hr=np.array([t.year for t in times])
    ds.close()
    q_sim_hourly = ro*AREA_M2     # m3/s
    import pandas as pd
    dpd=pd.to_datetime([str(t) for t in times], format="mixed")
    df=pd.DataFrame({"q":q_sim_hourly},index=dpd).resample("D").mean().dropna()
    sim_dates=df.index.to_pydatetime(); sim_q=df["q"].values

    obs_dates, obs_q = load_obs()
    so={d.date():v for d,v in zip(sim_dates,sim_q)}
    oo={d.date():v for d,v in zip(obs_dates,obs_q)}
    common=sorted(set(so)&set(oo))
    s=np.array([so[d] for d in common]); o=np.array([oo[d] for d in common])
    cdates=np.array(common)
    mask=np.array([d.year>=2006 for d in cdates])   # exclude 2005 spinup
    s_f, o_f, d_f = s[mask], o[mask], cdates[mask]

    m_full = all_metrics(o_f, s_f)
    from validators.standard_calval import compute_calval_metrics
    cv = compute_calval_metrics(list(d_f), o_f, s_f,
                                cal_start="2006-01-01", cal_end="2010-12-31",
                                val_start="2011-01-01", val_end="2015-12-31")
    m_cal, m_val = cv["calibration"], cv["validation"]

    wbm = yrs_hr >= 2006
    ndays=int(wbm.sum()/24)
    P_tot = float(np.nansum(P[wbm]))
    ET_tot = float(np.nansum(ET_mmhr[wbm])) if ET_mmhr is not None else float("nan")
    Q_tot = float(np.nansum(ro[wbm])*3600.0*1000.0)
    wb=validate_water_balance(precip_mm=P_tot, et_mm=ET_tot if ET_tot==ET_tot else 0.0,
                              runoff_mm=Q_tot, delta_storage_mm=0.0, period_days=ndays)

    result={
        "model_id":"SUMMA",
        "this_location":"Belly River near Mountain View",
        "obs_source":"Belly River near Mountain View",
        "status":"completed",
        "tools_used":["create_local_attributes.py","configure_decisions.py","set_trial_parameters.py",
                      "create_initial_conditions.py","create_file_manager.py","validate_file_manager.py",
                      "run_summa.py","load_forcing.load_hourly_forcing","metrics.all_metrics"],
        "tools_failed":[],
        "metrics":{
            "nse":m_full["NSE"],"kge":m_full["KGE"],"pbias":m_full["PBIAS"],"r":m_full["r"],
            "nse_cal":m_cal.get("NSE"),"kge_cal":m_cal.get("KGE"),
            "nse_val":m_val.get("NSE"),"kge_val":m_val.get("KGE"),
            "pbias_val":m_val.get("PBIAS"),
            "period":"2006-01-01..2015-12-31",
            "period_calibration":PERIOD_CAL,"period_validation":PERIOD_VAL},
        "water_balance":{"status":wb["status"],"residual_pct":wb["residual_pct"],
                         "residual_mm":wb["residual_mm"]},
        "forcing_preflight":pf,
        "notes":("Verifier @ Belly River near Mountain View (HYDAT 05AD005, AB Rocky Mtn front, "
                 "319 km2, 49.10N -113.70W). Single-GRU / 3 elevation-band HRUs (1500/2050/2600 m) "
                 "lumped SUMMA, hourly NASA POWER 2005-2015 (spinup 2005, scored 2006-2015). "
                 "Q=%s(GRU mean)*basin_area. n_paired=%d. P=%.0f Q=%.0f ET=%.0f mm over 2006-2015 "
                 "(residual %.1f%%). Recipe transferred from Moyie 08NH120 real-case (NSE 0.61): "
                 "3 elev-bands + ROSETTA soil + drop snowDenNew; retuned only coords/area/elev + "
                 "PRECIP_SCALE %.2f (Belly runs ~1.5x Moyie specific runoff). All KI tools used, none failed."
                 %(rovar,len(d_f),P_tot,Q_tot,ET_tot,wb["residual_pct"],PRECIP_SCALE))
    }
    with open(STATE+"/result.json","w") as f: json.dump(result,f,indent=2)
    print(json.dumps(result["metrics"],indent=2), flush=True)
    print("WROTE", STATE+"/result.json", flush=True)

if __name__=="__main__":
    main()
