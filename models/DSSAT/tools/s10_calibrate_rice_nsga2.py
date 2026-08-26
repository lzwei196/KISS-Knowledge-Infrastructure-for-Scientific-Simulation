#!/usr/bin/env python3
"""
DSSAT CERES-Rice 双目标 NSGA-II 校准工具
===========================================
校准参数（文档范围）:
  P1   Basic vegetative phase GDD   150–800 °C·d   (默认 300)
  G1   Spikelet number coefficient   50–75  #/g    (默认 75)

固定参数（数值稳定性约束）:
  G2 = 0.030  (单粒重 g)  — CN0231 东北粳稻仅 0.020/0.030 两值稳定，
                            其余值导致 CERES-Rice 4.8 + IIRRI=A 数值发散（负产量）
  P5, P2O, P2R, G3, PHINT — 无观测表型期数据时不调整（低灵活性参数）
  THOT=28, TCLDP=14, TCLDF=14 — CN0231 东北低温适应值，保持不变

目标函数（两目标 Pareto 优化）:
  f1 = |PBIAS|   均值偏差绝对值 (%)，越小越好
  f2 = 1 − r    年际 Pearson 相关反转，越小越好

用法:
  # 单省模式（推荐，独立 Pareto 前沿）
  python s10_calibrate_rice_nsga2.py \\
    --province 黑龙江省 \\
    --grid_csv  ../../outputs/songliao_dssat_2000_2020/grid_cells_all_unified.csv \\
    --output    ../../outputs/songliao_dssat_2000_2020/calib_rice_nsga2_heilongjiang.csv \\
    [--n_gen 40] [--pop_size 30] [--n_cells 20] [--calib_years 2003,2007,2011,2015,2018]

  # 三省联合模式（f1 = 三省 PBIAS² 均值，f2 = 三省 r 均值）
  python s10_calibrate_rice_nsga2.py --province ALL ...

依赖: pymoo>=0.6, pandas, numpy, scipy, multiprocessing
"""
import argparse
import os
import shutil
import sys
import multiprocessing as mp
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))
from dssat_workdir_setup import create_workdir, run_dssat, parse_summary

# ── 固定路径 ─────────────────────────────────────────────────────
DSSAT_GEN  = Path("KISSPATH_HOME/DSSAT/Data/Genotype")
ORIG_CUL   = DSSAT_GEN / "RICER048.CUL"
KI_DIR     = Path(__file__).parent
DEFAULT_GRID_CSV   = KI_DIR / "../../../outputs/songliao_dssat_2000_2020/grid_cells_all_unified.csv"
DEFAULT_PROV_MAP   = KI_DIR / "../../../outputs/songliao_dssat_2000_2020/cell_province_map.csv"
DEFAULT_WTH_DIR    = KI_DIR / "../../../outputs/songliao_dssat_2000_2020/wth_files"
DEFAULT_SOIL_DIR   = KI_DIR / "../../../outputs/songliao_dssat_2000_2020/soil_files"

# ── 参数定义 ──────────────────────────────────────────────────────
PROVINCES_ALL = ['黑龙江省', '吉林省', '辽宁省']
G2_FIXED      = 0.030      # 数值稳定的唯一可用最大值

# ── 全局变量（worker 初始化用）────────────────────────────────────
_G_p1 = None
_G_g1 = None
_G_wth_dir   = None
_G_soil_dir  = None
_G_calib_years = None


# ═══════════════════════════════════════════════════════════════════
#  CUL 文件 patch（线程安全：每个 worker 写自己的临时 workdir CUL）
# ═══════════════════════════════════════════════════════════════════
def patch_cul_p1g1(cul_text: str, p1: float, g1: float) -> str:
    """替换 CN0231 行的 P1 和 G1，G2 保持 0.030 不变。"""
    for line in cul_text.split('\n'):
        if 'CN0231' in line and not line.startswith('!'):
            parts = line.split()
            new_line = (line
                        .replace(parts[6],  f'{p1:.1f}', 1)   # P1
                        .replace(parts[10], f'{g1:.1f}', 1))  # G1
            return cul_text.replace(line, new_line, 1)
    return cul_text


# ═══════════════════════════════════════════════════════════════════
#  Worker 初始化 + 单格点单年任务
# ═══════════════════════════════════════════════════════════════════
def _init_worker(p1, g1, wth_dir, soil_dir, calib_years):
    global _G_p1, _G_g1, _G_wth_dir, _G_soil_dir, _G_calib_years
    _G_p1 = p1; _G_g1 = g1
    _G_wth_dir = wth_dir; _G_soil_dir = soil_dir
    _G_calib_years = calib_years


