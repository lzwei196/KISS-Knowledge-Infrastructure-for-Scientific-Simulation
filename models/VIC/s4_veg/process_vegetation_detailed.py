# KDT dt_vic_023: netCDF4 MUST be imported before xarray, and every
# xr.open_dataset() MUST pin `engine=`. See diagnostics/triplets.md.
import netCDF4  # noqa: F401  # isort:skip  -- must precede `import xarray`
import xarray as xr
import pandas as pd
import numpy as np
from pathlib import Path
import os
import geopandas as gpd
from shapely.geometry import box
from rasterstats import zonal_stats
import warnings
import rioxarray

# --- 0. 忽略良性的库警告 ---
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message="The 'band' dimension is ignored by rasterio")


def open_nc(path) -> xr.Dataset:
    """Engine-pinned NetCDF read (dt_vic_023).

    Mirrors the shipped siblings s2_forcing/forcing_1d.py,
    s2_forcing/process_forcing.py and s3_soil/fill_parameters1.py. Pinning the
    engine skips xarray's backend-entrypoint probe, which otherwise dlopen's a
    foreign libhdf5 and SIGSEGVs at interpreter exit -- after the data has
    already been read correctly.
    """
    try:
        return xr.open_dataset(path, engine="netcdf4")
    except Exception:
        return xr.open_dataset(path, engine="h5netcdf")

# ====================================================================
# --- 1. 配置路径 ---
# ====================================================================
# 改为使用“流域格网文件(grid.nc)”作为主格网模板
_BASIN = os.environ.get("VIC_BASIN_NAME", "xixian_rerun_71379b42")
_OUT_ROOT = Path(os.environ.get("VIC_OUT_ROOT", "/mnt/disk1/Hydrocraft_server/outputs"))

MASTER_GRID_NC = _OUT_ROOT / _BASIN / "vic_temp" / "grid" / f"grid_{_BASIN}_025deg.nc"

VEG_RASTER_IN = Path(r"/mnt/disk1/Hydrocraft_server/data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif")
VEGLIB_FILE = Path(r"/mnt/disk1/Hydrocraft_server/data/vic_param/veglib.LDAS")
VEG_PARAM_OUT = _OUT_ROOT / _BASIN / "vic_temp" / "veg" / "vic_veg_param_final.txt"

# grid.nc 中变量名（与你生成脚本一致）
MASK_VAR_NAME = "mask"
CELLID_VAR_NAME = "cell_id"

# ====================================================================
# --- 2. 准备工作 ---
# ====================================================================
os.makedirs(VEG_PARAM_OUT.parent, exist_ok=True)
print("处理开始...")

# ====================================================================
# --- 3. 解析植被库文件 ---
# ====================================================================
print(f"正在解析植被库文件: {VEGLIB_FILE.name}")
try:
    lai_lookup = {}
    with open(VEGLIB_FILE, 'r') as f:
        for line in f:
            if line.strip().startswith('#') or not line.strip():
                continue
            parts = line.split()
            veg_class = int(parts[0])
            # veglib 第5-16列是12个月LAI（你的原逻辑）
            lai_values = [f"{float(v):.3f}" for v in parts[4:16]]
            lai_lookup[veg_class] = lai_values
except FileNotFoundError:
    print(f"错误: 找不到植被库文件 {VEGLIB_FILE}。请检查路径。")
    exit()

