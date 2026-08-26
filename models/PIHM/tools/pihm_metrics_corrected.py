#!/usr/bin/env python3
"""ShaleHills metrics with corrected sim timestamp alignment.

PIHM stamps daily output at the END of the averaging window (00:00 of the
next day). So a value labelled '2009-06-15 00:00' is the daily mean for
2009-06-14. Shift sim back by one day before joining with obs.
"""
import math
from datetime import datetime, date, timedelta
from pathlib import Path

REPO = Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/PIHM/source/repo")
SIM = REPO / "output/test_run/ShaleHills.river.flx1.txt"
OBS = ["/tmp/SH_2008.dat", "/tmp/SH_2009.dat", "/tmp/SH_2010.dat"]


def read_sim_corrected(col_idx=20):
    series = {}
    with open(SIM) as f:
        for line in f:
            ps = line.strip().split("\t")
            if len(ps) < col_idx + 1:
                continue
            try:
                dt = datetime.strptime(ps[0].strip('"'), "%Y-%m-%d %H:%M").date()
                v = float(ps[col_idx])
            except (ValueError, IndexError):
                continue
            # PIHM timestamp = end of averaging window → represents prior day
            d_repr = dt - timedelta(days=1)
            series[d_repr] = v
    return series


def read_obs():
    daily_sum = {}; daily_n = {}
    for p in OBS:
        with open(p) as f:
            next(f)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ts_str, rest = line.split(",", 1)
                    val_str, _, flag = rest.partition(":q=")
                    val = float(val_str)
                    dt = datetime.strptime(ts_str.strip(), "%m/%d/%Y %H:%M").date()
                except (ValueError, IndexError):
                    continue
                daily_sum[dt] = daily_sum.get(dt, 0.0) + val
                daily_n[dt] = daily_n.get(dt, 0) + 1
    return {d: daily_sum[d]/n/86400.0 for d, n in daily_n.items() if n >= 100}


def metrics(sim, obs, label):
    pairs = [(sim[d], obs[d]) for d in sim if d in obs]
    if not pairs:
        return print(f"  {label}: no overlap")
    s = [p[0] for p in pairs]; o = [p[1] for p in pairs]
    n = len(s); mo, ms = sum(o)/n, sum(s)/n
    nse_num = sum((oi - si)**2 for oi, si in zip(o, s))
    nse_den = sum((oi - mo)**2 for oi in o)
    nse = 1 - nse_num/nse_den if nse_den > 0 else float("nan")
    pbias = 100*(sum(s)-sum(o))/sum(o) if sum(o) else float("nan")
    so = math.sqrt(sum((oi-mo)**2 for oi in o)/n)
    ss = math.sqrt(sum((si-ms)**2 for si in s)/n)
    cov = sum((oi-mo)*(si-ms) for oi, si in zip(o, s))/n
    r = cov/(so*ss) if so>0 and ss>0 else float("nan")
    alpha = ss/so if so>0 else float("nan")
    beta = ms/mo if mo else float("nan")
    kge = 1 - math.sqrt((r-1)**2 + (alpha-1)**2 + (beta-1)**2)
    rs = sorted(set(s)); ro = sorted(set(o))
    rsi = {v:i for i,v in enumerate(rs)}; roi = {v:i for i,v in enumerate(ro)}
    sr = [rsi[v] for v in s]; orank = [roi[v] for v in o]
    msr = sum(sr)/n; mor = sum(orank)/n
    cov_r = sum((srk-msr)*(ork-mor) for srk, ork in zip(sr, orank))/n
    sd_sr = math.sqrt(sum((srk-msr)**2 for srk in sr)/n)
    sd_or = math.sqrt(sum((ork-mor)**2 for ork in orank)/n)
    spearman = cov_r/(sd_sr*sd_or) if sd_sr>0 and sd_or>0 else float("nan")
    sl = [math.log(max(v, 1e-12)) for v in s]; ol = [math.log(max(v, 1e-12)) for v in o]
    msl = sum(sl)/n; mol = sum(ol)/n
    ssl = math.sqrt(sum((x-msl)**2 for x in sl)/n)
    sol = math.sqrt(sum((x-mol)**2 for x in ol)/n)
    covl = sum((x-msl)*(y-mol) for x,y in zip(sl, ol))/n
    rlog = covl/(ssl*sol) if ssl>0 and sol>0 else float("nan")
    print(f"  {label}: n={n}  mean_sim={ms:.5f}  mean_obs={mo:.5f}")
    print(f"    NSE={nse:+.3f}  KGE={kge:+.3f}  r={r:+.3f}  r(log)={rlog:+.3f}  spearman={spearman:+.3f}  PBIAS={pbias:+.1f}%")


sim = read_sim_corrected(20)
obs = read_obs()

print("ShaleHills with CORRECTED time alignment (sim timestamp -1 day):")
metrics(sim, obs, "full overlap (incl. spinup)")
sim_p = {d: v for d, v in sim.items() if d >= date(2009, 1, 1)}
metrics(sim_p, obs, "post-spinup 2009-01-01 onwards")
sim_p = {d: v for d, v in sim.items() if d >= date(2009, 4, 1)}
metrics(sim_p, obs, "drop first 5 mo (extended spinup)")
