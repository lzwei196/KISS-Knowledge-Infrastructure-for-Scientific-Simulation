#!/usr/bin/env python3
import csv
import datetime as dt
import math
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple

VIC_EXE = "/Volumes/Expansion4t/hydro-space2/model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe"
ROUT_EXE = "/Volumes/Expansion4t/hydro-space2/model/route_1.0/src/rout"

BASIN_NAME = "bengbu"
BASE_OUTPUT_DIR = "/Volumes/Expansion4t/hydro-space2/outputs"
BASE_RUN_DIR = os.path.join(BASE_OUTPUT_DIR, "bengbu_1979-1980_025deg")
SOIL_BASE = os.path.join(BASE_RUN_DIR, "vic_temp", "soil", "SOIL_PARAM_COMPLETE.txt")
GLOBAL_BASE = os.path.join(BASE_RUN_DIR, "vic_temp", "global_param_bengbu_1979-1980_025deg.txt")
OBS_FILE = "/Volumes/Expansion4t/hydro-space2/data/obs/BB/51080_bengbu.txt"

ROUT_TEMPLATE_DIR = "/Volumes/Expansion4t/hydro-space/docs/rout"
FLUX_PREFIX = "huaihe_fluxes_"
START_YEAR = 1979
END_YEAR = 1980

OUTPUT_ROOT = os.path.join(BASE_OUTPUT_DIR, f"{BASIN_NAME}_calibration_ai")
CURRENT_DIR = os.path.join(OUTPUT_ROOT, "current_run")
BEST_DIR = os.path.join(OUTPUT_ROOT, "best_run")

PARAM_RANGES = {
    "binfilt": (0.01, 1.0),
    "Ds": (0.0, 1.0),
    "Dsmax": (5.0, 20.0),
    "Ws": (0.1, 1.0),
    "soil_d2": (0.3, 1.0),
    "soil_d3": (0.8, 2.0),
}

INDEX_MAP = {
    "binfilt": 4,
    "Ds": 5,
    "Dsmax": 6,
    "Ws": 7,
    "soil_d2": 23,
    "soil_d3": 24,
}


@dataclass
class RuntimeConfig:
    basin_name: str
    base_output_dir: str
    soil_base: str
    global_base: str
    obs_file: str
    rout_template_dir: str
    vic_exe: str
    rout_exe: str
    start_year: int
    end_year: int
    flux_prefix: str = "huaihe_fluxes_"


