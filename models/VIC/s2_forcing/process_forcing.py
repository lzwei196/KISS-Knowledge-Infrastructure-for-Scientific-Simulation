# KDT dt_vic_023: netCDF4 MUST be imported before xarray. A bare
# xr.open_dataset() makes xarray enumerate every installed backend entrypoint
# (rex -> h5py), which dlopen's h5py's bundled libhdf5 first. netCDF4's C calls
# then bind to that foreign HDF5 and the interpreter dies with SIGSEGV during
# HDF5 teardown -- after the data has already been read correctly. Importing
# netCDF4 first makes its own libhdf5 win the global symbol table.
import netCDF4  # noqa: F401  # isort:skip  -- must precede `import xarray`
import xarray as xr
import pandas as pd
from pathlib import Path
import os
import numpy as np
import re
import sys
import warnings

# --- 0. 忽略不必要的警告 ---
warnings.filterwarnings("ignore", category=FutureWarning)


def open_nc(path) -> xr.Dataset:
    """Engine-pinned, eagerly-loaded, handle-closing read.

    Mirrors the shipped siblings s2_forcing/forcing_1d.py and
    s3_soil/fill_parameters1.py. Pinning the engine skips xarray's backend
    probe; .load() inside the context manager keeps at most one live HDF5
    handle instead of one per input file.
    """
    try:
        with xr.open_dataset(path, engine="netcdf4") as ds:
            return ds.load()
    except Exception:
        with xr.open_dataset(path, engine="h5netcdf") as ds:
            return ds.load()

# --- 1. 配置路径 ---
# 输入：包含所有处理好的NC文件的文件夹
# --- Basin/period configuration via environment (KDT 2026-07-09) -----------
# The forcing_1d NetCDF glob and the VIC forcing-file prefix used to be
# hard-coded to `_xixian.nc` / `huai_01dy_025deg_`, so a new basin silently
# found zero input files (or wrote files VIC could not locate via FORCING1).
_BASIN = os.environ.get("VIC_BASIN_NAME", "xixian")
_OUT_ROOT = Path(os.environ.get("VIC_OUT_ROOT", "KISSPATH_OUTPUTS"))
# FORCING1 prefix in the global param file MUST equal this string.
FORCING_PREFIX = os.environ.get("VIC_FORCING_PREFIX", "huai_01dy_025deg_")

INPUT_DATA_DIR = _OUT_ROOT / _BASIN / "vic_temp" / "forcing" / "forcing_1d"
# codex structure_sync r1 #4: forcing_1d.py tags every file with the target resolution token
# (025deg / 010deg, same rule as s1_grid). A 0.25 and a 0.1 build of one basin share
# forcing_1d, so only files of THIS VIC_RES are read — mixing them doubled every timestamp.
_RES = float(os.environ.get("VIC_RES", "0.25"))
if abs(float(os.environ.get("VIC_RES", "0.25")) * 100 - round(float(os.environ.get("VIC_RES", "0.25")) * 100)) > 1e-6:
    # codex structure_sync r2 #4: the NNNdeg token holds hundredths of a degree only; 0.125 and
    # 0.12 would both be "012deg" and silently share grid/forcing files. Refuse, never round.
    raise SystemExit(f"VIC_RES={os.environ.get('VIC_RES')} is not a whole number of 0.01 deg; "
                     f"the resolution token (e.g. 025deg) cannot represent it")
_RTOK = f"{int(round(_RES * 100)):03d}deg"
_RTOK_RE = re.compile(rf"_{_RTOK}_")
# 输出：最终气象驱动文件存放的文件夹
OUTPUT_FORCING_DIR = _OUT_ROOT / _BASIN / "vic_temp" / "forcing" / "forcing_final"
# 土壤参数文件（用于获取准确的经纬度和grid_id）
SOIL_PARAM_FILE = _OUT_ROOT / _BASIN / "vic_temp" / "soil" / "SOIL_PARAM_COMPLETE.txt"

# --- 2. 准备工作 ---
os.makedirs(OUTPUT_FORCING_DIR, exist_ok=True)
print("="*80)
print("最终气象驱动文件生成脚本（改进版）")
print("="*80)

