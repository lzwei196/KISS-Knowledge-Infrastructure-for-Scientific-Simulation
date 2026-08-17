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
from rasterio.enums import Resampling
import rasterio

# --- 0. 忽略良性的库警告 ---
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message="The 'band' dimension is ignored by rasterio")

# --- 1. 配置核心输入路径 ---
_BASIN = os.environ.get("VIC_BASIN_NAME", "xixian_rerun_71379b42")
_OUT_ROOT = Path(os.environ.get("VIC_OUT_ROOT", "KISSPATH_OUTPUTS"))

MASTER_GRID_NC = _OUT_ROOT / _BASIN / "vic_temp" / "grid" / f"grid_{_BASIN}_025deg.nc"
# KDT 2026-07-09 — these three were hard-coded to CHINA-ONLY rasters. Outside the
# CMFD domain the elevation lookup silently returned the nearest *Chinese* cell's
# elevation (sel(method="nearest") never fails), which is a wrong number rather
# than an error. They are now env-configurable; defaults reproduce the China runs.
ELEV_NC_IN = Path(os.environ.get(
    "VIC_ELEV_NC",
    r"KISSPATH_DATA/elev/elev_CMFD_V0200_B-00_fx_010deg.nc"))
PREC_ANNUAL_NC = Path(os.environ.get(
    "VIC_PREC_ANNUAL_NC",
    r"KISSPATH_DATA/his_average_prec/prec_CMFD_010deg_meanAnnual_1951-2020_mm.nc"))
SOIL_RASTER_IN = Path(os.environ.get(
    "VIC_SOIL_RASTER",
    r"KISSPATH_STATIC/HWSD_China_Geo.img"))

# --- 2. 配置输出路径 ---
OUTPUT_DIR = _OUT_ROOT / _BASIN / "vic_temp" / "soil"
SOIL_PARAM_OUT = OUTPUT_DIR / "SOIL_PARAM_FINAL.txt"

# --- 3. 准备工作 ---
os.makedirs(OUTPUT_DIR, exist_ok=True)
print("土壤参数生成脚本开始...")

def open_nc(path: Path) -> xr.Dataset:
    """尽量稳健地打开 netCDF（优先 netcdf4，失败再 h5netcdf）"""
    try:
        return xr.open_dataset(path, engine="netcdf4")
    except Exception:
        return xr.open_dataset(path, engine="h5netcdf")

# --- 4. 定义主格网 ---
print(f"正在从 {MASTER_GRID_NC.name} 定义主格网...")
with open_nc(MASTER_GRID_NC) as ds_master:
    ds_master = ds_master.rio.write_crs("EPSG:4326")

    # 使用 mask 变量识别有效格点
    if "mask" not in ds_master:
        raise KeyError("MASTER_GRID_NC 中未找到 'mask' 变量，请检查 grid_025deg.nc 内容。")

    valid_points = ds_master["mask"].stack(gridcell=("y", "x")).dropna("gridcell")
    lats = valid_points.coords["y"].values
    lons = valid_points.coords["x"].values
    num_final_cells = len(lats)

    # 读取分辨率
    resolution = abs(ds_master["y"].values[1] - ds_master["y"].values[0])

print(f"主格网已确定！有效单元格数量为: {num_final_cells}，分辨率为: {resolution}度。")

# --- 5. 生成并填充土壤参数文件 ---
print("\n--- 正在构建并填充土壤参数文件 ---")
df_soil = pd.DataFrame(index=range(num_final_cells), columns=[f"col_{i+1}" for i in range(53)], dtype=object)
df_soil.iloc[:, 0] = 1
df_soil.iloc[:, 1] = np.arange(1, num_final_cells + 1)
df_soil.iloc[:, 2] = lats
df_soil.iloc[:, 3] = lons
print("基础信息填充完毕。")