def _run_cell_year(args):
    """返回 HWAM (kg/ha) 或 None（失败）。"""
    lon_c, lat_c, year = args
    lo = int(abs(lon_c) * 10) % 1000
    la = int(abs(lat_c) * 10) % 100
    wth_name = f"{lo:03d}{la:02d}"[:4].upper()
    wth  = str(Path(_G_wth_dir) / f"{wth_name}_{lon_c:.2f}_{lat_c:.2f}.WTH")
    sol  = str(Path(_G_soil_dir) / f"soil_{lon_c:.2f}_{lat_c:.2f}.SOL")
    if not (os.path.isfile(wth) and os.path.isfile(sol)):
        return None

    # 种植日期：lat > 44 每度推迟 2 天，上限 DOY 160（6月9日）
    pdoy = 130 + (max(0, lat_c - 44) * 2 if lat_c > 44 else 0)
    pdoy = min(int(pdoy), 160)
    pd_str = (pd.Timestamp(year, 1, 1) + pd.Timedelta(days=pdoy - 1)).strftime('%Y-%m-%d')

    soil_id = f"SNG{int(abs(lon_c)*10)%10000:04d}{int(abs(lat_c)*10)%10000:04d}"[:10]
    wd = f"/tmp/nsga2_{int(abs(lon_c)*100)}_{int(abs(lat_c)*100)}_{year}_{os.getpid()}"
    shutil.rmtree(wd, ignore_errors=True)

    # 读原始 CUL，patch，写入 workdir
    orig_cul = ORIG_CUL.read_text()
    patched  = patch_cul_p1g1(orig_cul, _G_p1, _G_g1)

    try:
        create_workdir(crop='RI', cultivar='CN0231',
                       weather_file=wth, soil_id=soil_id, soil_file=sol,
                       lat=lat_c, lon=lon_c,
                       planting_date=pd_str,
                       start_year=year, end_year=year,
                       output_dir=wd)
        # 替换 workdir 内的 CUL（解除软链）
        for sub in [wd, os.path.join(wd, 'Genotype')]:
            cul_path = os.path.join(sub, "RICER048.CUL")
            if os.path.lexists(cul_path):
                if os.path.islink(cul_path):
                    os.unlink(cul_path)
                open(cul_path, 'w').write(patched)

        res = run_dssat(wd)
        if not res.get('success'):
            return None
        for r in parse_summary(wd):
            if r.get('WYEAR') and int(r['WYEAR']) == year:
                v = float(r.get('HWAM', 0) or 0)
                return v if v > 0 else None
    except Exception:
        return None
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════
#  省级目标函数评估
# ═══════════════════════════════════════════════════════════════════
def evaluate_province(p1: float, g1: float,
                      cells: list,           # [(lon_c, lat_c), ...]
                      yearbook: dict,        # {year: obs_yield}
                      calib_years: list,
                      wth_dir: str,
                      soil_dir: str,
                      n_workers: int = 24) -> dict:
    """
    返回 {'pbias': float, 'r': float, 'sim_mean': float, 'n_valid': int}
    失败时返回 {'pbias': 999, 'r': 0, 'sim_mean': 0, 'n_valid': 0}
    """
    tasks = [(lon_c, lat_c, yr) for lon_c, lat_c in cells for yr in calib_years]

    with mp.Pool(n_workers,
                 initializer=_init_worker,
                 initargs=(p1, g1, wth_dir, soil_dir, calib_years)) as pool:
        results = pool.map(_run_cell_year, tasks, chunksize=4)

    # 按年聚合：每年所有格点的均值
    yr_sim = {}
    for (lon_c, lat_c, yr), v in zip(tasks, results):
        if v is not None and v > 0:
            yr_sim.setdefault(yr, []).append(v)

    sim_by_year = {yr: np.mean(vals) for yr, vals in yr_sim.items() if vals}
    common_yrs  = sorted(set(sim_by_year) & set(yearbook))

    if len(common_yrs) < 2:
        return {'pbias': 999.0, 'r': 0.0, 'sim_mean': 0.0, 'n_valid': 0}

    sim_arr = np.array([sim_by_year[y] for y in common_yrs])
    obs_arr = np.array([yearbook[y]    for y in common_yrs])

    sim_mean = float(np.mean(sim_arr))
    obs_mean = float(np.mean(obs_arr))
    pbias    = (sim_mean - obs_mean) / obs_mean * 100 if obs_mean else 999.0
    r_val, _ = stats.pearsonr(sim_arr, obs_arr)

    return {'pbias': pbias, 'r': float(r_val), 'sim_mean': sim_mean, 'n_valid': len(common_yrs)}


