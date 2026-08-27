#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VIC输出预处理脚本 - 转换为Routing模型输入格式
Preprocess VIC output files to Routing model input format

Routing模型要求输入为7列: year month day prec evap runoff baseflow
VIC 5.x输出含20+列且带注释头，直接使用会导致routing读错列产生极端流量值。

本脚本自动解析VIC全局参数文件识别列号，无需手动指定。

用法 / Usage:
    python preprocess_vic_for_routing.py \
        --vic-result-dir <VIC输出目录> \
        --global-param <VIC全局参数文件> \
        --output-dir <Routing输入目录> \
        [--output-prefix <输出文件前缀, 默认 fluxes_>]

示例 / Example:
    python preprocess_vic_for_routing.py \
        --vic-result-dir /path/to/outputs/xixian/vic_result \
        --global-param /path/to/outputs/xixian/vic_temp/global_param_xixian.txt \
        --output-dir /path/to/outputs/xixian/routing_param/vic_in \
        --output-prefix fluxes_
"""

import os
import argparse

# VIC中产生多列输出的变量（每个产生 NLAYER 列）
MULTI_LAYER_VARS = {
    "OUT_SOIL_MOIST", "OUT_SOIL_TEMP", "OUT_SOIL_ICE",
    "OUT_SOIL_LIQ", "OUT_SOIL_TNODE", "OUT_SOIL_TNODE_WL",
}


def parse_global_param(filepath):
    """
    解析VIC全局参数文件，提取OUTVAR定义顺序并计算列索引。
    Parse VIC global parameter file to determine output column mapping.

    Returns:
        col_map (dict): 变量名 -> 列索引(0-based)
        nlayer (int): 土壤层数
        outfile_prefix (str): VIC输出文件名前缀(OUTFILE)
    """
    nlayer = 3
    outvars = []
    outfile_prefix = "fluxes"

    with open(filepath, 'r') as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or stripped.startswith('YEAR'):
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            key = parts[0]
            if key == 'NLAYER':
                nlayer = int(parts[1])
            elif key == 'OUTVAR':
                outvars.append(parts[1])
            elif key == 'OUTFILE':
                outfile_prefix = parts[1]

    # 构建列索引映射 (0-based)
    # 前3列固定: year(0), month(1), day(2)
    col_map = {}
    idx = 3
    for var in outvars:
        col_map[var] = idx
        if var in MULTI_LAYER_VARS:
            idx += nlayer
        else:
            idx += 1

    return col_map, nlayer, outfile_prefix


def preprocess_file(input_path, output_path, col_indices):
    """
    从单个VIC输出文件中提取指定列，写入新文件。
    跳过以 '#' 开头的注释行和空行。
    """
    lines_written = 0
    with open(input_path, 'r') as fin, open(output_path, 'w') as fout:
        for line in fin:
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or stripped.startswith('YEAR'):
                continue
            parts = stripped.split()
            if len(parts) <= max(col_indices):
                continue
            extracted = [parts[i] for i in col_indices]
            fout.write('\t'.join(extracted) + '\n')
            lines_written += 1
    return lines_written


def find_vic_output_files(result_dir, vic_prefix):
    """
    在VIC结果目录中查找匹配前缀的输出文件。
    排除macOS隐藏文件(._开头)。
    """
    files = []
    if not os.path.isdir(result_dir):
        return files
    for entry in sorted(os.listdir(result_dir)):
        if entry.startswith('._') or entry.startswith('.'):
            continue
        if entry.startswith(vic_prefix + '_'):
            files.append(os.path.join(result_dir, entry))
    return files


def extract_coords(filename, vic_prefix):
    """
    从VIC文件名中提取坐标部分。
    例: 'huaihe_fluxes_32.1250_114.6250.txt' -> '32.1250_114.6250'
    """
    basename = os.path.basename(filename)
    # 去除可能的 .txt 后缀
    if basename.endswith('.txt'):
        basename = basename[:-4]
    # 去除 VIC 前缀和分隔下划线
    coord_part = basename[len(vic_prefix) + 1:]
    return coord_part


def main():
    parser = argparse.ArgumentParser(
        description='VIC输出预处理: 提取Routing所需的7列 (year month day prec evap runoff baseflow)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
输出文件格式 (制表符分隔, 无表头):
  year  month  day  prec  evap  runoff  baseflow

注意: 列号从VIC全局参数文件的OUTVAR定义自动推断，无需手动指定。
        """)
    parser.add_argument('--vic-result-dir', required=True,
                        help='VIC输出文件所在目录')
    parser.add_argument('--global-param', required=True,
                        help='VIC全局参数文件路径 (用于自动识别列号)')
    parser.add_argument('--output-dir', required=True,
                        help='预处理后文件的输出目录 (即Routing的vic_in目录)')
    parser.add_argument('--output-prefix', default='fluxes_',
                        help='输出文件名前缀 (默认: fluxes_, 与rout_global.txt中的设置对应)')

    args = parser.parse_args()

    # === 1. 解析全局参数文件 ===
    print(f"[1] 解析全局参数文件: {args.global_param}")
    if not os.path.exists(args.global_param):
        print(f"    错误: 文件不存在 - {args.global_param}")
        return 1

    col_map, nlayer, vic_prefix = parse_global_param(args.global_param)

    print(f"    NLAYER = {nlayer}")
    print(f"    OUTFILE前缀 = {vic_prefix}")
    print(f"    检测到 {len(col_map)} 个输出变量")

    # === 2. 检查必需变量是否存在 ===
    print(f"\n[2] 检查必需输出变量...")
    required = ['OUT_PREC', 'OUT_EVAP', 'OUT_RUNOFF', 'OUT_BASEFLOW']
    missing = [v for v in required if v not in col_map]
    if missing:
        print(f"    错误: 全局参数文件中缺少以下OUTVAR定义: {missing}")
        print(f"    当前已定义: {list(col_map.keys())}")
        return 1

    # === 3. 确定列索引 ===
    col_indices = [
        0, 1, 2,                     # year, month, day (固定)
        col_map['OUT_PREC'],         # 降水
        col_map['OUT_EVAP'],         # 蒸发
        col_map['OUT_RUNOFF'],       # 地表径流
        col_map['OUT_BASEFLOW'],     # 基流
    ]

    print(f"\n[3] 列映射 (0-based索引):")
    print(f"    year=0  month=1  day=2")
    print(f"    OUT_PREC={col_map['OUT_PREC']}  OUT_EVAP={col_map['OUT_EVAP']}")
    print(f"    OUT_RUNOFF={col_map['OUT_RUNOFF']}  OUT_BASEFLOW={col_map['OUT_BASEFLOW']}")

    # === 4. 查找VIC输出文件 ===
    print(f"\n[4] 扫描VIC输出文件: {args.vic_result_dir}")
    vic_files = find_vic_output_files(args.vic_result_dir, vic_prefix)
    if not vic_files:
        print(f"    错误: 未找到匹配 '{vic_prefix}_*' 的文件")
        print(f"    请检查VIC是否已运行完成，以及OUTFILE前缀是否正确")
        return 1

    print(f"    找到 {len(vic_files)} 个文件")

    # === 5. 创建输出目录并处理文件 ===
    os.makedirs(args.output_dir, exist_ok=True)

    output_prefix = args.output_prefix
    if not output_prefix.endswith('_'):
        output_prefix += '_'

    print(f"\n[5] 开始预处理...")
    total_lines = 0
    for i, vic_file in enumerate(vic_files):
        coords = extract_coords(vic_file, vic_prefix)
        out_filename = f"{output_prefix}{coords}"
        out_path = os.path.join(args.output_dir, out_filename)

        n = preprocess_file(vic_file, out_path, col_indices)
        total_lines += n

        if (i + 1) % 10 == 0 or (i + 1) == len(vic_files):
            print(f"    进度: {i + 1}/{len(vic_files)}")

    # === 6. 输出统计 ===
    avg_lines = total_lines // max(len(vic_files), 1)
    print(f"\n{'=' * 55}")
    print(f"VIC输出预处理完成")
    print(f"{'=' * 55}")
    print(f"  输入目录:    {args.vic_result_dir}")
    print(f"  输出目录:    {args.output_dir}")
    print(f"  处理文件数:  {len(vic_files)}")
    print(f"  每文件行数:  ~{avg_lines}")
    print(f"  输出文件前缀: {output_prefix}")
    print(f"  输出列格式:  year  month  day  prec  evap  runoff  baseflow")
    print(f"{'=' * 55}")
    return 0


if __name__ == '__main__':
    exit(main() or 0)