# --- 2.5 读取土壤参数文件，获取准确的格网信息 ---
print("\n步骤1: 读取土壤参数文件，获取格网坐标")
print("-"*80)
try:
    # 读取土壤文件（只需要前4列：run_cell, grid_id, lat, lon）
    df_soil = pd.read_csv(SOIL_PARAM_FILE, sep=r'\s+', header=None, 
                          usecols=[0, 1, 2, 3], 
                          names=['run_cell', 'grid_id', 'lat', 'lon'])
    
    print(f"✓ 读取成功: {len(df_soil)} 个格网")
    print(f"  经度范围: {df_soil['lon'].min():.4f} ~ {df_soil['lon'].max():.4f}")
    print(f"  纬度范围: {df_soil['lat'].min():.4f} ~ {df_soil['lat'].max():.4f}")
    print(f"\n前5个格网信息：")
    print(df_soil.head().to_string(index=False))
    
except Exception as e:
    print(f"✗ 错误：无法读取土壤参数文件 '{SOIL_PARAM_FILE}'")
    print(f"  错误信息: {e}")
    sys.exit(1)

# --- 3. 一次性读取所有变量和所有年份的数据 ---
print(f"\n步骤2: 读取所有变量的NC文件")
print("-"*80)

# 需要从CMFD读取的变量列表
variables_to_load = ['prec', 'temp', 'pres', 'srad', 'lrad', 'wind', 'shum']
all_ds = []
try:
    import glob
    for var in variables_to_load:
        print(f"  - 正在加载变量: {var}")
        # 使用 glob 找到所有文件并逐个打开
        var_files = sorted(f for f in glob.glob(str(INPUT_DATA_DIR / f"{var}_*_{_BASIN}.nc"))
                           if _RTOK_RE.search(Path(f).name))
        if not var_files:
            raise FileNotFoundError(f"未找到 {var} 的 {_RTOK} 文件 (VIC_RES={_RES}) in {INPUT_DATA_DIR}")

        # KDT 2026-07-09: was an incremental xr.concat inside the loop, which
        # re-copies the whole accumulated array on every file (O(n^2) in both
        # time and memory). One concat over the full list is O(n).
        ds_var = xr.concat([open_nc(f) for f in var_files], dim='time')
        ds_var = ds_var.sortby('time')
        _dup = ds_var.indexes['time'].duplicated()
        if _dup.any():     # fail closed: two files for one timestamp is never a valid forcing
            raise ValueError(f"{var}: {int(_dup.sum())} duplicate timestamps across {len(var_files)} "
                             f"files (first {ds_var.indexes['time'][_dup][0]}) — mixed builds in {INPUT_DATA_DIR}")

        all_ds.append(ds_var)

    # 将所有变量合并到一个大的 xarray.Dataset 中
    ds_merged = xr.merge(all_ds)
    print(f"✓ 所有数据加载并合并完毕！")
    
except Exception as e:
    print(f"✗ 错误：读取NC文件时出错。")
    print(f"  请确保路径 '{INPUT_DATA_DIR}' 下包含所有必需的变量文件。")
    print(f"  错误信息: {e}")
    sys.exit(1)

# --- 4. 筛选时间范围 ---
print(f"\n步骤3: 筛选时间范围")
print("-"*80)

START_DATE = os.environ.get("VIC_START_DATE", '1979-01-01')
END_DATE = os.environ.get("VIC_END_DATE", '1980-12-31')
print(f"时间范围: {START_DATE} 到 {END_DATE}")

ds_merged = ds_merged.sel(time=slice(START_DATE, END_DATE))
# codex structure_sync r5: the VIC forcing file has no time column, so the selected axis must be
# non-empty, evenly stepped and cover the WHOLE requested period. An empty selection (dates outside
# the NetCDF period) or a timestamp missing in every variable would otherwise write short or
# shifted files and report success. Stop before any output file is opened.
_t = pd.DatetimeIndex(ds_merged.indexes["time"])
if len(_t) == 0:
    print(f"✗ 错误：{START_DATE}..{END_DATE} 内没有任何时间步 (forcing_1d covers other dates)", file=sys.stderr)
    sys.exit(1)