# ═══════════════════════════════════════════════════════════════════
#  NSGA-II 适应度问题类
# ═══════════════════════════════════════════════════════════════════
def _build_nsga2_problem(cells, yearbook, calib_years, wth_dir, soil_dir,
                          n_workers, progress_cb=None):
    """工厂函数，返回 pymoo Problem 子类实例。"""
    from pymoo.core.problem import ElementwiseProblem

    class RiceCalibProblem(ElementwiseProblem):
        _eval_count = 0

        def __init__(self):
            super().__init__(
                n_var=2,
                n_obj=2,
                n_constr=0,
                xl=np.array([150.0, 50.0]),   # [P1_min, G1_min]
                xu=np.array([800.0, 75.0]),    # [P1_max, G1_max]
            )

        def _evaluate(self, x, out, *args, **kwargs):
            p1, g1 = float(x[0]), float(x[1])
            res = evaluate_province(p1, g1, cells, yearbook, calib_years,
                                    wth_dir, soil_dir, n_workers)
            f1 = abs(res['pbias'])   # |PBIAS| → min
            f2 = 1.0 - max(-1.0, min(1.0, res['r']))   # 1-r → min
            out['F'] = [f1, f2]
            RiceCalibProblem._eval_count += 1
            if progress_cb:
                progress_cb(RiceCalibProblem._eval_count, p1, g1, res)

    return RiceCalibProblem()