# 5.1 使用逐点查找法填充高程
print("正在使用逐点查找法填充高程值...")
if ELEV_NC_IN.exists():
    with open_nc(ELEV_NC_IN) as ds_elev_raw:
        elev_var = list(ds_elev_raw.data_vars)[0]

        # 适配坐标维度名称
        if "lat" in ds_elev_raw.coords and "lon" in ds_elev_raw.coords:
            lat_dim, lon_dim = "lat", "lon"
        elif "y" in ds_elev_raw.coords and "x" in ds_elev_raw.coords:
            lat_dim, lon_dim = "y", "x"
        else:
            raise KeyError("高程 nc 未找到 lat/lon 或 y/x 坐标。")

        elev_values = []
        for i in range(num_final_cells):
            lat, lon = lats[i], lons[i]
            try:
                val = ds_elev_raw[elev_var].sel({lat_dim: lat, lon_dim: lon}, method="nearest").item()
                elev_values.append(0.0 if pd.isna(val) else float(val))
            except Exception:
                elev_values.append(0.0)

    df_soil["col_22"] = elev_values
    print("高程值填充完毕！")
else:
    print(f"⚠️  高程文件不存在: {ELEV_NC_IN}")
    print("   使用默认高程值: 100.0 m")
    df_soil["col_22"] = 100.0
    print("高程值填充完毕（使用默认值）！")

# 5.2 填充年平均降水（mm/year）
print("正在填充年平均降水...")
try:
    with open_nc(PREC_ANNUAL_NC) as ds_prec_raw, open_nc(MASTER_GRID_NC) as ds_template:
        ds_template = ds_template.rio.write_crs("EPSG:4326")

        # 变量名
        if "prec_mean_annual" in ds_prec_raw.data_vars:
            prec_var = "prec_mean_annual"
        else:
            prec_var = list(ds_prec_raw.data_vars)[0]

        ds_prec_raw = ds_prec_raw.rio.write_crs("EPSG:4326")

        # 坐标改名为 y/x 以便 rioxarray 重投影匹配
        if "lat" in ds_prec_raw.coords and "lon" in ds_prec_raw.coords:
            ds_prec_raw = ds_prec_raw.rename({"lat": "y", "lon": "x"})

        print(f"  正在将降水数据从 0.1° 重采样到 {resolution}°...")
        reprojected_prec = ds_prec_raw[prec_var].rio.reproject_match(ds_template, resampling=Resampling.average)

        lats_to_find = xr.DataArray(lats, dims="points")
        lons_to_find = xr.DataArray(lons, dims="points")
        prec_values = reprojected_prec.sel(y=lats_to_find, x=lons_to_find, method="nearest")

        # 缺测处理：<=0、-9999、NaN 都置 0
        prec_values_filled = prec_values.where(
            (prec_values != -9999.0) & (prec_values > 0),
            0.0
        ).fillna(0.0)

        df_soil["col_49"] = prec_values_filled.values
        print(f"  年平均降水范围: {prec_values_filled.min().item():.1f} - {prec_values_filled.max().item():.1f} mm/year")

except Exception as e:
    print(f"警告：未能成功读取年平均降水文件，将使用-9999填充。错误: {e}")
    df_soil["col_49"] = -9999.0

print("年平均降水填充完毕。")

# 5.3 获取主导土壤类型（HWSD）
print("\n--- 正在从HWSD栅格中提取主导土壤类型 ---")
half_res = resolution / 2
grid_gdf = gpd.GeoDataFrame(
    geometry=[box(lon - half_res, lat - half_res, lon + half_res, lat + half_res)
              for lat, lon in zip(lats, lons)],
    crs="EPSG:4326"
)

try:
    # 读取栅格 CRS 与 nodata
    with rasterio.open(str(SOIL_RASTER_IN)) as src:
        raster_crs = src.crs
        nodata = src.nodata
        if nodata is None:
            # 读不到就给一个合理兜底（很多分类栅格用 0 表示无效）
            nodata = 0

        # 验证 band 数量（你这个文件只有 1 个 band）
        band_count = src.count
        if band_count < 1:
            raise RuntimeError("SOIL_RASTER_IN 没有可用波段。")

    # CRS 对齐
    if raster_crs is not None and str(raster_crs) != str(grid_gdf.crs):
        grid_gdf = grid_gdf.to_crs(raster_crs)

    # 只用 band=1（修复你现在的 band=2 越界错误）
    stats_t = zonal_stats(
        grid_gdf,
        str(SOIL_RASTER_IN),
        band=1,
        stats="majority",
        nodata=nodata
    )
    soil_code_t = [s["majority"] if s.get("majority") is not None else 1 for s in stats_t]

    # 底层同一土壤类型（因为只有一个波段，无法提供第二层）
    soil_code_s = soil_code_t.copy()

