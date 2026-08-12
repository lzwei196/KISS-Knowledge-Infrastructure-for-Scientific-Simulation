# KDT dt_vic_023: netCDF4 MUST be imported before xarray, and every
# xr.open_dataset() MUST pin `engine=`. See diagnostics/triplets.md.
import netCDF4  # noqa: F401  # isort:skip  -- must precede `import xarray`
import xarray as xr
import numpy as np
import rioxarray
from pathlib import Path
import os
import warnings
from rasterio.enums import Resampling
from rasterio.transform import from_origin
import re
from scipy.interpolate import griddata

# ====================================================================
# --- 0. 配置 ---
# ====================================================================
# KDT 2026-07-10: ("rhum", "Rhum") removed. The CMFD directory is spelled
# "RHum", so this entry never matched and every run printed "✗ 目录不存在" —
# harmlessly, because process_forcing.py loads only
# ['prec','temp','pres','srad','lrad','wind','shum'] and derives vapour pressure
# from shum + pres. Correcting the case would instead have added 12*N wasted
# reprojections of a variable VIC never reads. These 7 are exactly the
# FORCE_TYPEs in the global parameter file.
VARIABLES_TO_PROCESS = [
    ("wind", "Wind"),
    ("temp", "Temp"),
    ("pres", "Pres"),
    ("shum", "SHum"),
    ("srad", "SRad"),
    ("lrad", "LRad"),
    ("prec", "Prec")
]

# --- Basin/period configuration via environment (KDT 2026-07-09) -----------
# SKILL.md warns YEAR_START/YEAR_END must be edited in three places, and that
# config_paths.py silently does NOT update GRID_NC_PATH. Reading them from the
# environment removes both traps. Defaults reproduce the old hard-coded run.
_BASIN = os.environ.get("VIC_BASIN_NAME", "xixian")
_OUT_ROOT = Path(os.environ.get("VIC_OUT_ROOT", "/mnt/disk1/Hydrocraft_server/outputs"))

YEAR_START = int(os.environ.get("VIC_YEAR_START", 1979))
YEAR_END = int(os.environ.get("VIC_YEAR_END", 1980))

INPUT_DATA_DIR = Path(os.environ.get(
    "VIC_CMFD_DIR", r"/Volumes/Expansion4t/hydro-space2/data/forcing"))
GRID_NC_PATH = _OUT_ROOT / _BASIN / "vic_temp" / "grid" / f"grid_{_BASIN}_025deg.nc"
OUTPUT_DIR = _OUT_ROOT / _BASIN / "vic_temp" / "forcing" / "forcing_1d"
MASK_VAR_NAME = "mask"

# ====================================================================
# --- 1. 初始化 ---
# ====================================================================
warnings.simplefilter(action="ignore", category=FutureWarning)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def open_nc(path: Path) -> xr.Dataset:
    """与土壤参数脚本相同的nc打开方式"""
    try:
        return xr.open_dataset(path, engine="netcdf4")
    except Exception:
        return xr.open_dataset(path, engine="h5netcdf")

print("="*80)
print("CMFD forcing 数据处理脚本（带最近邻外插版）")
print("="*80)
print(f"\n配置信息：")
print(f"  输入路径: {INPUT_DATA_DIR}")
print(f"  Grid NC: {GRID_NC_PATH}")
print(f"  输出路径: {OUTPUT_DIR}")
print(f"  处理年份: {YEAR_START}-{YEAR_END}")

# ====================================================================
# --- 2. 从grid.nc提取格网（与土壤参数脚本完全一致） ---
# ====================================================================
print(f"\n{'─'*80}")
print("步骤1: 从grid.nc提取格网（与土壤参数脚本完全一致）")
print(f"{'─'*80}")

