import pandas as pd
import numpy as np
from pathlib import Path
from scipy.interpolate import griddata
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

print("=" * 80)
print("全球0.5度土壤数据插值到0.25度脚本 (scipy版本)")
print("=" * 80)

# ============================================================================
# 1. 配置路径
# ============================================================================
import os as _os
_BASIN = _os.environ.get("VIC_BASIN_NAME", "xixian_rerun_71379b42")
_SOIL_DIR = Path(_os.environ.get("VIC_OUT_ROOT", "/mnt/disk1/Hydrocraft_server/outputs")) / _BASIN / "vic_temp" / "soil"

SOIL_PARAM_IN = _SOIL_DIR / "SOIL_PARAM_FINAL.txt"
GLOBAL_SOIL_FILE = Path(r"/mnt/disk1/Hydrocraft_server/data/插值/global_soil_param_new.txt")
SOIL_PARAM_OUT = _SOIL_DIR / "SOIL_PARAM_COMPLETE.txt"

# ============================================================================
# 2. 定义参数映射
# ============================================================================
PARAMS_TO_INTERPOLATE = {
    'expt': {'source_col': 9, 'target_cols': [9, 10, 11]},
    'ksat': {'source_col': 12, 'target_cols': [12, 13, 14]},
    'bulk_density': {'source_col': 33, 'target_cols': [33, 34, 35]},
    'Wcr_FRACT': {'source_col': 40, 'target_cols': [40, 41, 42]},
    'Wpwp_FRACT': {'source_col': 43, 'target_cols': [43, 44, 45]},
    'init_moist': {'source_col': 18, 'target_cols': [18, 19, 20]},
    'AVG_T': {'source_col': 25, 'target_cols': [25]},
    'QUARTZ': {'source_col': 30, 'target_cols': [30, 31, 32]},
}

print(f"\n将插值的参数组：{len(PARAMS_TO_INTERPOLATE)}")
for param_name in PARAMS_TO_INTERPOLATE.keys():
    print(f"  - {param_name}")

# ============================================================================
# 3. 读取全球0.5度数据
# ============================================================================
print(f"\n{'─' * 80}")
print("步骤1: 读取全球0.5度土壤数据")
print(f"{'─' * 80}")

df_global = pd.read_csv(GLOBAL_SOIL_FILE, sep=r'\s+', header=None, dtype=float)
print(f"✓ 读取成功: {len(df_global)} 行, {df_global.shape[1]} 列")

global_lons = df_global.iloc[:, 3].values
global_lats = df_global.iloc[:, 2].values

print(f"  经度范围: {global_lons.min():.2f} ~ {global_lons.max():.2f}")
print(f"  纬度范围: {global_lats.min():.2f} ~ {global_lats.max():.2f}")

# ============================================================================
# 4. 读取VIC 0.25度土壤参数文件
# ============================================================================
print(f"\n{'─' * 80}")
print("步骤2: 读取VIC 0.25度土壤参数文件")
print(f"{'─' * 80}")

df_soil = pd.read_csv(SOIL_PARAM_IN, sep=r'\s+', header=None, dtype=float)
print(f"✓ 读取成功: {len(df_soil)} 行, {df_soil.shape[1]} 列")

target_lats = df_soil.iloc[:, 2].values
target_lons = df_soil.iloc[:, 3].values

print(f"  经度范围: {target_lons.min():.2f} ~ {target_lons.max():.2f}")
print(f"  纬度范围: {target_lats.min():.2f} ~ {target_lats.max():.2f}")

# ============================================================================
# 5. 逐个参数进行插值（使用scipy.interpolate.griddata）
# ============================================================================
print(f"\n{'─' * 80}")
print("步骤3: 执行插值 (scipy.griddata)")
print(f"{'─' * 80}")

