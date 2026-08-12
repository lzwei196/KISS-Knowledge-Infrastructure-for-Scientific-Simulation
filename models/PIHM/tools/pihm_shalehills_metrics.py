#!/usr/bin/env python3
"""ShaleHills PIHM vs SSHCZO weir obs (HydroShare resource 95f52e8c…).

Sim:  rivflx1.txt segment 20 (outlet), m3/s, daily.
Obs:  10-min discharge in m3/day → aggregate to daily mean → convert to m3/s.
"""
import csv
import math
from datetime import datetime, date
from pathlib import Path

REPO = Path("/home/server/knowledge-dissection-toolkit/auto_dissect/_work/PIHM/source/repo")
SIM_PATH = REPO / "output/test_run/ShaleHills.river.flx1.txt"
OBS_FILES = ["/tmp/SH_2008.dat", "/tmp/SH_2009.dat", "/tmp/SH_2010.dat"]


def read_sim(path, col_idx=20):
    series = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < col_idx + 1:
                continue
            try:
                dt = datetime.strptime(parts[0].strip('"'), "%Y-%m-%d %H:%M")
                v = float(parts[col_idx])
            except ValueError:
                continue
            series[dt.date()] = v
    return series


def read_obs_sshczo(paths):
    """Return daily mean discharge in m3/s, plus QC fraction.

    Each line: 'MM/DD/YYYY HH:MM,VAL:q=FLAG'. cmd = m3/day.
    Quality flag A = approved, U = unverified, E = estimated, M = missing.
    """
    daily_sum = {}
    daily_n = {}
    daily_good = {}
    for p in paths:
        with open(p) as f:
            next(f)  # header
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ts_str, rest = line.split(",", 1)
                    val_str, _, flag_part = rest.partition(":q=")
                    flag = flag_part.strip()
                    val = float(val_str)
                    dt = datetime.strptime(ts_str.strip(), "%m/%d/%Y %H:%M")
                except (ValueError, IndexError):
                    continue
                d = dt.date()
                daily_sum[d] = daily_sum.get(d, 0.0) + val
                daily_n[d] = daily_n.get(d, 0) + 1
                if flag in ("A",):
                    daily_good[d] = daily_good.get(d, 0) + 1

    out = {}
    qc_frac = {}
    for d, n in daily_n.items():
        if n < 100:  # need at least ~17 hr of 10-min data
            continue
        mean_cmd = daily_sum[d] / n
        out[d] = mean_cmd / 86400.0  # m3/day -> m3/s
        qc_frac[d] = daily_good.get(d, 0) / n
    return out, qc_frac


def metrics(sim, obs, label):
    pairs = [(sim[d], obs[d]) for d in sim if d in obs]
    if not pairs:
        print(f"  {label}: no overlap")
        return
    s = [p[0] for p in pairs]
    o = [p[1] for p in pairs]
    n = len(s)
    mo, ms = sum(o)/n, sum(s)/n
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
    print(f"  {label}: n={n}  mean_sim={ms:.5f}  mean_obs={mo:.5f}")
    print(f"    NSE={nse:.4f}  KGE={kge:.4f}  r={r:.4f}  PBIAS={pbias:.2f}%  alpha={alpha:.3f}  beta={beta:.3f}")


def main():
    sim = read_sim(SIM_PATH, col_idx=20)
    obs, qc = read_obs_sshczo(OBS_FILES)
    print(f"Sim: {len(sim)} days, {min(sim)} → {max(sim)}")
    print(f"Obs: {len(obs)} days, {min(obs)} → {max(obs)}")
    print(f"  obs sample (m3/s): "
          f"min={min(obs.values()):.5f}  max={max(obs.values()):.5f}  "
          f"mean={sum(obs.values())/len(obs):.5f}")

    print("\n-- ShaleHills outlet (segment 20) --")
    metrics(sim, obs, "full overlap (incl. spinup)")

    # Drop the first ~3 months as spinup (sim starts 2008-10-21; usable from ~2009-01-01)
    spinup_end = date(2009, 1, 1)
    sim_p = {d: v for d, v in sim.items() if d >= spinup_end}
    metrics(sim_p, obs, f"after spinup ({spinup_end})")

    # Also try summing all 20 segments (basin-integrated)
    sim_sum = {}
    with open(SIM_PATH) as f:
        for line in f:
            parts = line.strip().split("\t")
            try:
                dt = datetime.strptime(parts[0].strip('"'), "%Y-%m-%d %H:%M").date()
                sim_sum[dt] = sum(float(x) for x in parts[1:21])
            except (ValueError, IndexError):
                continue
    sim_sum_p = {d: v for d, v in sim_sum.items() if d >= spinup_end}
    metrics(sim_sum_p, obs, "sum-of-all-segments, post-spinup (sanity check)")


if __name__ == "__main__":
    main()
