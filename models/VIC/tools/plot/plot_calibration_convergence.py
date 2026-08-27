#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
率定收敛曲线图绘制脚本
Calibration Convergence Plot

用法 / Usage:
    python plot_calibration_convergence.py --csv <率定结果CSV> --output <输出图片路径>
           [--metric <指标名>] [--threshold <阈值线>] [--title <图标题>]
           [--phase1 <随机探索次数>] [--ai_only]

    --ai_only: 仅显示AI优化阶段，从1重新编号
"""

import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import warnings
warnings.filterwarnings('ignore')

# 设置字体
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


def plot_convergence(csv_path, output_path, metric='NSE', threshold=None,
                     title=None, phase1_runs=20, ai_only=False):
    """
    绘制率定收敛曲线图

    Parameters:
    -----------
    csv_path : str
        率定结果CSV文件路径
    output_path : str
        输出图片路径
    metric : str
        评价指标名称 (NSE, KGE, RMSE等)
    threshold : float or list
        阈值线 (可以是单个值或多个值的列表)
    title : str
        图表标题
    phase1_runs : int
        第一阶段(随机探索)的运行次数
    ai_only : bool
        是否仅显示AI优化阶段（从1重新编号）
    """
    # 读取数据
    df = pd.read_csv(csv_path)

    # 如果仅显示AI优化阶段
    if ai_only:
        df = df[df['run_id'] > phase1_runs].copy()
        df['run_id'] = range(1, len(df) + 1)  # 重新从1编号
        phase1_runs = 0  # AI only模式下没有第一阶段

    # 检查指标列是否存在
    if metric not in df.columns:
        available = [c for c in df.columns if c not in ['run_id', 'runtime_seconds', 'best_nse_so_far']]
        raise ValueError(f"指标 '{metric}' 不存在，可用指标: {available}")

    run_ids = df['run_id'].values
    metric_values = df[metric].values

    # 计算累积最优值
    if metric in ['RMSE', 'MAE', 'PBIAS']:
        # 对于这些指标，越小越好
        if metric == 'PBIAS':
            best_so_far = np.minimum.accumulate(np.abs(metric_values))
        else:
            best_so_far = np.minimum.accumulate(metric_values)
        better_direction = 'lower'
    else:
        # NSE, KGE, R 等，越大越好
        best_so_far = np.maximum.accumulate(metric_values)
        better_direction = 'higher'

    # 找出刷新最优记录的点
    if better_direction == 'higher':
        is_new_best = np.zeros(len(metric_values), dtype=bool)
        is_new_best[0] = True
        current_best = metric_values[0]
        for i in range(1, len(metric_values)):
            if metric_values[i] > current_best:
                is_new_best[i] = True
                current_best = metric_values[i]
    else:
        is_new_best = np.zeros(len(metric_values), dtype=bool)
        is_new_best[0] = True
        current_best = metric_values[0] if metric != 'PBIAS' else abs(metric_values[0])
        for i in range(1, len(metric_values)):
            val = metric_values[i] if metric != 'PBIAS' else abs(metric_values[i])
            if val < current_best:
                is_new_best[i] = True
                current_best = val

    # 创建图形
    fig, ax = plt.subplots(figsize=(14, 7))

    # 绘制阶段背景色
    if ai_only:
        # AI only模式：统一绿色背景
        ax.axvspan(0.5, len(run_ids) + 0.5, alpha=0.15, color='green',
                   label='AI-Guided Optimization')
        colors = ['forestgreen' for _ in range(len(run_ids))]
    elif phase1_runs > 0 and phase1_runs < len(run_ids):
        ax.axvspan(0.5, phase1_runs + 0.5, alpha=0.15, color='blue',
                   label='Phase 1: Random Exploration')
        ax.axvspan(phase1_runs + 0.5, len(run_ids) + 0.5, alpha=0.15, color='green',
                   label='Phase 2: AI-Guided Optimization')
        colors = ['steelblue' if i < phase1_runs else 'forestgreen'
                  for i in range(len(run_ids))]
    else:
        colors = ['steelblue' for _ in range(len(run_ids))]

    # 绘制每次运行的指标值 (散点)
    ax.scatter(run_ids, metric_values, c=colors, s=30, alpha=0.6,
               edgecolors='none', zorder=3)

    # 高亮刷新最优的点
    new_best_runs = run_ids[is_new_best]
    new_best_values = metric_values[is_new_best]
    ax.scatter(new_best_runs, new_best_values, c='red', s=80, marker='*',
               edgecolors='darkred', linewidths=0.5, zorder=5,
               label='New Best Record')

    # 绘制累积最优曲线
    ax.plot(run_ids, best_so_far, 'r-', linewidth=2, alpha=0.8,
            label=f'Best {metric} So Far', zorder=4)

    # 绘制阈值线
    if threshold is not None:
        if isinstance(threshold, (list, tuple)):
            thresholds = threshold
        else:
            thresholds = [threshold]

        colors_th = ['orange', 'purple', 'brown', 'pink']
        for i, th in enumerate(thresholds):
            color = colors_th[i % len(colors_th)]
            ax.axhline(y=th, color=color, linestyle='--', linewidth=2, alpha=0.8,
                      label=f'Threshold: {metric}={th}', zorder=2)

    # 设置坐标轴
    ax.set_xlabel('Run ID', fontsize=12)
    ax.set_ylabel(metric, fontsize=12)

    # 设置标题
    if title:
        ax.set_title(title, fontsize=14)
    else:
        ax.set_title(f'Calibration Convergence: {metric}', fontsize=14)

    # 设置x轴范围
    ax.set_xlim(0.5, len(run_ids) + 0.5)

    # 添加网格
    ax.grid(True, alpha=0.3, zorder=1)

    # 图例
    ax.legend(loc='lower right' if better_direction == 'higher' else 'upper right',
              fontsize=10)

    # 添加统计信息文本框
    final_best = best_so_far[-1]
    initial_best = best_so_far[0]
    improvement = final_best - initial_best if better_direction == 'higher' else initial_best - final_best

    if ai_only:
        stats_text = (
            f'AI Optimization Runs: {len(run_ids)}\n'
            f'─────────────────\n'
            f'Initial ({metric}): {initial_best:.4f}\n'
            f'Final Best ({metric}): {final_best:.4f}\n'
            f'Improvement: {improvement:+.4f}'
        )
    else:
        stats_text = (
            f'Total Runs: {len(run_ids)}\n'
            f'Phase 1 (Random): {phase1_runs} runs\n'
            f'Phase 2 (AI): {len(run_ids) - phase1_runs} runs\n'
            f'─────────────────\n'
            f'Initial Best ({metric}): {initial_best:.4f}\n'
            f'Final Best ({metric}): {final_best:.4f}\n'
            f'Improvement: {improvement:+.4f}'
        )

    props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10,
            verticalalignment='top', bbox=props, family='monospace')

    # 标注最终最优点
    best_run_idx = np.argmax(best_so_far) if better_direction == 'higher' else np.argmin(best_so_far)
    best_run = run_ids[best_run_idx]
    best_value = metric_values[best_run_idx]

    ax.annotate(f'Best: Run {best_run}\n{metric}={best_value:.4f}',
                xy=(best_run, best_value),
                xytext=(best_run + len(run_ids)*0.08, best_value),
                fontsize=9,
                arrowprops=dict(arrowstyle='->', color='red', lw=1.5),
                bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow', alpha=0.8))

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    # 打印统计信息
    print(f"\n{'='*60}")
    print(f"率定收敛分析报告")
    print(f"{'='*60}")
    print(f"数据文件: {csv_path}")
    print(f"评价指标: {metric}")
    if ai_only:
        print(f"模式: 仅AI优化阶段")
    print(f"\n运行统计:")
    if ai_only:
        print(f"  AI优化运行次数: {len(run_ids)}")
    else:
        print(f"  总运行次数: {len(run_ids)}")
        print(f"  第一阶段 (随机探索): {phase1_runs} 次")
        print(f"  第二阶段 (AI优化): {len(run_ids) - phase1_runs} 次")
    print(f"  刷新最优次数: {np.sum(is_new_best)}")
    print(f"\n{metric} 统计:")
    print(f"  初始值: {initial_best:.4f}")
    print(f"  最终最优: {final_best:.4f}")
    print(f"  提升幅度: {improvement:+.4f}")
    print(f"  最优运行: Run {best_run}")
    if threshold is not None:
        for th in thresholds:
            exceeded = np.sum(metric_values >= th) if better_direction == 'higher' else np.sum(metric_values <= th)
            print(f"  超过阈值 {th} 的次数: {exceeded}")
    print(f"\n图片已保存至: {output_path}")
    print(f"{'='*60}\n")

    return {
        'total_runs': len(run_ids),
        'phase1_runs': phase1_runs,
        'phase2_runs': len(run_ids) - phase1_runs,
        'new_best_count': int(np.sum(is_new_best)),
        'initial_best': initial_best,
        'final_best': final_best,
        'improvement': improvement,
        'best_run': int(best_run)
    }


def main():
    parser = argparse.ArgumentParser(description='率定收敛曲线图绘制')
    parser.add_argument('--csv', type=str, required=True,
                        help='率定结果CSV文件路径')
    parser.add_argument('--output', type=str, default='calibration_convergence.png',
                        help='输出图片路径')
    parser.add_argument('--metric', type=str, default='NSE',
                        help='评价指标名称 (默认: NSE)')
    parser.add_argument('--threshold', type=float, nargs='+', default=None,
                        help='阈值线，可指定多个值')
    parser.add_argument('--title', type=str, default=None,
                        help='图表标题')
    parser.add_argument('--phase1', type=int, default=20,
                        help='第一阶段运行次数 (默认: 20)')
    parser.add_argument('--ai_only', action='store_true',
                        help='仅显示AI优化阶段，从1重新编号')

    args = parser.parse_args()

    plot_convergence(
        csv_path=args.csv,
        output_path=args.output,
        metric=args.metric,
        threshold=args.threshold,
        title=args.title,
        phase1_runs=args.phase1,
        ai_only=args.ai_only
    )


if __name__ == '__main__':
    main()