with open_nc(GRID_NC_PATH) as ds_master:
    ds_master = ds_master.rio.write_crs("EPSG:4326")
    
    if MASK_VAR_NAME not in ds_master:
        raise KeyError(f"grid.nc 中未找到 '{MASK_VAR_NAME}' 变量")
    
    # 与土壤参数脚本完全相同的方式
    valid_points = ds_master[MASK_VAR_NAME].stack(gridcell=("y", "x")).dropna("gridcell")
    valid_lats = valid_points.coords["y"].values
    valid_lons = valid_points.coords["x"].values
    num_final_cells = len(valid_lats)
    
    # 读取完整坐标
    full_lats = ds_master["y"].values
    full_lons = ds_master["x"].values
    resolution = abs(full_lats[1] - full_lats[0])
    
    # 读取原始mask
    original_mask = ds_master[MASK_VAR_NAME].values

print(f"✓ 格网提取完成")
print(f"  有效格网: {num_final_cells}")
print(f"  分辨率: {resolution}°")

# ====================================================================
# --- 3. 创建template ---
# ====================================================================
print(f"\n{'─'*80}")
print("步骤2: 创建template")
print(f"{'─'*80}")

min_lon = float(np.min(full_lons))
max_lat = float(np.max(full_lats))
west = min_lon - resolution / 2.0
north = max_lat + resolution / 2.0
transform = from_origin(west, north, resolution, resolution)

template = xr.DataArray(
    np.where(np.isfinite(original_mask), 1.0, np.nan).astype("float32"),
    coords={"y": full_lats, "x": full_lons},
    dims=("y", "x"),
    name="template_mask",
)

template = template.rio.write_crs("EPSG:4326", inplace=False)
template = template.rio.write_transform(transform, inplace=False)
template = template.rio.set_spatial_dims(x_dim="x", y_dim="y", inplace=False)

print(f"✓ Template创建完成")

# ====================================================================
# --- 4. 处理 forcing 文件（带最近邻外插） ---
# ====================================================================
print(f"\n{'─'*80}")
print("步骤3: 开始处理 CMFD forcing 文件（带最近邻外插）")
print(f"{'─'*80}")

total_files = 0
success_files = 0
failed_files = 0
extrapolated_files = 0