# 根系参数查找表（保留原样）
root_zone_lookup = {
    0: ['0.1', '0.44', '0.6', '0.45', '0.8', '0.11'], 1: ['0.10', '0.34', '0.6', '0.52', '0.8', '0.14'],
    2: ['0.1', '0.32', '0.6', '0.44', '2.3', '0.23'], 3: ['0.1', '0.34', '0.6', '0.5', '1.3', '0.16'],
    4: ['0.10', '0.31', '0.6', '0.52', '1.3', '0.17'], 5: ['0.10', '0.25', '0.60', '0.52', '1.70', '0.22'],
    6: ['0.10', '0.30', '0.60', '0.5', '2.00', '0.2'], 7: ['0.10', '0.37', '0.60', '0.5', '0.10', '0.3'],
    8: ['0.10', '0.31', '0.60', '0.48', '1.80', '0.21'], 9: ['0.10', '0.33', '0.60', '0.43', '2.40', '0.24'],
    10: ['0.10', '0.36', '0.60', '0.45', '1.70', '0.19'], 11: ['0.10', '0.33', '0.6', '0.55', '0.80', '0.12'],
    12: ['0.1', '0.22', '0.6', '0.46', '3.3', '0.31'], 14: ['0.1', '0.44', '0.6', '0.45', '0.8', '0.11'],
    'default': ['0.10', '0.10', '1.00', '0.70', '0.50', '0.20']
}
print("植被库和根系参数查找表创建完成。")

# ====================================================================
# --- 4. 从 grid.nc 创建主格网（带 cell_id） ---
# ====================================================================
print(f"正在从 {MASTER_GRID_NC.name} 创建主格网...")

try:
    with open_nc(MASTER_GRID_NC) as ds_template:
        # 坐标名兼容：优先 y/x，否则 lat/lon
        if ("y" in ds_template.coords) and ("x" in ds_template.coords):
            lat_name, lon_name = "y", "x"
        elif ("lat" in ds_template.coords) and ("lon" in ds_template.coords):
            lat_name, lon_name = "lat", "lon"
        else:
            raise KeyError("grid.nc 中未找到 (y,x) 或 (lat,lon) 坐标。")

        resolution = float(abs(ds_template[lat_name].values[1] - ds_template[lat_name].values[0]))

        if CELLID_VAR_NAME in ds_template.data_vars:
            da_id = ds_template[CELLID_VAR_NAME]
            stacked = da_id.stack(gridcell=(lat_name, lon_name))
            valid = stacked.where(np.isfinite(stacked), drop=True)

            df_grid = pd.DataFrame({
                "lat": valid.coords[lat_name].values,
                "lon": valid.coords[lon_name].values,
                "cell_id": valid.values.astype(int)
            })
            # 用 cell_id 排序，确保与 soil 框架一致
            df_grid = df_grid.sort_values("cell_id", ascending=True).reset_index(drop=True)

        elif MASK_VAR_NAME in ds_template.data_vars:
            da_mask = ds_template[MASK_VAR_NAME]
            stacked = da_mask.stack(gridcell=(lat_name, lon_name))
            valid = stacked.where(np.isfinite(stacked), drop=True)

            df_grid = pd.DataFrame({
                "lat": valid.coords[lat_name].values,
                "lon": valid.coords[lon_name].values
            })
            # 无 cell_id 时：用 VIC 常用顺序排序并临时编号（不推荐，但可跑通）
            df_grid = df_grid.sort_values(["lat", "lon"], ascending=[False, True]).reset_index(drop=True)
            df_grid["cell_id"] = np.arange(1, len(df_grid) + 1, dtype=int)

        else:
            raise KeyError(f"grid.nc 中未找到 '{CELLID_VAR_NAME}' 或 '{MASK_VAR_NAME}'，无法定义有效格网。")

except Exception as e:
    print(f"错误: 读取/解析 grid.nc 失败: {e}")
    exit()

# 构建格网面 polygon（用于 zonal stats）
polygons = [
    box(lon - resolution / 2, lat - resolution / 2, lon + resolution / 2, lat + resolution / 2)
    for lat, lon in zip(df_grid["lat"].values, df_grid["lon"].values)
]
grid_gdf = gpd.GeoDataFrame(geometry=polygons, crs="EPSG:4326")
grid_gdf["lat"] = df_grid["lat"].values
grid_gdf["lon"] = df_grid["lon"].values
grid_gdf["cell_id"] = df_grid["cell_id"].values