def configure_runtime(cfg: RuntimeConfig) -> None:
    global BASIN_NAME, BASE_OUTPUT_DIR, SOIL_BASE, GLOBAL_BASE, OBS_FILE
    global ROUT_TEMPLATE_DIR, VIC_EXE, ROUT_EXE, OUTPUT_ROOT, CURRENT_DIR, BEST_DIR
    global START_YEAR, END_YEAR, FLUX_PREFIX

    BASIN_NAME = cfg.basin_name
    BASE_OUTPUT_DIR = cfg.base_output_dir
    SOIL_BASE = cfg.soil_base
    GLOBAL_BASE = cfg.global_base
    OBS_FILE = cfg.obs_file
    ROUT_TEMPLATE_DIR = cfg.rout_template_dir
    VIC_EXE = cfg.vic_exe
    ROUT_EXE = cfg.rout_exe
    START_YEAR = int(cfg.start_year)
    END_YEAR = int(cfg.end_year)
    FLUX_PREFIX = cfg.flux_prefix

    OUTPUT_ROOT = os.path.join(BASE_OUTPUT_DIR, f"{BASIN_NAME}_calibration_ai")
    CURRENT_DIR = os.path.join(OUTPUT_ROOT, "current_run")
    BEST_DIR = os.path.join(OUTPUT_ROOT, "best_run")


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def reset_dir(path: str) -> None:
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def read_obs(obs_path: str, start: dt.date, end: dt.date) -> Dict[dt.date, float]:
    obs = {}
    with open(obs_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            try:
                date_str = row.get("dates") or row.get("date")
                if not date_str:
                    continue
                y, m, d = [int(x) for x in date_str.split("-")]
                date = dt.date(y, m, d)
                if date < start or date > end:
                    continue
                q = float(row.get("Q"))
                if q < 0:
                    continue
                obs[date] = q
            except Exception:
                continue
    return obs


def read_sim_day(sim_path: str, start: dt.date, end: dt.date) -> Dict[dt.date, float]:
    sim = {}
    with open(sim_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            try:
                y = int(parts[0])
                m = int(parts[1])
                d = int(parts[2])
                val = float(parts[3])
            except Exception:
                continue
            date = dt.date(y, m, d)
            if start <= date <= end:
                sim[date] = val
    return sim


def compute_ratio(sim: List[float], obs: List[float], top_frac: float = 0.05, low: bool = False) -> float:
    if not sim or not obs:
        return float("nan")
    n = len(sim)
    k = max(1, int(n * top_frac))
    pairs = list(zip(sim, obs))
    pairs.sort(key=lambda x: x[1], reverse=not low)
    sel = pairs[:k]
    sim_mean = sum(p[0] for p in sel) / len(sel)
    obs_mean = sum(p[1] for p in sel) / len(sel)
    if obs_mean == 0:
        return float("nan")
    return sim_mean / obs_mean


def compute_metrics(obs: Dict[dt.date, float], sim: Dict[dt.date, float]) -> Tuple[float, float, float, float, float]:
    dates = sorted(set(obs.keys()) & set(sim.keys()))
    if not dates:
        return float("nan"), float("nan"), float("nan"), float("nan"), float("nan")

    o = [obs[d] for d in dates]
    s = [sim[d] for d in dates]

    mean_o = sum(o) / len(o)
    num = sum((s[i] - o[i]) ** 2 for i in range(len(o)))
    den = sum((o[i] - mean_o) ** 2 for i in range(len(o)))
    nse = 1.0 - num / den if den > 0 else float("nan")

    rmse = math.sqrt(sum((s[i] - o[i]) ** 2 for i in range(len(o))) / len(o))
    pbias = 100.0 * (sum(s) - sum(o)) / sum(o) if sum(o) != 0 else float("nan")
    peak_ratio = compute_ratio(s, o, top_frac=0.05)
    low_ratio = compute_ratio(s, o, top_frac=0.20, low=True)
    return nse, rmse, pbias, peak_ratio, low_ratio


def write_soil_params(src_path: str, dst_path: str, params: Dict[str, float]) -> None:
    with open(src_path, "r", encoding="utf-8", errors="ignore") as f_in, open(dst_path, "w", encoding="utf-8") as f_out:
        for line in f_in:
            parts = line.strip().split()
            if not parts:
                f_out.write(line)
                continue
            for key, idx in INDEX_MAP.items():
                parts[idx] = f"{params[key]:.3f}"
            f_out.write(" ".join(parts) + "\n")


def write_global_param(src_path: str, dst_path: str, soil_path: str, result_dir: str) -> None:
    with open(src_path, "r", encoding="utf-8", errors="ignore") as f_in, open(dst_path, "w", encoding="utf-8") as f_out:
        for line in f_in:
            stripped = line.strip()
            if stripped.startswith("SOIL"):
                f_out.write(f"SOIL                    {soil_path}\n")
            elif stripped.startswith("RESULT_DIR"):
                result_dir_use = result_dir if result_dir.endswith("/") else result_dir + "/"
                f_out.write(f"RESULT_DIR              {result_dir_use}\n")
            else:
                f_out.write(line)


def preprocess_vic_output(vic_dir: str, out_dir: str) -> None:
    ensure_dir(out_dir)
    for name in os.listdir(vic_dir):
        if not name.endswith(".txt") or name.startswith("._"):
            continue
        src_path = os.path.join(vic_dir, name)
        dst_path = os.path.join(out_dir, name[:-4])
        with open(src_path, "r", encoding="utf-8", errors="ignore") as f_in, open(dst_path, "w", encoding="utf-8") as f_out:
            for _ in range(3):
                next(f_in, None)
            for line in f_in:
                parts = line.strip().split()
                if len(parts) < 19:
                    continue
                out = [parts[0], parts[1], parts[2], parts[3], parts[18], parts[16], parts[17]]
                f_out.write("\t".join(out) + "\n")


def _find_first_by_suffix(files: List[str], suffix: str) -> str:
    for n in sorted(files):
        if n.endswith(suffix):
            return n
    return ""


def prepare_routing_dir(run_dir: str, vic_for_routing: str, routing_result: str, start_year: int, end_year: int) -> str:
    routing_dir = os.path.join(run_dir, "rout")
    ensure_dir(routing_dir)

    tmpl_files = [n for n in os.listdir(ROUT_TEMPLATE_DIR) if not n.startswith("._")]
    for fname in tmpl_files:
        src = os.path.join(ROUT_TEMPLATE_DIR, fname)
        dst = os.path.join(routing_dir, fname)
        if os.path.isfile(src):
            shutil.copyfile(src, dst)

    vic_link = os.path.join(routing_dir, "vic_in")
    rout_link = os.path.join(routing_dir, "rout_out")
    for link in [vic_link, rout_link]:
        if os.path.islink(link) or os.path.exists(link):
            try:
                os.unlink(link)
            except Exception:
                pass
    os.symlink(vic_for_routing, vic_link)
    os.symlink(routing_result, rout_link)

    global_candidates = [n for n in os.listdir(routing_dir) if n.endswith("rout_global.txt")]
    if not global_candidates:
        raise FileNotFoundError(f"rout_global.txt not found in template dir: {ROUT_TEMPLATE_DIR}")
    global_path = os.path.join(routing_dir, sorted(global_candidates)[0])

    routed_files = [n for n in os.listdir(routing_dir) if not n.startswith("._")]
    direc = _find_first_by_suffix(routed_files, "_direc.txt")
    veloc = _find_first_by_suffix(routed_files, "_veloc.txt")
    diff = _find_first_by_suffix(routed_files, "_diff.txt")
    xmask = _find_first_by_suffix(routed_files, "_xmask.txt")
    frac = _find_first_by_suffix(routed_files, "_frac.txt")
    staloc = _find_first_by_suffix(routed_files, "_staloc.txt")
    uh_all = "UH.all" if "UH.all" in routed_files else _find_first_by_suffix(routed_files, ".all")

    with open(global_path, "r", encoding="utf-8", errors="ignore") as f_in:
        lines = f_in.readlines()

    out_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.endswith("_direc.txt") and direc:
            out_lines.append(f"./{direc}\n")
        elif stripped.endswith("_veloc.txt") and veloc:
            out_lines.append(f"./{veloc}\n")
        elif stripped.endswith("_diff.txt") and diff:
            out_lines.append(f"./{diff}\n")
        elif stripped.endswith("_xmask.txt") and xmask:
            out_lines.append(f"./{xmask}\n")
        elif stripped.endswith("_frac.txt") and frac:
            out_lines.append(f"./{frac}\n")
        elif stripped.endswith("_staloc.txt") and staloc:
            out_lines.append(f"./{staloc}\n")
        elif stripped.endswith("_fluxes_"):
            out_lines.append(f"./vic_in/{FLUX_PREFIX}\n")
        elif stripped.endswith("/rout_out/") or stripped.endswith("./rout_out/"):
            out_lines.append("./rout_out/\n")
        elif (stripped == "./UH.all" or stripped.endswith("UH.all")) and uh_all:
            out_lines.append(f"./{uh_all}\n")
        else:
            out_lines.append(line)

    time_line = f"{start_year} 01 {end_year} 12\n"
    new_lines = []
    for line in out_lines:
        parts = line.strip().split()
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            new_lines.append(time_line)
        else:
            new_lines.append(line)

    with open(global_path, "w", encoding="utf-8") as f_out:
        f_out.writelines(new_lines)

    for n in os.listdir(routing_dir):
        if n.endswith(".uh_s") and os.path.isfile(os.path.join(routing_dir, n)):
            try:
                os.remove(os.path.join(routing_dir, n))
            except Exception:
                pass

    ensure_dir(routing_result)
    return routing_dir


def find_day_file(routing_result: str) -> str:
    candidates = []
    for name in os.listdir(routing_result):
        if name.startswith("._"):
            continue
        if name.endswith(".day") and not name.endswith("day_mm"):
            candidates.append(name)
    if not candidates:
        return ""
    candidates.sort()
    return os.path.join(routing_result, candidates[0])


def write_analysis(md_path: str, run_id: int, params: Dict[str, float], metrics: Dict[str, float], best_nse: float, best_run: int, decision: str) -> None:
    with open(md_path, "a", encoding="utf-8") as f:
        f.write(f"\n## Run {run_id} Analysis\n\n")
        f.write("### Current Results\n")
        f.write(f"- params: binfilt={params['binfilt']:.3f}, Ds={params['Ds']:.3f}, Dsmax={params['Dsmax']:.3f}, Ws={params['Ws']:.3f}, d2={params['soil_d2']:.3f}, d3={params['soil_d3']:.3f}\n")
        f.write(f"- NSE={metrics.get('NSE', float('nan')):.4f}, RMSE={metrics.get('RMSE', float('nan')):.4f}, PBIAS={metrics.get('PBIAS', float('nan')):.2f}%\n\n")
        f.write("### Best So Far\n")
        f.write(f"- best NSE={best_nse:.4f} (run {best_run})\n\n")
        f.write("### Next Decision\n")
        f.write(f"- {decision}\n")


def copy_best(src_dir: str, dst_dir: str) -> None:
    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir)


def run_vic_with_watchdog(run_id: int, global_path: str, log_path: str) -> bool:
    hard_timeout_sec = 4 * 3600
    poll_sec = 20
    heartbeat_sec = 60

    start = time.time()
    last_heartbeat = start
    proc = subprocess.Popen(
        [VIC_EXE, "-g", global_path],
        cwd=CURRENT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    while True:
        if proc.poll() is not None:
            break
        now = time.time()
        if now - last_heartbeat >= heartbeat_sec:
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"Run {run_id} VIC heartbeat: elapsed_sec={now - start:.0f}\n")
            last_heartbeat = now
        if time.time() - start > hard_timeout_sec:
            proc.kill()
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"Run {run_id} VIC timeout (> {hard_timeout_sec}s). Killed.\n")
            return False
        time.sleep(poll_sec)

    if proc.returncode != 0:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"Run {run_id} VIC failed. returncode={proc.returncode}\n")
        return False
    return True