for param_idx, (param_name, param_info) in enumerate(PARAMS_TO_INTERPOLATE.items(), 1):
    source_col = param_info['source_col']
    target_cols = param_info['target_cols']

    print(f"\n[{param_idx}/{len(PARAMS_TO_INTERPOLATE)}] {param_name}")
    print(f"  全球数据列{source_col + 1} → VIC列 {[c + 1 for c in target_cols]}")

    try:
        # 1. 提取全球数据的参数值
        source_values = df_global.iloc[:, source_col].values

        # 2. 过滤掉NaN值
        valid_mask = ~np.isnan(source_values)

        valid_count = valid_mask.sum()
        total_count = len(source_values)
        print(f"  有效数据点: {valid_count}/{total_count} ({100 * valid_count / total_count:.1f}%)")

        if valid_count == 0:
            print(f"  ✗ 没有有效数据，跳过")
            continue

        # 3. 准备scipy griddata所需的数据
        source_points = np.column_stack([
            global_lats[valid_mask],
            global_lons[valid_mask]
        ])
        source_vals = source_values[valid_mask]

        # 目标点坐标
        target_points = np.column_stack([target_lats, target_lons])

        # 4. 先用线性插值
        print(f"  执行线性插值...")
        interp_linear = griddata(
            source_points,
            source_vals,
            target_points,
            method='linear',
            fill_value=np.nan
        )

        # 5. 对NaN点使用最近邻插值
        nan_mask = np.isnan(interp_linear)
        if nan_mask.sum() > 0:
            print(f"  执行最近邻插值（填充{nan_mask.sum()}个NaN）...")
            interp_nearest = griddata(
                source_points,
                source_vals,
                target_points[nan_mask],
                method='nearest'
            )
            interp_linear[nan_mask] = interp_nearest

        # 6. 统计信息
        linear_count = (~nan_mask).sum()
        nearest_count = nan_mask.sum()
        final_nan = np.isnan(interp_linear).sum()

        print(f"  插值完成:")
        print(f"    线性插值: {linear_count}/{len(interp_linear)}")
        print(f"    最近邻补充: {nearest_count}/{len(interp_linear)}")
        print(f"    最终NaN: {final_nan}/{len(interp_linear)}")

        if final_nan == 0:
            print(f"    ✓ 所有格网都已填充")
            print(f"    范围: {interp_linear.min():.3f} ~ {interp_linear.max():.3f}")
        else:
            valid_values = interp_linear[~np.isnan(interp_linear)]
            if len(valid_values) > 0:
                print(f"    范围: {valid_values.min():.3f} ~ {valid_values.max():.3f}")
                print(f"    ⚠️ 仍有{final_nan}个NaN，将保持原值")

        # 7. 填充到所有目标列
        for i, target_col in enumerate(target_cols):
            if i == 0:
                # 第一层：使用插值结果（NaN保持原值）
                mask = ~np.isnan(interp_linear)
                df_soil.iloc[mask, target_col] = interp_linear[mask]
            else:
                # 第二、三层：复制第一层
                df_soil.iloc[:, target_col] = df_soil.iloc[:, target_cols[0]].values

        print(f"  ✓ 已填充到VIC列: {[c + 1 for c in target_cols]}")

    except Exception as e:
        print(f"  ✗ 插值失败: {e}")
        import traceback
        traceback.print_exc()
        continue

# ============================================================================
# 5.5 修改第24和25列的值
# ============================================================================
print(f"\n{'─' * 80}")
print("步骤3.5: 修改第24和25列的固定值")
print(f"{'─' * 80}")

# 第24列（索引23）设置为0.30
df_soil.iloc[:, 23] = 0.30
print(f"✓ 第24列 (Depth_2) 全部设置为: 0.30")

# 第25列（索引24）设置为1.50
df_soil.iloc[:, 24] = 1.50
print(f"✓ 第25列 (Depth_3) 全部设置为: 1.50")

print(f"\n验证修改结果（前5行）：")
print(f"{'行号':<6} {'第24列':<10} {'第25列':<10}")
print("─" * 30)
for i in range(min(5, len(df_soil))):
    print(f"{i+1:<6} {df_soil.iloc[i, 23]:<10.2f} {df_soil.iloc[i, 24]:<10.2f}")

# ============================================================================
# 5.6 bubble (VIC cols 28-30) + fs_active (VIC col 53)  —  dt_vic_031
# ============================================================================
# fill_parameters1.py leaves bubble = -9999 and fs_active = 0.  Both are ignored
# while FULL_ENERGY/FROZEN_SOIL are FALSE, so no reference basin ever noticed —
# but together they make `FROZEN_SOIL TRUE` unusable: VIC's
# estimate_layer_ice_content() reads bubble, and read_soilparam() skips any cell
# whose fs_active is 0.  A snow-dominated basin (哈尔滨) needs the frozen-soil
# module, so derive both here rather than leaving them as sentinels.
#
# bubble = 0.32 * expt + 4.3  is VIC's own texture relation (expt = 3 + 2b, so
# this maps the Campbell exponent onto the Clapp-Hornberger bubbling pressure in
# cm).  It is the relation used to build the Maurer/Livneh CONUS soil files and is
# documented in the VIC soil-parameter reference.
print(f"\n{'─' * 80}")
print("步骤3.6: 推导 bubble (第28-30列) 与 fs_active (第53列)")
print(f"{'─' * 80}")

_EXPT_IDX = [9, 10, 11]      # VIC cols 10-12
_BUBBLE_IDX = [27, 28, 29]   # VIC cols 28-30

for _b, _e in zip(_BUBBLE_IDX, _EXPT_IDX):
    _expt = pd.to_numeric(df_soil.iloc[:, _e], errors="coerce")
    if _expt.isna().any() or (_expt <= 0).any():
        raise ValueError(
            f"cannot derive bubble for VIC col {_b + 1}: expt (col {_e + 1}) "
            f"contains NaN or non-positive values — run fill_parameters1.py first"
        )
    df_soil.iloc[:, _b] = (0.32 * _expt + 4.3).round(3)

df_soil.iloc[:, 52] = 1      # fs_active: let VIC solve frozen soil on every cell