if len(_t) > 1:
    _steps = pd.Series(_t[1:] - _t[:-1]).unique()
    if len(_steps) != 1:
        _bad = _t[1:][(_t[1:] - _t[:-1]) != _steps.min()][:3]
        print(f"✗ 错误：时间步不连续 (steps {[str(x) for x in _steps[:4]]}; gap after e.g. {list(map(str, _bad))})", file=sys.stderr)
        sys.exit(1)
    _dt = pd.Timedelta(_steps[0])
else:
    _dt = pd.Timedelta(hours=24)
if _t[0] > pd.Timestamp(START_DATE) or _t[-1] < pd.Timestamp(END_DATE) + pd.Timedelta(hours=24) - _dt:
    print(f"✗ 错误：forcing covers {_t[0]}..{_t[-1]}, not the whole requested {START_DATE}..{END_DATE}", file=sys.stderr)
    sys.exit(1)
print(f"✓ 数据筛选完毕，共包含 {len(ds_merged.time)} 个时间步。")

# --- 5. 检查坐标系统 ---
print(f"\n步骤4: 检查nc文件的坐标系统")
print("-"*80)

# 确定nc文件使用的坐标名
if 'y' in ds_merged.coords and 'x' in ds_merged.coords:
    lat_dim, lon_dim = 'y', 'x'
    print(f"✓ 使用坐标名: y (纬度), x (经度)")
elif 'lat' in ds_merged.coords and 'lon' in ds_merged.coords:
    lat_dim, lon_dim = 'lat', 'lon'
    print(f"✓ 使用坐标名: lat, lon")
else:
    print(f"✗ 错误：无法识别nc文件的坐标维度")
    sys.exit(1)

print(f"  nc文件纬度范围: {float(ds_merged[lat_dim].min().values):.4f} ~ {float(ds_merged[lat_dim].max().values):.4f}")
print(f"  nc文件经度范围: {float(ds_merged[lon_dim].min().values):.4f} ~ {float(ds_merged[lon_dim].max().values):.4f}")

# --- 6. 为每个格网生成一个驱动文件（使用土壤文件的坐标） ---
print(f"\n步骤5: 为 {len(df_soil)} 个格网生成驱动文件")
print("-"*80)

success_count = 0
fail_count = 0
missing_coords = []