print(f"主格网有效单元格数量为: {len(grid_gdf)}。resolution = {resolution}")

# ====================================================================
# --- 5. 执行空间统计 ---
# ====================================================================
try:
    with rioxarray.open_rasterio(VEG_RASTER_IN) as rds:
        if str(rds.rio.crs) != str(grid_gdf.crs):
            grid_gdf = grid_gdf.to_crs(rds.rio.crs)
except Exception as e:
    print(f"错误: 读取植被栅格时出错。 {e}")
    exit()

print("正在对高分辨率植被图进行空间统计 (这可能需要一些时间)...")
# 关键：不指定 nodata=0，让水体(ID=0)参与统计（保持你原逻辑）
stats = zonal_stats(grid_gdf, str(VEG_RASTER_IN), categorical=True, geojson_out=True)
print("空间统计完成。")

# ====================================================================
# --- 6. 整理统计结果并生成最终文件 ---
# ====================================================================
print(f"正在生成VIC植被参数文件: {VEG_PARAM_OUT.name}\n")

stats_gdf = gpd.GeoDataFrame.from_features(stats)

# zonal_stats 返回的 features 顺序与传入 grid_gdf 顺序一致；为保险起见，重新附上 cell_id/lat/lon
# 有些版本的 rasterstats 可能不会把原属性完整回写，这里显式覆盖
stats_gdf["cell_id"] = grid_gdf["cell_id"].values
stats_gdf["lat"] = grid_gdf["lat"].values
stats_gdf["lon"] = grid_gdf["lon"].values

# 输出顺序：严格按 cell_id（推荐，最稳定）
stats_gdf = stats_gdf.sort_values(by=["cell_id"], ascending=[True]).reset_index(drop=True)

output_lines = []
for _, row in stats_gdf.iterrows():
    cell_id = int(row["cell_id"])

    # rasterstats 的 categorical 输出一般是 {类别ID: 像元数}，键可能是 int 或 str
    properties = {}
    for k, v in row.items():
        if pd.isna(v):
            continue
        if isinstance(k, int):
            properties[k] = v
        elif isinstance(k, str) and k.isdigit():
            properties[int(k)] = v

    # 剔除裸地(ID 16)
    if 16 in properties:
        del properties[16]

    total_pixels = sum(properties.values())
    if total_pixels == 0:
        continue  # 剔除裸地后没有其他类型则跳过

    veg_fractions = {veg_code: count / total_pixels for veg_code, count in properties.items()}

    # 过滤占比 < 0.03
    filtered_veg = {code: frac for code, frac in veg_fractions.items() if frac >= 0.03}
    if not filtered_veg:
        continue

    # 归一化
    final_total_fraction = sum(filtered_veg.values())
    final_veg_info = {code: frac / final_total_fraction for code, frac in filtered_veg.items()}

    line_block = []
    line_block.append(f"{cell_id}\t{len(final_veg_info)}")

    for veg_class, fraction in final_veg_info.items():
        root_params = root_zone_lookup.get(veg_class, root_zone_lookup["default"])
        lai_params = lai_lookup.get(veg_class)
        if lai_params is None:
            continue

        line_block.append(f"\t \t{veg_class}\t{fraction:.2f}\t{' '.join(root_params)}")
        lai_string = "\t".join(lai_params)
        line_block.append(f"  \t \t {lai_string}")

    if len(line_block) > 1:
        output_lines.append("\n".join(line_block))

# ====================================================================
# --- 7. 写入文件 ---
# ====================================================================
if output_lines:
    with open(VEG_PARAM_OUT, "w") as f:
        f.write("\n".join(output_lines))
        f.write("\n")
    print(f"\n处理成功完成！共为 {len(output_lines)} 个有效格网生成了参数。")
else:
    print("\n处理完成，但未能生成任何有效的植被参数。输出文件为空。")