_bub = pd.to_numeric(df_soil.iloc[:, 27])
print(f"✓ bubble (第28-30列): {_bub.min():.3f} … {_bub.max():.3f} cm  (= 0.32*expt + 4.3)")
print(f"✓ fs_active (第53列) 全部设置为: 1")
assert (_bub > 0).all(), "bubble must be > 0 for FROZEN_SOIL TRUE"

# ============================================================================
# 6. 写入最终文件
# ============================================================================
print(f"\n{'─' * 80}")
print("步骤4: 写入最终文件")
print(f"{'─' * 80}")

with open(SOIL_PARAM_OUT, 'w') as f:
    for _, row in df_soil.iterrows():
        formatted_items = []
        for i, value in enumerate(row):
            col_index = i + 1

            if pd.isna(value):
                formatted_items.append('nan')
                continue

            if col_index in [1, 2]:
                formatted_items.append(str(int(value)))
            elif col_index in [3, 4]:
                formatted_items.append(f"{value:.4f}")
            elif col_index == 22:
                formatted_items.append(f"{value:.2f}")
            elif col_index in [24, 25]:  # 第24和25列格式化为3位小数
                formatted_items.append(f"{value:.3f}")
            elif col_index in [37, 38, 39, 53]:
                formatted_items.append(str(int(value)))
            else:
                if value == -9999.0 or value == -9999:
                    formatted_items.append("-9999")
                elif abs(value - round(value)) < 1e-6:
                    formatted_items.append(str(int(round(value))))
                else:
                    formatted_items.append(f"{value:.3f}")

        f.write(" ".join(formatted_items) + "\n")

print(f"✓ 写入成功: {SOIL_PARAM_OUT}")

# ============================================================================
# 7. 验证结果
# ============================================================================
print(f"\n{'─' * 80}")
print("步骤5: 验证填充结果")
print(f"{'─' * 80}")

df_result = pd.read_csv(SOIL_PARAM_OUT, sep=r'\s+', header=None, nrows=30, dtype=float)

print("\n前30行关键列检查：")
print(f"{'行号':<6} {'expt_1':<10} {'Ksat_1':<12} {'init_m_1':<10} {'Depth_2':<10} {'Depth_3':<10}")
print("─" * 70)

check_cols = [9, 12, 18, 23, 24]  # 加入第24和25列的检查
success_count = 0
for i in range(min(30, len(df_result))):
    values = [df_result.iloc[i, col] for col in check_cols]
    # 检查插值列是否有值
    has_value = any(v != 0 and v != -9999 and not pd.isna(v) for v in values[:3])
    if has_value:
        success_count += 1
    marker = "✓" if has_value else "✗"

    print(
        f"{i + 1:<6} {marker} {values[0]:<10.3f} {values[1]:<12.3f} {values[2]:<10.3f} {values[3]:<10.3f} {values[4]:<10.3f}")

print(f"\n填充统计（前30行）：")
print(f"  成功填充: {success_count}/{len(df_result)} ({100 * success_count / len(df_result):.1f}%)")

# 验证第24和25列的值
depth_2_check = df_result.iloc[:, 23].unique()
depth_3_check = df_result.iloc[:, 24].unique()
print(f"\n第24列唯一值: {depth_2_check}")
print(f"第25列唯一值: {depth_3_check}")

# 统计整个文件
df_all = pd.read_csv(SOIL_PARAM_OUT, sep=r'\s+', header=None, dtype=float)
total_success = 0
for i in range(len(df_all)):
    values = [df_all.iloc[i, col] for col in [9, 12, 18]]
    if any(v != 0 and v != -9999 and not pd.isna(v) for v in values):
        total_success += 1

print(f"\n全部格网填充统计：")
print(f"  成功填充: {total_success}/{len(df_all)} ({100 * total_success / len(df_all):.1f}%)")

# 验证所有行的第24和25列
all_depth_2 = df_all.iloc[:, 23].unique()
all_depth_3 = df_all.iloc[:, 24].unique()
print(f"\n全部格网第24列检查:")
print(f"  唯一值: {all_depth_2}")
print(f"  是否全部为0.30: {'✓' if len(all_depth_2) == 1 and abs(all_depth_2[0] - 0.30) < 0.001 else '✗'}")
print(f"全部格网第25列检查:")
print(f"  唯一值: {all_depth_3}")
print(f"  是否全部为1.50: {'✓' if len(all_depth_3) == 1 and abs(all_depth_3[0] - 1.50) < 0.001 else '✗'}")

print("\n" + "=" * 80)
print("处理完成！")
print("=" * 80)
print(f"\n输出文件: {SOIL_PARAM_OUT}")
print(f"格网数量: {len(df_soil)}")
print(f"插值参数: {len(PARAMS_TO_INTERPOLATE)} 组")
print("\n关键改进：")
print("  ✓ 使用scipy.interpolate.griddata")
print("  ✓ 线性插值 + 最近邻补充")
print("  ✓ 最近邻插值更robust，不会返回NaN")
print("  ✓ 第24列 (Depth_2) 设置为 0.30")
print("  ✓ 第25列 (Depth_3) 设置为 1.50")
print("\n" + "=" * 80)
