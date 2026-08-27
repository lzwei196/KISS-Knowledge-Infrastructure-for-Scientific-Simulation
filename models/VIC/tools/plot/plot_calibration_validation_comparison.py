#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
率定期与验证期流量过程对比图
Calibration vs Validation Period Discharge Comparison Plot

功能：
- 绘制观测与模拟流量的全时段对比（三条曲线：观测、率定前、率定后）
- 用竖线分隔率定期和验证期
- 显示率定前后两条模拟曲线的对比
- 分别计算率定期和验证期的评价指标（含率定前后对比）

用法 / Usage:
    python plot_calibration_validation_comparison.py \
        --obs <观测文件> \
        --sim_cali <率定后模拟文件(率定期)> \
        --sim_vali <率定后模拟文件(验证期)> \
        --sim_uncali_cali <未率定模拟文件(率定期)> \
        --sim_uncali_vali <未率定模拟文件(验证期)> \
        --cali_start <率定起始年> --cali_end <率定结束年> \
        --vali_start <验证起始年> --vali_end <验证结束年> \
        --output <输出图片路径> \
        --title <图标题>
"""

import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 设置字体
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


def calc_nse(obs, sim):
    """计算Nash-Sutcliffe效率系数"""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    obs_valid, sim_valid = obs[mask], sim[mask]
    if len(obs_valid) == 0:
        return np.nan
    obs_mean = np.mean(obs_valid)
    numerator = np.sum((obs_valid - sim_valid) ** 2)
    denominator = np.sum((obs_valid - obs_mean) ** 2)
    if denominator == 0:
        return np.nan
    return 1 - numerator / denominator


def calc_kge(obs, sim):
    """计算Kling-Gupta效率系数"""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    obs_valid, sim_valid = obs[mask], sim[mask]
    if len(obs_valid) == 0:
        return np.nan
    r = np.corrcoef(obs_valid, sim_valid)[0, 1]
    alpha = np.std(sim_valid) / np.std(obs_valid) if np.std(obs_valid) != 0 else 1.0
    beta = np.mean(sim_valid) / np.mean(obs_valid) if np.mean(obs_valid) != 0 else 1.0
    return 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def calc_rmse(obs, sim):
    """计算均方根误差"""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    obs_valid, sim_valid = obs[mask], sim[mask]
    if len(obs_valid) == 0:
        return np.nan
    return np.sqrt(np.mean((obs_valid - sim_valid) ** 2))


def calc_pbias(obs, sim):
    """计算百分比偏差"""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    obs_valid, sim_valid = obs[mask], sim[mask]
    if len(obs_valid) == 0 or np.sum(obs_valid) == 0:
        return np.nan
    return 100 * np.sum(sim_valid - obs_valid) / np.sum(obs_valid)


def calc_r(obs, sim):
    """计算相关系数"""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    obs_valid, sim_valid = obs[mask], sim[mask]
    if len(obs_valid) == 0:
        return np.nan
    return np.corrcoef(obs_valid, sim_valid)[0, 1]


def read_obs_data(filepath):
    """读取观测数据文件"""
    encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin-1']
    df = None
    for enc in encodings:
        try:
            df = pd.read_csv(filepath, sep='\t', encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if df is None:
        raise ValueError(f"无法读取文件 {filepath}")

    df['dates'] = pd.to_datetime(df['dates'])
    df = df.rename(columns={'Q': 'obs_Q'})
    df = df[['dates', 'obs_Q']].copy()
    df = df.set_index('dates')
    return df


def read_sim_data(filepath):
    """读取模拟数据文件"""
    df = pd.read_csv(filepath, sep=r'\s+', header=None,
                     names=['year', 'month', 'day', 'sim_Q'])
    df['dates'] = pd.to_datetime(df[['year', 'month', 'day']])
    df = df[['dates', 'sim_Q']].copy()
    df = df.set_index('dates')
    return df


def calculate_metrics(obs, sim):
    """计算所有评价指标"""
    return {
        'NSE': calc_nse(obs, sim),
        'KGE': calc_kge(obs, sim),
        'R': calc_r(obs, sim),
        'PBIAS': calc_pbias(obs, sim),
        'RMSE': calc_rmse(obs, sim)
    }


def plot_comparison(obs_df, sim_cali_df, sim_vali_df, sim_uncali_cali_df, sim_uncali_vali_df,
                    cali_start, cali_end, vali_start, vali_end,
                    output_path, title=None):
    """
    绘制率定期与验证期流量过程对比图（三条曲线：观测、率定前、率定后）
    """
    # 合并数据
    # 率定期数据
    cali_start_date = f'{cali_start}-01-01'
    cali_end_date = f'{cali_end}-12-31'

    obs_cali = obs_df.loc[cali_start_date:cali_end_date].copy()
    sim_cali = sim_cali_df.loc[cali_start_date:cali_end_date].copy()
    sim_uncali_cali = sim_uncali_cali_df.loc[cali_start_date:cali_end_date].copy()
    sim_uncali_cali = sim_uncali_cali.rename(columns={'sim_Q': 'sim_uncali_Q'})

    merged_cali = pd.merge(obs_cali, sim_cali, left_index=True, right_index=True, how='inner')
    merged_cali = pd.merge(merged_cali, sim_uncali_cali, left_index=True, right_index=True, how='inner')
    merged_cali = merged_cali[merged_cali['obs_Q'] >= 0]
    merged_cali = merged_cali.rename(columns={'sim_Q': 'sim_cali_Q'})

    # 验证期数据
    vali_start_date = f'{vali_start}-01-01'
    vali_end_date = f'{vali_end}-12-31'

    obs_vali = obs_df.loc[vali_start_date:vali_end_date].copy()
    sim_vali = sim_vali_df.loc[vali_start_date:vali_end_date].copy()
    sim_uncali_vali = sim_uncali_vali_df.loc[vali_start_date:vali_end_date].copy()
    sim_uncali_vali = sim_uncali_vali.rename(columns={'sim_Q': 'sim_uncali_Q'})

    merged_vali = pd.merge(obs_vali, sim_vali, left_index=True, right_index=True, how='inner')
    merged_vali = pd.merge(merged_vali, sim_uncali_vali, left_index=True, right_index=True, how='inner')
    merged_vali = merged_vali[merged_vali['obs_Q'] >= 0]
    merged_vali = merged_vali.rename(columns={'sim_Q': 'sim_vali_Q'})

    # 计算评价指标
    # 率定期 - 率定后
    metrics_cali_calibrated = calculate_metrics(
        merged_cali['obs_Q'].values,
        merged_cali['sim_cali_Q'].values
    )

    # 率定期 - 未率定
    metrics_cali_uncalibrated = calculate_metrics(
        merged_cali['obs_Q'].values,
        merged_cali['sim_uncali_Q'].values
    )

    # 验证期 - 率定后
    metrics_vali_calibrated = calculate_metrics(
        merged_vali['obs_Q'].values,
        merged_vali['sim_vali_Q'].values
    )

    # 验证期 - 未率定
    metrics_vali_uncalibrated = calculate_metrics(
        merged_vali['obs_Q'].values,
        merged_vali['sim_uncali_Q'].values
    )

    # 创建图形
    fig, ax = plt.subplots(figsize=(16, 8))

    # 绘制率定期数据（三条曲线）
    ax.plot(merged_cali.index, merged_cali['obs_Q'], 'b-', linewidth=1.0,
            label='Observed', alpha=0.9)
    ax.plot(merged_cali.index, merged_cali['sim_uncali_Q'], 'g-', linewidth=0.8,
            label='Simulated (Before Calibration)', alpha=0.7)
    ax.plot(merged_cali.index, merged_cali['sim_cali_Q'], 'r-', linewidth=0.8,
            label='Simulated (After Calibration)', alpha=0.8)

    # 绘制验证期数据（三条曲线，不重复添加图例）
    ax.plot(merged_vali.index, merged_vali['obs_Q'], 'b-', linewidth=1.0, alpha=0.9)
    ax.plot(merged_vali.index, merged_vali['sim_uncali_Q'], 'g-', linewidth=0.8, alpha=0.7)
    ax.plot(merged_vali.index, merged_vali['sim_vali_Q'], 'r-', linewidth=0.8, alpha=0.8)

    # 绘制分隔线
    split_date = pd.Timestamp(f'{cali_end}-12-31') + pd.Timedelta(days=1)
    ax.axvline(x=split_date, color='black', linestyle='--', linewidth=2,
               label='Calibration/Validation Split')

    # 添加背景色区分
    ax.axvspan(merged_cali.index.min(), split_date, alpha=0.08, color='blue')
    ax.axvspan(split_date, merged_vali.index.max(), alpha=0.08, color='green')

    # 获取y轴范围用于放置标签
    ymin, ymax = ax.get_ylim()

    # 添加期间标签
    ax.text(merged_cali.index.min() + (split_date - merged_cali.index.min())/2,
            ymax * 0.95, 'Calibration Period',
            ha='center', va='top', fontsize=12, fontweight='bold', color='darkblue')
    ax.text(split_date + (merged_vali.index.max() - split_date)/2,
            ymax * 0.95, 'Validation Period',
            ha='center', va='top', fontsize=12, fontweight='bold', color='darkgreen')

    # 设置坐标轴
    ax.set_ylabel('Discharge (m³/s)', fontsize=12)
    ax.set_xlabel('Date', fontsize=12)

    if title:
        ax.set_title(title, fontsize=14)
    else:
        ax.set_title(f'Discharge Comparison: Calibration ({cali_start}-{cali_end}) vs Validation ({vali_start}-{vali_end})',
                    fontsize=14)

    ax.legend(loc='upper center', fontsize=10, ncol=4)
    ax.grid(True, alpha=0.3)

    # 格式化x轴
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

    # 添加率定期评价指标（左上角）- 对比表格形式
    metrics_text_cali = (
        f'Calibration Period ({cali_start}-{cali_end})\n'
        f'─────────────────────────\n'
        f'{"Metric":<8} {"Before":>8} {"After":>8}\n'
        f'{"NSE":<8} {metrics_cali_uncalibrated["NSE"]:>8.3f} {metrics_cali_calibrated["NSE"]:>8.3f}\n'
        f'{"KGE":<8} {metrics_cali_uncalibrated["KGE"]:>8.3f} {metrics_cali_calibrated["KGE"]:>8.3f}\n'
        f'{"R":<8} {metrics_cali_uncalibrated["R"]:>8.3f} {metrics_cali_calibrated["R"]:>8.3f}\n'
        f'{"PBIAS%":<8} {metrics_cali_uncalibrated["PBIAS"]:>8.1f} {metrics_cali_calibrated["PBIAS"]:>8.1f}\n'
        f'{"RMSE":<8} {metrics_cali_uncalibrated["RMSE"]:>8.1f} {metrics_cali_calibrated["RMSE"]:>8.1f}'
    )

    props_cali = dict(boxstyle='round', facecolor='lightblue', alpha=0.85)
    ax.text(0.02, 0.98, metrics_text_cali, transform=ax.transAxes, fontsize=9,
            verticalalignment='top', bbox=props_cali, family='monospace')

    # 添加验证期评价指标（右上角）- 对比表格形式
    metrics_text_vali = (
        f'Validation Period ({vali_start}-{vali_end})\n'
        f'─────────────────────────\n'
        f'{"Metric":<8} {"Before":>8} {"After":>8}\n'
        f'{"NSE":<8} {metrics_vali_uncalibrated["NSE"]:>8.3f} {metrics_vali_calibrated["NSE"]:>8.3f}\n'
        f'{"KGE":<8} {metrics_vali_uncalibrated["KGE"]:>8.3f} {metrics_vali_calibrated["KGE"]:>8.3f}\n'
        f'{"R":<8} {metrics_vali_uncalibrated["R"]:>8.3f} {metrics_vali_calibrated["R"]:>8.3f}\n'
        f'{"PBIAS%":<8} {metrics_vali_uncalibrated["PBIAS"]:>8.1f} {metrics_vali_calibrated["PBIAS"]:>8.1f}\n'
        f'{"RMSE":<8} {metrics_vali_uncalibrated["RMSE"]:>8.1f} {metrics_vali_calibrated["RMSE"]:>8.1f}'
    )

    props_vali = dict(boxstyle='round', facecolor='lightgreen', alpha=0.85)
    ax.text(0.98, 0.98, metrics_text_vali, transform=ax.transAxes, fontsize=9,
            verticalalignment='top', horizontalalignment='right',
            bbox=props_vali, family='monospace')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    # 打印统计信息
    print(f"\n{'='*70}")
    print(f"率定期与验证期流量对比分析报告")
    print(f"{'='*70}")
    print(f"\n率定期: {cali_start}-{cali_end} ({len(merged_cali)}天)")
    print(f"验证期: {vali_start}-{vali_end} ({len(merged_vali)}天)")

    print(f"\n{'─'*70}")
    print(f"率定期评价指标:")
    print(f"{'─'*70}")
    print(f"{'指标':<10} {'率定前':>12} {'率定后':>12} {'提升':>12}")
    print(f"{'NSE':<10} {metrics_cali_uncalibrated['NSE']:>12.4f} {metrics_cali_calibrated['NSE']:>12.4f} {metrics_cali_calibrated['NSE']-metrics_cali_uncalibrated['NSE']:>+12.4f}")
    print(f"{'KGE':<10} {metrics_cali_uncalibrated['KGE']:>12.4f} {metrics_cali_calibrated['KGE']:>12.4f} {metrics_cali_calibrated['KGE']-metrics_cali_uncalibrated['KGE']:>+12.4f}")
    print(f"{'R':<10} {metrics_cali_uncalibrated['R']:>12.4f} {metrics_cali_calibrated['R']:>12.4f} {metrics_cali_calibrated['R']-metrics_cali_uncalibrated['R']:>+12.4f}")
    print(f"{'PBIAS(%)':<10} {metrics_cali_uncalibrated['PBIAS']:>12.2f} {metrics_cali_calibrated['PBIAS']:>12.2f} {abs(metrics_cali_calibrated['PBIAS'])-abs(metrics_cali_uncalibrated['PBIAS']):>+12.2f}")
    print(f"{'RMSE':<10} {metrics_cali_uncalibrated['RMSE']:>12.2f} {metrics_cali_calibrated['RMSE']:>12.2f} {metrics_cali_calibrated['RMSE']-metrics_cali_uncalibrated['RMSE']:>+12.2f}")

    print(f"\n{'─'*70}")
    print(f"验证期评价指标:")
    print(f"{'─'*70}")
    print(f"{'指标':<10} {'率定前':>12} {'率定后':>12} {'提升':>12}")
    print(f"{'NSE':<10} {metrics_vali_uncalibrated['NSE']:>12.4f} {metrics_vali_calibrated['NSE']:>12.4f} {metrics_vali_calibrated['NSE']-metrics_vali_uncalibrated['NSE']:>+12.4f}")
    print(f"{'KGE':<10} {metrics_vali_uncalibrated['KGE']:>12.4f} {metrics_vali_calibrated['KGE']:>12.4f} {metrics_vali_calibrated['KGE']-metrics_vali_uncalibrated['KGE']:>+12.4f}")
    print(f"{'R':<10} {metrics_vali_uncalibrated['R']:>12.4f} {metrics_vali_calibrated['R']:>12.4f} {metrics_vali_calibrated['R']-metrics_vali_uncalibrated['R']:>+12.4f}")
    print(f"{'PBIAS(%)':<10} {metrics_vali_uncalibrated['PBIAS']:>12.2f} {metrics_vali_calibrated['PBIAS']:>12.2f} {abs(metrics_vali_calibrated['PBIAS'])-abs(metrics_vali_uncalibrated['PBIAS']):>+12.2f}")
    print(f"{'RMSE':<10} {metrics_vali_uncalibrated['RMSE']:>12.2f} {metrics_vali_calibrated['RMSE']:>12.2f} {metrics_vali_calibrated['RMSE']-metrics_vali_uncalibrated['RMSE']:>+12.2f}")

    print(f"\n图片已保存至: {output_path}")
    print(f"{'='*70}\n")

    return {
        'cali_calibrated': metrics_cali_calibrated,
        'cali_uncalibrated': metrics_cali_uncalibrated,
        'vali_calibrated': metrics_vali_calibrated,
        'vali_uncalibrated': metrics_vali_uncalibrated
    }


def main():
    parser = argparse.ArgumentParser(description='率定期与验证期流量过程对比图（三条曲线：观测、率定前、率定后）')
    parser.add_argument('--obs', type=str, required=True, help='观测数据文件路径')
    parser.add_argument('--sim_cali', type=str, required=True, help='率定后模拟文件(率定期)')
    parser.add_argument('--sim_vali', type=str, required=True, help='率定后模拟文件(验证期)')
    parser.add_argument('--sim_uncali_cali', type=str, required=True, help='未率定模拟文件(率定期)')
    parser.add_argument('--sim_uncali_vali', type=str, required=True, help='未率定模拟文件(验证期)')
    parser.add_argument('--cali_start', type=int, required=True, help='率定期起始年')
    parser.add_argument('--cali_end', type=int, required=True, help='率定期结束年')
    parser.add_argument('--vali_start', type=int, required=True, help='验证期起始年')
    parser.add_argument('--vali_end', type=int, required=True, help='验证期结束年')
    parser.add_argument('--output', type=str, default='cali_vali_comparison.png', help='输出图片路径')
    parser.add_argument('--title', type=str, default=None, help='图表标题')

    args = parser.parse_args()

    # 读取数据
    print(f"读取观测数据: {args.obs}")
    obs_df = read_obs_data(args.obs)

    print(f"读取率定后模拟数据(率定期): {args.sim_cali}")
    sim_cali_df = read_sim_data(args.sim_cali)

    print(f"读取率定后模拟数据(验证期): {args.sim_vali}")
    sim_vali_df = read_sim_data(args.sim_vali)

    print(f"读取未率定模拟数据(率定期): {args.sim_uncali_cali}")
    sim_uncali_cali_df = read_sim_data(args.sim_uncali_cali)

    print(f"读取未率定模拟数据(验证期): {args.sim_uncali_vali}")
    sim_uncali_vali_df = read_sim_data(args.sim_uncali_vali)

    # 绘图
    plot_comparison(obs_df, sim_cali_df, sim_vali_df, sim_uncali_cali_df, sim_uncali_vali_df,
                    args.cali_start, args.cali_end,
                    args.vali_start, args.vali_end,
                    args.output, args.title)


if __name__ == '__main__':
    main()
