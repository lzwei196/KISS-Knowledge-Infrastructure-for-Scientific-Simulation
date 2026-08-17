#!/usr/bin/env python3
"""Compute NSE/KGE/PBIAS/r for PIHM runs at Bengbu, Wangjiaba, ShaleHills."""
import csv
import math
from datetime import datetime
from pathlib import Path

REPO = Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/PIHM/source/repo")
OBS_DIR = Path("KISSPATH_OBS")


def read_sim(path, col_idx=1):
    """Read PIHM rivflx ASCII. col_idx=1 for single-segment, 20 for ShaleHills outlet."""
    series = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 2:
                continue
            ts = parts[0].strip('"')
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            try:
                v = float(parts[col_idx])
            except (IndexError, ValueError):
                continue
            series[dt.date()] = v
    return series


def read_obs_cn(path):
    """Read Chinese-format obs: stcd<TAB>dates<TAB>z<TAB>Q<TAB>name."""
    series = {}
    with open(path, encoding="latin-1") as f:
        next(f)  # header
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            try:
                y, m, d = parts[1].split("-")
                dt = datetime(int(y), int(m), int(d)).date()
                q = float(parts[3])
            except (ValueError, IndexError):
                continue
            series[dt] = q
    return series


def metrics(sim, obs):
    pairs = [(sim[d], obs[d]) for d in sim if d in obs]
    if len(pairs) < 2:
        return None
    s = [p[0] for p in pairs]
    o = [p[1] for p in pairs]
    n = len(s)
    mo = sum(o) / n
    ms = sum(s) / n
    num = sum((oi - si) ** 2 for oi, si in zip(o, s))
    den = sum((oi - mo) ** 2 for oi in o)
    nse = 1 - num / den if den > 0 else float("nan")
    pbias = 100.0 * (sum(s) - sum(o)) / sum(o) if sum(o) != 0 else float("nan")
    so = math.sqrt(sum((oi - mo) ** 2 for oi in o) / n)
    ss = math.sqrt(sum((si - ms) ** 2 for si in s) / n)
    cov = sum((oi - mo) * (si - ms) for oi, si in zip(o, s)) / n
    r = cov / (so * ss) if (so > 0 and ss > 0) else float("nan")
    alpha = ss / so if so > 0 else float("nan")
    beta = ms / mo if mo != 0 else float("nan")
    kge = 1 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return {
        "n": n,
        "first": min(d for d in sim if d in obs).isoformat(),
        "last": max(d for d in sim if d in obs).isoformat(),
        "mean_sim": ms,
        "mean_obs": mo,
        "NSE": nse,
        "KGE": kge,
        "r": r,
        "PBIAS_%": pbias,
        "alpha": alpha,
        "beta": beta,
    }


def report(name, sim_path, col_idx, obs_path, spinup_until=None):
    sim = read_sim(sim_path, col_idx)
    print(f"\n=== {name} ===")
    print(f"  sim file : {sim_path}")
    print(f"  sim dates: {min(sim)} → {max(sim)}  ({len(sim)} days)")
    if obs_path is None:
        print(f"  obs file : (none — outlet sim mean = "
              f"{sum(sim.values())/len(sim):.4f} m3/s)")
        return
    obs = read_obs_cn(obs_path)
    print(f"  obs file : {obs_path}")
    print(f"  obs dates: {min(obs)} → {max(obs)}  ({len(obs)} days)")

    # Full overlap
    m = metrics(sim, obs)
    if m:
        print("  -- full overlap --")
        for k, v in m.items():
            print(f"    {k:>10}: {v}")

    # Drop spinup
    if spinup_until is not None:
        sim_p = {d: v for d, v in sim.items() if d >= spinup_until}
        m2 = metrics(sim_p, obs)
        if m2:
            print(f"  -- after spinup ({spinup_until}) --")
            for k, v in m2.items():
                print(f"    {k:>10}: {v}")


if __name__ == "__main__":
    report(
        "Bengbu (single-segment outlet)",
        REPO / "output/bengbu_val/Bengbu.river.flx1.txt",
        col_idx=1,
        obs_path=OBS_DIR / "BB/51080_bengbu.txt",
        spinup_until=datetime(1981, 1, 1).date(),
    )
    report(
        "Wangjiaba (single-segment outlet)",
        REPO / "output/kdt_test_pihm/Wangjiaba.river.flx1.txt",
        col_idx=1,
        obs_path=OBS_DIR / "WJB/HUAIH-51030-wangjiaba.txt",
        spinup_until=datetime(1976, 1, 1).date(),
    )
    report(
        "ShaleHills (segment 20 = outlet)",
        REPO / "output/test_run/ShaleHills.river.flx1.txt",
        col_idx=20,
        obs_path=None,
    )