def run_once(run_id: int, params: Dict[str, float], phase: str, log_path: str) -> Tuple[bool, Dict[str, float]]:
    reset_dir(CURRENT_DIR)

    vic_result = os.path.join(CURRENT_DIR, "vic_result")
    vic_for_routing = os.path.join(CURRENT_DIR, "vic_for_routing")
    routing_result = os.path.join(CURRENT_DIR, "routing_result")
    ensure_dir(vic_result)

    soil_path = os.path.join(CURRENT_DIR, "SOIL_PARAM_COMPLETE.txt")
    write_soil_params(SOIL_BASE, soil_path, params)

    global_path = os.path.join(CURRENT_DIR, "global_param.txt")
    write_global_param(GLOBAL_BASE, global_path, soil_path, vic_result)

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"Run {run_id} start: phase={phase}, params={params}\n")

    if not run_vic_with_watchdog(run_id, global_path, log_path):
        return False, {}

    preprocess_vic_output(vic_result, vic_for_routing)
    routing_dir = prepare_routing_dir(CURRENT_DIR, vic_for_routing, routing_result, START_YEAR, END_YEAR)

    rout_proc = subprocess.run([ROUT_EXE, "rout_global.txt"], cwd=routing_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if rout_proc.returncode != 0:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"Run {run_id} routing failed: {rout_proc.stderr}\n")
        return False, {}

    day_file = find_day_file(routing_result)
    if not day_file:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"Run {run_id} missing routing day file.\n")
        return False, {}

    start_date = dt.date(START_YEAR, 1, 1)
    end_date = dt.date(END_YEAR, 12, 31)
    obs = read_obs(OBS_FILE, start_date, end_date)
    sim = read_sim_day(day_file, start_date, end_date)
    nse, rmse, pbias, peak_ratio, low_ratio = compute_metrics(obs, sim)

    metrics = {
        "NSE": nse,
        "RMSE": rmse,
        "PBIAS": pbias,
        "peak_ratio": peak_ratio,
        "lowflow_ratio": low_ratio,
    }

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"Run {run_id} done: NSE={nse:.4f}, RMSE={rmse:.4f}, PBIAS={pbias:.2f}%\n")

    return True, metrics
