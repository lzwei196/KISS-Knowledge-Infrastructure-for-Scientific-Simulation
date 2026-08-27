#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
流量模拟结果与观测数据对比绘图脚本
Discharge Comparison Plot: Observed vs Simulated

用法 / Usage:
    python plot_discharge_comparison.py --obs <观测文件> --sim <模拟文件>
           --start <起始年> --end <结束年> --output <输出图片路径>
"""

import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


def calc_nse(obs, sim):
    """计算Nash-Sutcliffe效率系数 (NSE)"""
    obs_mean = np.mean(obs)
    numerator = np.sum((obs - sim) ** 2)
    denominator = np.sum((obs - obs_mean) ** 2)
    if denominator == 0:
        return np.nan
    return 1 - numerator / denominator


def calc_kge(obs, sim):
    """计算Kling-Gupta效率系数 (KGE)"""
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    kge = 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return kge


def calc_r(obs, sim):
    """计算皮尔逊相关系数 (R)"""
    return np.corrcoef(obs, sim)[0, 1]


def calc_pbias(obs, sim):
    """计算百分比偏差 (PBIAS, %)"""
    return 100 * np.sum(sim - obs) / np.sum(obs)


def calc_mae(obs, sim):
    """计算平均绝对误差 (MAE)"""
    return np.mean(np.abs(obs - sim))


def calc_rmse(obs, sim):
    """计算均方根误差 (RMSE)"""
    return np.sqrt(np.mean((obs - sim) ** 2))


def read_obs_data(filepath):
    """
    读取观测数据文件
    格式: stcd  dates  z  Q  name (制表符分隔，有表头)
    """
    # 尝试多种编码
    encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin-1']
    df = None
    for enc in encodings:
        try:
            df = pd.read_csv(filepath, sep='\t', encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if df is None:
        raise ValueError(f"无法读取文件 {filepath}，请检查文件编码")

    df['dates'] = pd.to_datetime(df['dates'])
    df = df.rename(columns={'Q': 'obs_Q'})
    df = df[['dates', 'obs_Q']].copy()
    df = df.set_index('dates')
    return df


def read_sim_data(filepath):
    """
    读取模拟数据文件 (Routing输出)
    格式: year month day discharge (空格分隔，无表头)
    """
    df = pd.read_csv(filepath, sep=r'\s+', header=None,
                     names=['year', 'month', 'day', 'sim_Q'])
    df['dates'] = pd.to_datetime(df[['year', 'month', 'day']])
    df = df[['dates', 'sim_Q']].copy()
    df = df.set_index('dates')
    return df


def plot_comparison(obs_df, sim_df, start_year, end_year, output_path, station_name='', param_text=''):
    """
    绘制观测与模拟流量对比图
    """
    # 合并数据
    merged = pd.merge(obs_df, sim_df, left_index=True, right_index=True, how='inner')

    # 筛选时间范围
    start_date = f'{start_year}-01-01'
    end_date = f'{end_year}-12-31'
    merged = merged.loc[start_date:end_date]

    if len(merged) == 0:
        print(f"错误：在{start_year}-{end_year}时间范围内没有重叠数据！")
        print(f"观测数据范围: {obs_df.index.min()} 至 {obs_df.index.max()}")
        print(f"模拟数据范围: {sim_df.index.min()} 至 {sim_df.index.max()}")
        return

    # 剔除观测流量小于0的数据（通常表示缺测或异常）
    total_before_filter = len(merged)
    merged = merged[merged['obs_Q'] >= 0]
    removed_count = total_before_filter - len(merged)
    if removed_count > 0:
        print(f"  已剔除观测流量<0的数据: {removed_count} 条")

    if len(merged) == 0:
        print(f"错误：剔除负值后没有有效数据！")
        return

    obs = merged['obs_Q'].values
    sim = merged['sim_Q'].values

    # 计算评价指标
    nse = calc_nse(obs, sim)
    kge = calc_kge(obs, sim)
    r = calc_r(obs, sim)
    pbias = calc_pbias(obs, sim)
    mae = calc_mae(obs, sim)
    rmse = calc_rmse(obs, sim)

    # 创建图形
    fig, axes = plt.subplots(2, 1, figsize=(14, 10),
                              gridspec_kw={'height_ratios': [3, 1]})

    # 上图：时间序列对比
    ax1 = axes[0]
    ax1.plot(merged.index, obs, 'b-', linewidth=0.8, label='Observed', alpha=0.8)
    ax1.plot(merged.index, sim, 'r-', linewidth=0.8, label='Simulated', alpha=0.8)
    ax1.set_ylabel('Discharge (m³/s)', fontsize=12)
    ax1.set_title(f'Discharge Comparison: {station_name} ({start_year}-{end_year})', fontsize=14)
    ax1.legend(loc='upper right', fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(merged.index.min(), merged.index.max())

    # 格式化x轴日期
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

    # 添加评价指标文本框
    metrics_text = (
        f'NSE = {nse:.3f}\n'
        f'KGE = {kge:.3f}\n'
        f'R = {r:.3f}\n'
        f'PBIAS = {pbias:.1f}%\n'
        f'MAE = {mae:.1f} m³/s\n'
        f'RMSE = {rmse:.1f} m³/s'
    )

    # 根据NSE值选择文本框颜色
    if nse >= 0.75:
        box_color = 'lightgreen'
    elif nse >= 0.5:
        box_color = 'lightyellow'
    elif nse >= 0.0:
        box_color = 'lightsalmon'
    else:
        box_color = 'lightcoral'

    props = dict(boxstyle='round', facecolor=box_color, alpha=0.8)
    ax1.text(0.02, 0.98, metrics_text, transform=ax1.transAxes, fontsize=11,
             verticalalignment='top', bbox=props, family='monospace')

    if param_text:
        param_props = dict(boxstyle='round', facecolor='aliceblue', alpha=0.85)
        ax1.text(0.98, 0.98, param_text, transform=ax1.transAxes, fontsize=9,
                 verticalalignment='top', horizontalalignment='right',
                 bbox=param_props, family='monospace')

    # 下图：散点图
    ax2 = axes[1]
    ax2.scatter(obs, sim, c='steelblue', alpha=0.3, s=10, edgecolors='none')

    # 添加1:1线
    max_val = max(obs.max(), sim.max()) * 1.1
    min_val = min(obs.min(), sim.min())
    ax2.plot([min_val, max_val], [min_val, max_val], 'k--', linewidth=1, label='1:1 Line')

    # 添加线性回归线
    z = np.polyfit(obs, sim, 1)
    p = np.poly1d(z)
    x_line = np.linspace(min_val, max_val, 100)
    ax2.plot(x_line, p(x_line), 'r-', linewidth=1,
             label=f'Regression: y={z[0]:.2f}x+{z[1]:.1f}')

    ax2.set_xlabel('Observed Discharge (m³/s)', fontsize=12)
    ax2.set_ylabel('Simulated Discharge (m³/s)', fontsize=12)
    ax2.set_title('Scatter Plot', fontsize=12)
    ax2.legend(loc='upper left', fontsize=9)
    ax2.grid(True, alpha=0.3)
    ax2.set_xlim(min_val, max_val)
    ax2.set_ylim(min_val, max_val)
    ax2.set_aspect('equal', adjustable='box')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    # 打印统计信息
    print(f"\n{'='*60}")
    print(f"流量对比分析报告 - {station_name}")
    print(f"{'='*60}")
    print(f"时间范围: {start_year} - {end_year}")
    print(f"有效数据天数: {len(merged)} (已剔除观测<0的{removed_count}条)")
    print(f"实际数据范围: {merged.index.min().strftime('%Y-%m-%d')} 至 {merged.index.max().strftime('%Y-%m-%d')}")
    print(f"\n观测流量统计:")
    print(f"  均值: {np.mean(obs):.1f} m³/s")
    print(f"  最大: {np.max(obs):.1f} m³/s")
    print(f"  最小: {np.min(obs):.1f} m³/s")
    print(f"\n模拟流量统计:")
    print(f"  均值: {np.mean(sim):.1f} m³/s")
    print(f"  最大: {np.max(sim):.1f} m³/s")
    print(f"  最小: {np.min(sim):.1f} m³/s")
    print(f"\n评价指标:")
    print(f"  NSE   = {nse:.4f}")
    print(f"  KGE   = {kge:.4f}")
    print(f"  R     = {r:.4f}")
    print(f"  PBIAS = {pbias:.2f}%")
    print(f"  MAE   = {mae:.2f} m³/s")
    print(f"  RMSE  = {rmse:.2f} m³/s")
    print(f"\n图片已保存至: {output_path}")
    print(f"{'='*60}\n")

    return {
        'NSE': nse,
        'KGE': kge,
        'R': r,
        'PBIAS': pbias,
        'MAE': mae,
        'RMSE': rmse
    }


def main():
    parser = argparse.ArgumentParser(description='流量模拟结果与观测数据对比绘图')
    parser.add_argument('--obs', type=str, required=True, help='观测数据文件路径')
    parser.add_argument('--sim', type=str, required=True, help='模拟数据文件路径')
    parser.add_argument('--start', type=int, required=True, help='起始年份')
    parser.add_argument('--end', type=int, required=True, help='结束年份')
    parser.add_argument('--output', type=str, default='discharge_comparison.png',
                        help='输出图片路径')
    parser.add_argument('--station', type=str, default='', help='站点名称')
    parser.add_argument('--params-json', type=str, default='',
                        help='参数JSON文件路径（可选，用于图上标注参数）')

    args = parser.parse_args()

    # 读取数据
    print(f"读取观测数据: {args.obs}")
    obs_df = read_obs_data(args.obs)
    print(f"  数据范围: {obs_df.index.min()} 至 {obs_df.index.max()}")

    print(f"读取模拟数据: {args.sim}")
    sim_df = read_sim_data(args.sim)
    print(f"  数据范围: {sim_df.index.min()} 至 {sim_df.index.max()}")

    param_text = ''
    if args.params_json:
        try:
            import json
            with open(args.params_json, 'r', encoding='utf-8') as f:
                pjson = json.load(f)
            params = pjson.get('params', {})
            if params:
                param_text = (
                    'Parameters\n'
                    f"binfilt={params.get('binfilt', np.nan):.3f}\n"
                    f"Ds={params.get('Ds', np.nan):.3f}\n"
                    f"Dsmax={params.get('Dsmax', np.nan):.3f}\n"
                    f"Ws={params.get('Ws', np.nan):.3f}\n"
                    f"d2={params.get('soil_d2', np.nan):.3f}\n"
                    f"d3={params.get('soil_d3', np.nan):.3f}"
                )
        except Exception as e:
            print(f"参数文件读取失败，跳过参数标注: {e}")

    # 绘图
    plot_comparison(obs_df, sim_df, args.start, args.end, args.output, args.station, param_text)


if __name__ == '__main__':
    main()