# ═══════════════════════════════════════════════════════════════════
#  主函数
# ═══════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description='DSSAT CERES-Rice NSGA-II 校准（P1×G1）')
    ap.add_argument('--province',    default='ALL',
                    help='省名（黑龙江省/吉林省/辽宁省/ALL）')
    ap.add_argument('--grid_csv',    default=str(DEFAULT_GRID_CSV))
    ap.add_argument('--prov_map',    default=str(DEFAULT_PROV_MAP))
    ap.add_argument('--wth_dir',     default=str(DEFAULT_WTH_DIR))
    ap.add_argument('--soil_dir',    default=str(DEFAULT_SOIL_DIR))
    ap.add_argument('--output',      required=True, help='结果 CSV 路径')
    ap.add_argument('--n_gen',       type=int, default=40, help='NSGA-II 迭代代数')
    ap.add_argument('--pop_size',    type=int, default=30, help='NSGA-II 种群规模')
    ap.add_argument('--n_cells',     type=int, default=20, help='每省样本格点数')
    ap.add_argument('--n_workers',   type=int, default=24, help='并行 DSSAT 进程数')
    ap.add_argument('--calib_years', default='2003,2007,2011,2015,2018',
                    help='校准年份（逗号分隔）')
    args = ap.parse_args()

    calib_years = [int(y) for y in args.calib_years.split(',')]
    print(f"校准年份: {calib_years}")
    print(f"NSGA-II: pop={args.pop_size}  gen={args.n_gen}")
    print(f"G2 固定: {G2_FIXED}  |  P1 范围: 150–800  |  G1 范围: 50–75")

    # ── 读格点（province 列已在 grid CSV 中）────────────────────────
    grid = pd.read_csv(args.grid_csv)
    if 'province' not in grid.columns and os.path.isfile(args.prov_map):
        pmap = pd.read_csv(args.prov_map)
        grid = grid.merge(pmap, on=['lon_c', 'lat_c'], how='left')

    # ── 读年鉴产量（kg/ha）────────────────────────────────────────
    import sqlite3
    DB = 'KISSPATH_OUTPUTS/yearbook_catalog/yearbook.db'
    conn = sqlite3.connect(DB)
    df_yk = pd.read_sql("SELECT * FROM 综合统计_国家局分省长面板", conn)
    conn.close()
    yr_cols = [c for c in df_yk.columns if str(c).isdigit() and 2000 <= int(c) <= 2024]

    def load_yearbook(province):
        sub = df_yk[(df_yk['指标名称'] == '稻谷单位面积产量') & (df_yk['地区'] == province)]
        if sub.empty:
            return {}
        row = sub.iloc[0]
        return {int(y): float(row[y]) for y in yr_cols
                if y in row.index and pd.notna(row[y]) and float(row[y]) > 0}

    # ── 决定省份列表 ─────────────────────────────────────────────
    provinces = PROVINCES_ALL if args.province == 'ALL' else [args.province]

    all_results = []

    for province in provinces:
        print(f"\n{'='*60}")
        print(f"省份: {province}")

        # 格点：取水稻面积最大的 N 个
        prov_cells = grid[grid['province'] == province].copy()
        rice_col = next((c for c in ['spam_rice_ha', 'area_rice', 'rice_ha']
                         if c in prov_cells.columns), None)
        if rice_col:
            prov_cells = prov_cells.nlargest(args.n_cells, rice_col)
        else:
            prov_cells = prov_cells.head(args.n_cells)
        cells = list(prov_cells[['lon_c', 'lat_c']].itertuples(index=False, name=None))
        print(f"样本格点: {len(cells)}  校准年份: {len(calib_years)}")

        yearbook = load_yearbook(province)
        yk_mean  = np.mean(list(yearbook.values())) if yearbook else 0
        print(f"年鉴均值: {yk_mean:.0f} kg/ha  ({min(yearbook)} – {max(yearbook)})")

        if not cells or not yearbook:
            print("⚠️  无格点或无年鉴数据，跳过")
            continue

        # ── 进度回调 ──────────────────────────────────────────────
        _progress_store = []

        def progress_cb(count, p1, g1, res):
            _progress_store.append({
                'province': province, 'eval': count,
                'P1': round(p1, 1), 'G1': round(g1, 1), 'G2': G2_FIXED,
                'pbias': round(res['pbias'], 2),
                'r': round(res['r'], 4),
                'sim_mean': round(res['sim_mean'], 1),
                'n_valid': res['n_valid'],
            })
            if count % 10 == 0 or count <= 3:
                print(f"  eval {count:4d}  P1={p1:.0f}  G1={g1:.0f}  "
                      f"|PBIAS|={abs(res['pbias']):.1f}%  r={res['r']:.3f}  "
                      f"sim={res['sim_mean']:.0f} kg/ha")

        # ── NSGA-II ───────────────────────────────────────────────
        from pymoo.algorithms.moo.nsga2 import NSGA2
        from pymoo.operators.crossover.sbx import SBX
        from pymoo.operators.mutation.pm import PM
        from pymoo.optimize import minimize
        from pymoo.termination import get_termination

        problem = _build_nsga2_problem(cells, yearbook, calib_years,
                                        args.wth_dir, args.soil_dir,
                                        args.n_workers, progress_cb)

        algorithm = NSGA2(
            pop_size=args.pop_size,
            crossover=SBX(prob=0.9, eta=15),
            mutation=PM(eta=20),
            eliminate_duplicates=True,
        )
        termination = get_termination('n_gen', args.n_gen)

        print(f"启动 NSGA-II…")
        res_nsga = minimize(problem, algorithm, termination,
                            seed=42, verbose=False)

        # ── 汇总 Pareto 前沿 ──────────────────────────────────────
        pareto = pd.DataFrame(_progress_store)
        if not pareto.empty:
            # 筛选 |PBIAS| < 20% 且 r > 0.5 的解
            pareto_front = pareto[(pareto['pbias'].abs() < 20) & (pareto['r'] > 0.5)]
            if pareto_front.empty:
                pareto_front = pareto

            # 按 |PBIAS| + (1-r) 综合排序，取最优
            pareto_front = pareto_front.copy()
            pareto_front['score'] = (pareto_front['pbias'].abs() / 20 +
                                     (1 - pareto_front['r']))
            best = pareto_front.nsmallest(1, 'score').iloc[0]
            print(f"\n  ▶ 最优解: P1={best['P1']:.0f}  G1={best['G1']:.0f}  "
                  f"|PBIAS|={abs(best['pbias']):.1f}%  r={best['r']:.3f}")
            print(f"           模拟均值={best['sim_mean']:.0f} kg/ha  "
                  f"年鉴均值≈{yk_mean:.0f} kg/ha")
            all_results.extend(pareto.to_dict('records'))

    # ── 保存结果 ─────────────────────────────────────────────────
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(all_results).to_csv(out_path, index=False)
    print(f"\n结果已保存: {out_path}")

    # ── 打印汇总最优参数 ─────────────────────────────────────────
    print(f"\n{'='*60}")
    print("最终推荐参数（|PBIAS|+r 综合最优）:")
    if all_results:
        df_all = pd.DataFrame(all_results)
        df_all['score'] = df_all['pbias'].abs() / 20 + (1 - df_all['r'])
        for prov in provinces:
            sub = df_all[df_all['province'] == prov]
            if sub.empty:
                continue
            best = sub.nsmallest(1, 'score').iloc[0]
            print(f"  {prov}: P1={best['P1']:.0f}  G1={best['G1']:.0f}  "
                  f"G2={G2_FIXED}  |PBIAS|={abs(best['pbias']):.1f}%  r={best['r']:.3f}")


if __name__ == '__main__':
    main()