except Exception as e:
    print(f"错误: 空间统计失败，将使用默认土壤类型ID '1'。错误: {e}")
    soil_code_t = [1] * num_final_cells
    soil_code_s = [1] * num_final_cells

print("主导土壤类型提取完毕。")

# 5.4 根据R代码逻辑填充剩余参数
print("\n--- 正在根据R代码逻辑填充所有剩余参数 ---")
mdata = {
    1:[1,0,0,0,0,0], 2:[2,708,0.37,0.25,21.868,1400], 3:[3,763.2,0.36,0.17,27.691,1260],
    4:[4,1096.8,0.36,0.21,15.195,0], 5:[5,424.8,0.34,0.21,16.888,1350], 6:[6,2061.6,0.28,0.08,8.509,0],
    7:[7,950.4,0.32,0.12,11.064,1380], 8:[8,285.6,0.31,0.23,12.302,0], 9:[9,472.8,0.29,0.14,13.362,1410],
    10:[10,576,0.27,0.17,18.152,1410], 11:[11,1257.6,0.21,0.09,12.524,1480], 12:[12,2608.8,0.15,0.06,11.888,1660],
    13:[13,9218.4,0.08,0.03,11.734,1740]
}

df_soil[['col_5', 'col_6', 'col_7', 'col_8', 'col_9']] = [0.3, 0.02, 10.00, 0.7, 2]
df_soil[['col_47', 'col_48']] = [0.01, 0.03]
df_soil[['col_16','col_17','col_18','col_19','col_20','col_24','col_25','col_28','col_29','col_30','col_31','col_32','col_33']] = -9999.0
df_soil[['col_23', 'col_27', 'col_37', 'col_38', 'col_39', 'col_50', 'col_51', 'col_52', 'col_53']] = [0.1, 4.0, 2685, 2685, 2685, 0, 0, 0, 0]

df_soil['col_10'] = [mdata.get(int(tid), mdata[1])[4] for tid in soil_code_t]
df_soil['col_11'] = df_soil['col_10']
df_soil['col_12'] = [mdata.get(int(tid), mdata[1])[4] for tid in soil_code_s]

df_soil['col_13'] = [mdata.get(int(tid), mdata[1])[1] for tid in soil_code_t]
df_soil['col_14'] = df_soil['col_13']
df_soil['col_15'] = [mdata.get(int(tid), mdata[1])[1] for tid in soil_code_s]

df_soil['col_34'] = [mdata.get(int(tid), mdata[1])[5] for tid in soil_code_t]
df_soil['col_35'] = df_soil['col_34']
df_soil['col_36'] = [mdata.get(int(tid), mdata[1])[5] for tid in soil_code_s]

df_soil['col_41'] = [mdata.get(int(tid), mdata[1])[2] for tid in soil_code_t]
df_soil['col_42'] = df_soil['col_41']
df_soil['col_43'] = [mdata.get(int(tid), mdata[1])[2] for tid in soil_code_s]

df_soil['col_44'] = [mdata.get(int(tid), mdata[1])[3] for tid in soil_code_t]
df_soil['col_45'] = df_soil['col_44']
df_soil['col_46'] = [mdata.get(int(tid), mdata[1])[3] for tid in soil_code_s]

# 计算时区偏移（基于经度）
df_soil['col_40'] = (df_soil['col_4'].astype(float) * 24 / 360).round(1)

print("所有参数填充完毕。")

# 5.5 按精确格式保存最终文件
print(f"\n正在写入最终土壤参数文件: {SOIL_PARAM_OUT.name}")
with open(SOIL_PARAM_OUT, 'w') as f:
    for _, row in df_soil.iterrows():
        formatted_items = []
        for i, item in enumerate(row):
            col_index = i + 1
            if col_index in [1, 2, 37, 38, 39, 53]:
                formatted_items.append(str(int(float(item))))
            elif col_index in [3, 4]:
                formatted_items.append(f"{float(item):.4f}")
            elif col_index == 22:
                formatted_items.append(f"{float(item):.2f}")
            else:
                num = float(item)
                if num == -9999.0:
                    formatted_items.append("-9999")
                else:
                    formatted_items.append(f"{num:.3f}")
        f.write(" ".join(formatted_items) + "\n")

print(f"土壤参数文件生成成功！输出文件: {SOIL_PARAM_OUT}")
print(f"共生成 {num_final_cells} 个格网的土壤参数。")
print("\n处理成功完成！")