for var_prefix, var_dir_name in VARIABLES_TO_PROCESS:
    print(f"\n>>> 正在处理变量: {var_dir_name}")

    var_subdir = INPUT_DATA_DIR / var_dir_name
    
    if not var_subdir.exists():
        print(f"   ✗ 目录不存在: {var_subdir}")
        continue
    
    nc_files = sorted(var_subdir.glob(f"{var_prefix}_*.nc"))
    
    if not nc_files:
        print(f"   ✗ 未找到文件")
        continue

    # 筛选年份
    files_to_process = []
    for nc_file in nc_files:
        m = re.search(r"(19\d{2}|20\d{2})", nc_file.name)
        if m:
            year = int(m.group(1))
            if YEAR_START <= year <= YEAR_END:
                files_to_process.append(nc_file)
    
    print(f"   ✓ 找到 {len(files_to_process)} 个文件")

    for nc_file in files_to_process:
        total_files += 1
        print(f"   [{total_files}] 处理: {nc_file.name}", end="")

        # KDT 2026-07-09: resumability. A basin-wide reprojection of ~1000 CMFD
        # monthly files takes hours; without this, any interruption restarts
        # from zero.
        _base = re.sub(r'_\d{3}deg_', '_025deg_', nc_file.stem)
        _out = OUTPUT_DIR / f"{_base}_{_BASIN}.nc"
        if _out.exists() and _out.stat().st_size > 0:
            print(" ✓ (已存在，跳过)")
            success_files += 1
            continue

        try:
            # dt_vic_023: engine MUST be pinned; a bare open_dataset() triggers
            # xarray's backend-entrypoint probe and SIGSEGVs at interpreter exit.
            xds = open_nc(nc_file)

            if ("lat" in xds.coords) and ("lon" in xds.coords):
                src_lat, src_lon = "lat", "lon"
            elif ("y" in xds.coords) and ("x" in xds.coords):
                src_lat, src_lon = "y", "x"
            else:
                raise KeyError("输入 NC 未找到坐标")

            xds = xds.rio.set_spatial_dims(x_dim=src_lon, y_dim=src_lat, inplace=False)
            xds = xds.rio.write_crs("EPSG:4326", inplace=False)

            # reproject_match
            resampled = xds.rio.reproject_match(template, resampling=Resampling.average)

            # 统一坐标名
            rename_map = {}
            if src_lat != "y" and src_lat in resampled.dims:
                rename_map[src_lat] = "y"
            if src_lon != "x" and src_lon in resampled.dims:
                rename_map[src_lon] = "x"
            if rename_map:
                resampled = resampled.rename(rename_map)

            # ===== 关键改进：检查并填充NaN =====
            needs_extrapolation = False
            for dv in list(resampled.data_vars):
                if ("y" in resampled[dv].dims) and ("x" in resampled[dv].dims):
                    # 检查每个时间步
                    for t in range(resampled[dv].sizes['time']):
                        data_slice = resampled[dv].isel(time=t)
                        
                        # 找出需要填充的位置（mask有效但数据是NaN）
                        mask_valid = np.isfinite(template.values)
                        data_nan = np.isnan(data_slice.values)
                        need_fill = mask_valid & data_nan
                        
                        if need_fill.sum() > 0:
                            needs_extrapolation = True
                            
                            # 使用最近邻填充
                            # 1. 获取有效数据的坐标和值
                            valid_mask = np.isfinite(data_slice.values)
                            valid_y_indices, valid_x_indices = np.where(valid_mask)
                            
                            if len(valid_y_indices) > 0:
                                valid_points = np.column_stack([
                                    full_lats[valid_y_indices],
                                    full_lons[valid_x_indices]
                                ])
                                valid_values = data_slice.values[valid_mask]
                                
                                # 2. 获取需要填充的坐标
                                fill_y_indices, fill_x_indices = np.where(need_fill)
                                fill_points = np.column_stack([
                                    full_lats[fill_y_indices],
                                    full_lons[fill_x_indices]
                                ])
                                
                                # 3. 使用最近邻插值
                                filled_values = griddata(
                                    valid_points,
                                    valid_values,
                                    fill_points,
                                    method='nearest'
                                )
                                
                                # 4. 填充到原数组
                                data_array = resampled[dv].values
                                data_array[t, fill_y_indices, fill_x_indices] = filled_values
                                resampled[dv].values = data_array

            if needs_extrapolation:
                extrapolated_files += 1
                print(f" ✓ (已外插)")
            else:
                print(f" ✓")

            # 输出文件名
            base_name = re.sub(r'_\d{3}deg_', '_025deg_', nc_file.stem)
            output_filename = f"{base_name}_{_BASIN}.nc"
            output_path = OUTPUT_DIR / output_filename

            # 编码
            encoding = {}
            for dv in resampled.data_vars:
                fv = xds[dv].attrs.get("_FillValue", None) if dv in xds.data_vars else None
                if fv is None:
                    fv = -9999
                encoding[dv] = {"_FillValue": fv}

            resampled.to_netcdf(output_path, encoding=encoding)
            xds.close()

            success_files += 1

        except Exception as e:
            print(f" ✗ {e}")
            import traceback
            traceback.print_exc()
            failed_files += 1
            continue

print(f"\n{'='*80}")
print("处理完成！")
print(f"{'='*80}")
print(f"\n统计信息：")
print(f"  总文件数: {total_files}")
print(f"  成功: {success_files}")
print(f"  失败: {failed_files}")
print(f"  使用外插: {extrapolated_files}")
print(f"  成功率: {100*success_files/total_files if total_files > 0 else 0:.1f}%")

print(f"\n关键改进：")
print(f"  ✓ 使用与土壤参数脚本完全相同的格网提取方式")
print(f"  ✓ 自动检测并填充边界格网的NaN")
print(f"  ✓ 使用最近邻方法外插（从最近的陆地点取值）")
print(f"  ✓ 确保所有630个格网都有数据")

print(f"\n说明：")
print(f"  - 格网数: {num_final_cells}")
print(f"  - 外插方法: 最近邻（nearest neighbor）")
print(f"  - 外插来源: 最近的有效陆地格网")
print(f"  - 适用场景: 近海/岛屿格网")

print(f"\n{'='*80}")