for idx, row in df_soil.iterrows():
    run_cell = int(row['run_cell'])
    grid_id = int(row['grid_id'])
    lat = row['lat']
    lon = row['lon']
    
    # 构造输出文件名（匹配VIC期望的格式）
    # 根据VIC全局参数文件中的FORCING定义，使用以下格式之一：
    # 格式1: huai_01dy_025deg_<lat>_<lon> (标准前缀，4位小数)
    output_filename = f"{FORCING_PREFIX}{lat:.4f}_{lon:.4f}"
    
    # 格式2（备选）: forcing_<lat>_<lon>
    # output_filename = f"forcing_{lat:.4f}_{lon:.4f}"
    
    # 格式3（备选）: data_<run_cell>_<grid_id>
    # output_filename = f"data_{run_cell}_{grid_id}"
    
    output_path = OUTPUT_FORCING_DIR / output_filename
    
    if (idx + 1) % 50 == 0 or idx == 0:
        print(f"  [{idx+1}/{len(df_soil)}] 正在处理 grid_id={grid_id}, lat={lat:.4f}, lon={lon:.4f}")
    
    try:
        # 使用nearest方法选择最近的格网点
        # 关键：使用土壤文件的经纬度来查找nc文件中对应的数据
        cell_data = ds_merged.sel(
            {lat_dim: lat, lon_dim: lon}, 
            method='nearest', 
            tolerance=_RES / 2.0 + 0.005  # 容差：半个格网 (System 1 W5: follows VIC_RES)
        ).compute()
        
        # 检查是否所有变量都有有效数据
        # codex structure_sync r4 (pre-existing): ANY missing value fails the cell, not only an
        # all-NaN variable — a missing month in one variable would otherwise become blank fields in
        # the VIC forcing file while the converter reported success. A missing variable fails too.
        has_valid_data = True
        _why = ""
        for var in variables_to_load:
            if var not in cell_data.data_vars:
                has_valid_data, _why = False, f"{var} missing"
                break
            _n = int(cell_data[var].isnull().sum())
            if _n:
                has_valid_data, _why = False, f"{var} has {_n} NaN steps of {cell_data[var].size}"
                break

        if not has_valid_data:
            print(f"    ✗ grid_id={grid_id} ({lat:.4f}, {lon:.4f}): {_why} — no forcing file written")
            fail_count += 1
            missing_coords.append((grid_id, lat, lon))
            continue
        
        # 转换为Pandas DataFrame
        df = cell_data.to_dataframe()
        
        # --- 7. 单位换算与参数计算 ---
        df_out = pd.DataFrame(index=df.index)
        
        # 1. 气温 (air_temp): 从 K 转换为 °C
        df_out['air_temp'] = df['temp'] - 273.15

        # 2. 降水 (prec): 从 kg/m2/s 转换为 mm/3hr
        # 3小时 = 10800秒, 1 kg/m²/s = 1 mm/s
        df_out['prec'] = df['prec'] * 10800

        # 3. 气压 (pressure): 从 Pa 转换为 kPa
        df_out['pressure'] = df['pres'] / 1000.0

        # 4. 短波辐射 (swdown): 单位 W/m2
        df_out['swdown'] = df['srad']
        
        # 5. 长波辐射 (lwdown): 单位 W/m2
        df_out['lwdown'] = df['lrad']

        # 6. 水汽压 (vp): 根据比湿(shum)和气压(pres)计算，并转换为kPa
        df_out['vp'] = (df['shum'] * df['pres']) / (0.622 + 0.378 * df['shum']) / 1000.0
        
        # 7. 风速 (wind): 单位 m/s
        df_out['wind'] = df['wind']

        # --- 8. 整理并写入文件 ---
        final_columns_order = ['air_temp', 'prec', 'pressure', 'swdown', 'lwdown', 'vp', 'wind']
        vic_forcing_df = df_out[final_columns_order]
        
        # 写入文本文件
        vic_forcing_df.to_csv(
            output_path,
            sep='\t',
            header=False,
            index=False,
            float_format='%.4f'
        )
        
        success_count += 1
        
    except Exception as e:
        print(f"    ✗ 失败：grid_id={grid_id} ({lat:.4f}, {lon:.4f}), 错误: {e}")
        fail_count += 1
        missing_coords.append((grid_id, lat, lon))
        continue

# --- 9. 汇总统计 ---
print(f"\n{'='*80}")
print("处理完成！")
print(f"{'='*80}")
print(f"\n统计信息：")
print(f"  成功生成: {success_count} 个文件")
print(f"  失败/跳过: {fail_count} 个文件")
print(f"  总计格网: {len(df_soil)} 个")
print(f"  成功率: {100*success_count/len(df_soil):.1f}%")

if missing_coords:
    print(f"\n⚠️  以下格网未能生成驱动文件：")
    print(f"{'grid_id':<10} {'纬度':<12} {'经度':<12}")
    print("-"*40)
    for gid, lat, lon in missing_coords[:10]:  # 只显示前10个
        print(f"{gid:<10} {lat:<12.4f} {lon:<12.4f}")
    if len(missing_coords) > 10:
        print(f"... 还有 {len(missing_coords)-10} 个")

print(f"\n输出目录: {OUTPUT_FORCING_DIR}")
print(f"文件命名格式: forcing_<lat>_<lon>")
print(f"\n说明：")
print(f"  - 使用土壤参数文件的经纬度坐标")
print(f"  - 文件名与土壤文件的经纬度完全一致")
print(f"  - VIC可以通过经纬度匹配土壤和气象文件")
print(f"\n{'='*80}")

# honest exit code: a cell without forcing makes VIC fail later (or run short) — stop here
if fail_count:
    print(f"✗ process_forcing FAILED: {fail_count} of {len(df_soil)} cells have no forcing file",
          file=sys.stderr)
    sys.exit(1)
