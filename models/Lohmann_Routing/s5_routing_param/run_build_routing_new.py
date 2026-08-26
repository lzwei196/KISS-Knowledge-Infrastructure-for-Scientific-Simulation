# -*- coding: utf-8 -*-
"""
VIC Routing参数自动制备脚本
使用"先计算后修复"的两阶段策略确保流向网络全连通

使用方法：
1. 修改下方配置参数
2. 运行脚本: python run_build_routing_new.py
"""

import os
import numpy as np
import rasterio
from rasterio.mask import mask
import geopandas as gpd
from shapely.geometry import box, mapping
import whitebox
from collections import defaultdict

# ============================================================================
# 配置参数 - 根据实际情况修改
# ============================================================================

# 输入文件
SOIL_PARAM_PATH = "KISSPATH_OUTPUTS/hefei_2000-2001/vic_temp/soil/SOIL_PARAM_COMPLETE.txt"  # VIC土壤参数文件
DEM_PATH = "KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif"  # DEM文件
BASIN_SHP = "KISSPATH_DATA/shp/hefei_shp/hefei_boundary_shp/hefei_boundary.shp"  # 流域边界shapefile

# 输出目录
OUTPUT_DIR = "KISSPATH_OUTPUTS/hefei_2000-2001/routing_param"

# 参数配置
CELL_SIZE = 0.25  # VIC网格分辨率（度）
NODATA_VALUE = 0  # 无数据值
STATION_NAME = "HF"  # 站点名称（合肥/Chaohu outlet）

# 出口站点坐标（经度, 纬度）- 自动计算
OUTLET_LON = 0.0  # 出口经度（自动计算）
OUTLET_LAT = 0.0  # 出口纬度（自动计算）

# 流速和扩散系数
VELOCITY = 1.5  # m/s
DIFFUSIVITY = 800  # m²/s

# WhiteboxTools路径
WBT_DIR = "KISSPATH_HOME/.local/lib/python3.12/site-packages/whitebox/WBT"

# ============================================================================
# 工具函数
# ============================================================================

def read_vic_grid_from_soil(soil_path):
    """从土壤参数文件读取VIC网格坐标"""
    lats, lons = [], []
    with open(soil_path, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 4:
                lats.append(float(parts[2]))  # 第3列是纬度
                lons.append(float(parts[3]))  # 第4列是经度
    return np.array(lats), np.array(lons)


def compute_grid_params(lats, lons, cellsize):
    """计算网格参数"""
    lon_min, lon_max = lons.min(), lons.max()
    lat_min, lat_max = lats.min(), lats.max()
    xllcorner = lon_min - cellsize / 2
    yllcorner = lat_min - cellsize / 2
    ncols = int(round((lon_max - lon_min) / cellsize)) + 1
    nrows = int(round((lat_max - lat_min) / cellsize)) + 1
    return {
        'ncols': ncols, 'nrows': nrows,
        'xllcorner': xllcorner, 'yllcorner': yllcorner,
        'cellsize': cellsize, 'nodata': NODATA_VALUE
    }


def create_mask_from_coords(lats, lons, grid_params):
    """从坐标创建掩膜"""
    nrows, ncols = grid_params['nrows'], grid_params['ncols']
    xll, yll, cs = grid_params['xllcorner'], grid_params['yllcorner'], grid_params['cellsize']
    mask_grid = np.zeros((nrows, ncols), dtype=np.int32)
    for lat, lon in zip(lats, lons):
        col = int(round((lon - xll - cs/2) / cs))
        row = nrows - 1 - int(round((lat - yll - cs/2) / cs))
        if 0 <= row < nrows and 0 <= col < ncols:
            mask_grid[row, col] = 1
    return mask_grid


def write_ascii_grid(filepath, data, grid_params, fmt="{:.2f}"):
    """写入ASCII格式网格文件"""
    with open(filepath, 'w') as f:
        f.write(f"ncols         {grid_params['ncols']}\n")
        f.write(f"nrows         {grid_params['nrows']}\n")
        f.write(f"xllcorner     {grid_params['xllcorner']}\n")
        f.write(f"yllcorner     {grid_params['yllcorner']}\n")
        f.write(f"cellsize      {grid_params['cellsize']}\n")
        f.write(f"NODATA_value  {grid_params['nodata']}\n")
        for row in range(grid_params['nrows']):
            values = [fmt.format(data[row, col]) for col in range(grid_params['ncols'])]
            f.write(" ".join(values) + "\n")


def build_fraction_grid(shp_path, grid_params, vic_mask):
    """计算每个网格的面积比例"""
    gdf = gpd.read_file(shp_path)
    basin_geom = gdf.union_all() if hasattr(gdf, 'union_all') else gdf.geometry.unary_union
    nrows, ncols = grid_params['nrows'], grid_params['ncols']
    xll, yll, cs = grid_params['xllcorner'], grid_params['yllcorner'], grid_params['cellsize']
    frac = np.zeros((nrows, ncols), dtype=np.float32)
    for row in range(nrows):
        for col in range(ncols):
            if vic_mask[row, col] == 0:
                continue
            x_min = xll + col * cs
            x_max = x_min + cs
            y_max = yll + (nrows - row) * cs
            y_min = y_max - cs
            cell_box = box(x_min, y_min, x_max, y_max)
            try:
                intersection = basin_geom.intersection(cell_box)
                if not intersection.is_empty:
                    frac[row, col] = intersection.area / cell_box.area
            except:
                pass
    return frac


def crop_dem_to_basin(dem_path, shp_path, output_dir):
    """裁剪DEM到流域范围"""
    output_path = os.path.join(output_dir, "dem_crop.tif")
    if os.path.exists(output_path):
        print(f"  使用已有裁剪DEM")
        return output_path
    gdf = gpd.read_file(shp_path)
    bounds = gdf.total_bounds
    buffer = 0.5
    extended_bounds = [bounds[0]-buffer, bounds[1]-buffer, bounds[2]+buffer, bounds[3]+buffer]
    clip_geom = [mapping(box(*extended_bounds))]
    with rasterio.open(dem_path) as src:
        out_image, out_transform = mask(src, clip_geom, crop=True)
        out_meta = src.meta.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform
        })
        with rasterio.open(output_path, "w", **out_meta) as dest:
            dest.write(out_image)
    print(f"  DEM裁剪完成")
    return output_path


def compute_flow_direction_and_accum(dem_path, output_dir):
    """使用WhiteboxTools计算流向和累积量"""
    wbt = whitebox.WhiteboxTools()
    wbt.set_whitebox_dir(WBT_DIR)
    wbt.verbose = False

    dem_filled = os.path.join(output_dir, "dem_filled.tif")
    d8_pointer = os.path.join(output_dir, "d8_pointer.tif")
    accum = os.path.join(output_dir, "accum.tif")

    if not os.path.exists(dem_filled):
        print("  填充洼地...")
        wbt.fill_depressions(dem_path, dem_filled)

    if not os.path.exists(d8_pointer):
        print("  计算D8流向...")
        wbt.d8_pointer(dem_filled, d8_pointer)

    if not os.path.exists(accum):
        print("  计算汇流累积量...")
        wbt.d8_flow_accumulation(dem_filled, accum, out_type="cells")

    return d8_pointer, accum


def _aggregate_raster_to_vic_grid(raster_path, frac, grid_params, agg='max'):
    """将高分辨率栅格聚合到VIC网格

    agg: 'max' 取最大值（用于累积量）, 'min' 取最小值（用于高程）
    """
    with rasterio.open(raster_path) as src:
        data = src.read(1)
        transform = src.transform

    nrows, ncols = grid_params['nrows'], grid_params['ncols']
    xll, yll, cs = grid_params['xllcorner'], grid_params['yllcorner'], grid_params['cellsize']
    result = np.full((nrows, ncols), np.nan)

    for row in range(nrows):
        for col in range(ncols):
            if frac[row, col] <= 0:
                continue
            x_min = xll + col * cs
            x_max = x_min + cs
            y_max = yll + (nrows - row) * cs
            y_min = y_max - cs

            px_c0 = int((x_min - transform.c) / transform.a)
            px_c1 = int((x_max - transform.c) / transform.a)
            px_r0 = int((transform.f - y_max) / (-transform.e))
            px_r1 = int((transform.f - y_min) / (-transform.e))

            px_c0, px_c1 = max(0, px_c0), min(data.shape[1], px_c1)
            px_r0, px_r1 = max(0, px_r0), min(data.shape[0], px_r1)

            if px_r0 < px_r1 and px_c0 < px_c1:
                subset = data[px_r0:px_r1, px_c0:px_c1]
                valid = subset[np.isfinite(subset) & (subset > -9999)]
                if agg == 'max':
                    valid = valid[valid > 0]
                if len(valid) > 0:
                    result[row, col] = np.max(valid) if agg == 'max' else np.min(valid)

    return result


def aggregate_accum_to_vic_grid(accum_path, frac, grid_params):
    """将高分辨率累积量聚合到VIC网格（取最大值）"""
    result = _aggregate_raster_to_vic_grid(accum_path, frac, grid_params, agg='max')
    result[np.isnan(result)] = 0
    return result


def aggregate_dem_to_vic_grid(dem_path, frac, grid_params):
    """将高分辨率DEM聚合到VIC网格（取最小值 = 格点最低高程）"""
    result = _aggregate_raster_to_vic_grid(dem_path, frac, grid_params, agg='min')
    return result


def compute_direction_with_fix(vic_accum, frac, grid_params, vic_elev=None):
    """
    两阶段流向计算：先基于累积量计算，后迭代修复断开格点

    出口确定策略：
    - 如果提供了DEM高程(vic_elev)，使用最低高程点作为出口（更准确，尤其对小流域）
    - 否则回退到最大累积量（旧方法）

    阶段1：基于累积量计算初始流向
    - 每个格点流向其8邻域中累积量最大且大于自身的邻居

    阶段2：迭代修复
    - 检测不能到达出口的格点
    - 将其流向设置为能到达出口的邻居中累积量最大者
    - 重复直到所有格点连通或无法继续修复
    """
    nrows, ncols = grid_params['nrows'], grid_params['ncols']

    # D8方向编码: 1=N, 2=NE, 3=E, 4=SE, 5=S, 6=SW, 7=W, 8=NW
    dir_offsets = {
        1: (-1, 0), 2: (-1, 1), 3: (0, 1), 4: (1, 1),
        5: (1, 0), 6: (1, -1), 7: (0, -1), 8: (-1, -1)
    }

    direction = np.zeros((nrows, ncols), dtype=np.int32)

    # 阶段1：基于累积量计算初始流向
    print("  阶段1：计算初始流向...")
    for row in range(nrows):
        for col in range(ncols):
            if frac[row, col] <= 0:
                continue
            cur_acc = vic_accum[row, col]
            best_dir = 0
            max_acc = cur_acc
            for d, (dr, dc) in dir_offsets.items():
                nr, nc = row + dr, col + dc
                if 0 <= nr < nrows and 0 <= nc < ncols:
                    if frac[nr, nc] > 0 and vic_accum[nr, nc] > max_acc:
                        max_acc = vic_accum[nr, nc]
                        best_dir = d
            direction[row, col] = best_dir

    # 找出口：优先使用DEM最低高程，回退到最大累积量
    if vic_elev is not None:
        # 用DEM最低点：将无效格点设为极大值，然后找最小值
        elev_masked = np.where(frac > 0, vic_elev, np.inf)
        elev_masked = np.where(np.isnan(elev_masked), np.inf, elev_masked)
        outlet_idx = np.unravel_index(np.argmin(elev_masked), elev_masked.shape)
        xll, yll, cs = grid_params['xllcorner'], grid_params['yllcorner'], grid_params['cellsize']
        out_lon = xll + (outlet_idx[1] + 0.5) * cs
        out_lat = yll + (nrows - outlet_idx[0] - 0.5) * cs
        print(f"  出口确定方式：DEM最低高程 ({vic_elev[outlet_idx]:.1f}m)")
        print(f"  出口位置：行{outlet_idx[0]}, 列{outlet_idx[1]} ({out_lon:.4f}°E, {out_lat:.4f}°N)")
    else:
        outlet_idx = np.unravel_index(np.argmax(vic_accum * (frac > 0)), vic_accum.shape)
        print(f"  出口确定方式：最大累积量 ({vic_accum[outlet_idx]:.0f})")
    outlet_row, outlet_col = outlet_idx
    direction[outlet_row, outlet_col] = -88

    # 追踪函数
    def trace_to_outlet(r, c):
        visited = set()
        for _ in range(500):
            if (r, c) in visited:
                return False
            visited.add((r, c))
            if r == outlet_row and c == outlet_col:
                return True
            d = direction[r, c]
            if d == -88:
                return True
            if d not in dir_offsets:
                return False
            dr, dc = dir_offsets[d]
            r, c = r + dr, c + dc
            if not (0 <= r < nrows and 0 <= c < ncols):
                return False
        return False

    # 统计初始连通性
    total = sum(1 for r in range(nrows) for c in range(ncols) if frac[r, c] > 0)
    reaching = sum(1 for r in range(nrows) for c in range(ncols)
                   if frac[r, c] > 0 and trace_to_outlet(r, c))
    print(f"    初始连通: {reaching}/{total}")

    # 阶段2：迭代修复断开的格点
    if reaching < total:
        print("  阶段2：修复断开格点...")
        for iteration in range(50):  # 最多50轮迭代
            fixed = 0
            for row in range(nrows):
                for col in range(ncols):
                    if frac[row, col] <= 0:
                        continue
                    if trace_to_outlet(row, col):
                        continue  # 已连通

                    # 找能到达出口的邻居中累积量最大的
                    best_dir = 0
                    max_acc = -1
                    for d, (dr, dc) in dir_offsets.items():
                        nr, nc = row + dr, col + dc
                        if 0 <= nr < nrows and 0 <= nc < ncols:
                            if frac[nr, nc] > 0 and trace_to_outlet(nr, nc):
                                if vic_accum[nr, nc] > max_acc:
                                    max_acc = vic_accum[nr, nc]
                                    best_dir = d

                    if best_dir != 0:
                        direction[row, col] = best_dir
                        fixed += 1

            if fixed == 0:
                break
            print(f"    迭代 {iteration+1}: 修复 {fixed} 个格点")

        reaching = sum(1 for r in range(nrows) for c in range(ncols)
                       if frac[r, c] > 0 and trace_to_outlet(r, c))
        print(f"    最终连通: {reaching}/{total}")

    return direction, outlet_row, outlet_col


def compute_xmask(direction, frac, dx=22849, dy=27734, diag=35956):
    """计算流动距离"""
    nrows, ncols = direction.shape
    xmask = np.zeros((nrows, ncols), dtype=np.float32)
    dir_dist = {1: dy, 2: diag, 3: dx, 4: diag, 5: dy, 6: diag, 7: dx, 8: diag}
    for row in range(nrows):
        for col in range(ncols):
            if frac[row, col] > 0:
                d = direction[row, col]
                xmask[row, col] = dir_dist.get(abs(d), dx)
    return xmask


def write_staloc(filepath, station_name, outlet_row, outlet_col, nrows):
    """写入站点位置文件（包含必需的第二行）"""
    staloc_col = outlet_col + 1  # 从1开始
    staloc_row = nrows - outlet_row  # 从下往上
    with open(filepath, 'w') as f:
        f.write(f"1 {station_name} {staloc_col} {staloc_row} -9999\n")
        f.write("NONE\n")  # 第二行必须有，NONE表示重新计算UH_S


def write_uh_file(filepath):
    """写入单位线文件（12行格式）"""
    uh_values = [0.15, 0.40, 0.25, 0.10, 0.06, 0.03, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0]
    with open(filepath, 'w') as f:
        for i, val in enumerate(uh_values):
            f.write(f"   {i}   {val:.2f}\n")


def write_rout_global(filepath, grid_params, station_name, start_year=1979, end_year=1990):
    """写入routing全局参数文件"""
    content = f"""# Routing Information File for {station_name}
# NAME OF FLOW DIRECTION FILE
./{station_name}_direc.txt
# NAME OF VELOCITY FILE
.false.
{VELOCITY}
# NAME OF DIFF FILE
.false.
{DIFFUSIVITY}
# NAME OF XMASK FILE
.true.
./{station_name}_xmask.txt
# NAME OF FRACTION FILE
.true.
./{station_name}_frac.txt
# NAME OF STATION FILE
./{station_name}_staloc.txt
# PATH OF INPUT FILES AND PRECISION
./vic_in/fluxes_
4
# PATH OF OUTPUT FILES
./rout_out/
# YEAR AND MONTH OF VIC OUTPUT TO ROUTE & ROUTED OUTPUT TO WRITE
{start_year} 01 {end_year} 12
{start_year} 01 {end_year} 12
# NAME OF UNIT HYDROGRAPH FILE
./UH.all
"""
    with open(filepath, 'w') as f:
        f.write(content)


# ============================================================================
# 主程序
# ============================================================================

def main():
    print("=" * 60)
    print("VIC Routing参数自动制备")
    print("=" * 60)

    # 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    temp_dir = os.path.join(OUTPUT_DIR, "temp")
    os.makedirs(temp_dir, exist_ok=True)

    # Step 1: 读取VIC网格
    print("\n[1] 读取VIC网格...")
    vic_lats, vic_lons = read_vic_grid_from_soil(SOIL_PARAM_PATH)
    print(f"  网格点数: {len(vic_lats)}")
    print(f"  经度范围: {vic_lons.min():.4f} - {vic_lons.max():.4f}")
    print(f"  纬度范围: {vic_lats.min():.4f} - {vic_lats.max():.4f}")

    # Step 2: 计算网格参数
    print("\n[2] 计算网格参数...")
    grid_params = compute_grid_params(vic_lats, vic_lons, CELL_SIZE)
    print(f"  行数×列数: {grid_params['nrows']} × {grid_params['ncols']}")
    print(f"  左下角: ({grid_params['xllcorner']}, {grid_params['yllcorner']})")

    # Step 3: 创建掩膜
    print("\n[3] 创建网格掩膜...")
    vic_mask = create_mask_from_coords(vic_lats, vic_lons, grid_params)
    print(f"  有效格点: {vic_mask.sum()}")

    # Step 4: 计算面积比例
    print("\n[4] 计算面积比例...")
    frac = build_fraction_grid(BASIN_SHP, grid_params, vic_mask)
    valid_frac = (frac > 0).sum()
    print(f"  有效格点: {valid_frac}")

    # Step 5: 裁剪DEM
    print("\n[5] 裁剪DEM...")
    dem_crop = crop_dem_to_basin(DEM_PATH, BASIN_SHP, temp_dir)

    # Step 6: 计算高分辨率流向和累积量
    print("\n[6] 计算高分辨率流向...")
    d8_pointer, accum = compute_flow_direction_and_accum(dem_crop, temp_dir)

    # Step 7: 聚合累积量到VIC网格
    print("\n[7] 聚合累积量...")
    vic_accum = aggregate_accum_to_vic_grid(accum, frac, grid_params)
    print(f"  最大累积量: {vic_accum.max():.0f}")

    # Step 7b: 聚合DEM高程到VIC网格（取最低值，用于确定出口）
    print("\n[7b] 聚合DEM高程...")
    vic_elev = aggregate_dem_to_vic_grid(dem_crop, frac, grid_params)
    valid_elev = vic_elev[~np.isnan(vic_elev)]
    if len(valid_elev) > 0:
        print(f"  高程范围: {valid_elev.min():.1f}m - {valid_elev.max():.1f}m")

    # Step 8: 计算VIC流向（两阶段：先计算后修复）
    print("\n[8] 计算VIC流向...")
    direction, outlet_row, outlet_col = compute_direction_with_fix(vic_accum, frac, grid_params, vic_elev=vic_elev)

    # Step 9: 计算xmask
    print("\n[9] 计算流动距离...")
    xmask = compute_xmask(direction, frac)

    # Step 10: 输出文件
    print("\n[10] 输出参数文件...")

    write_ascii_grid(os.path.join(OUTPUT_DIR, f"{STATION_NAME}_direc.txt"),
                     direction, grid_params, fmt="{:.0f}")
    print(f"  {STATION_NAME}_direc.txt")

    write_ascii_grid(os.path.join(OUTPUT_DIR, f"{STATION_NAME}_frac.txt"),
                     frac, grid_params, fmt="{:.2f}")
    print(f"  {STATION_NAME}_frac.txt")

    write_ascii_grid(os.path.join(OUTPUT_DIR, f"{STATION_NAME}_xmask.txt"),
                     xmask, grid_params, fmt="{:.0f}")
    print(f"  {STATION_NAME}_xmask.txt")

    write_staloc(os.path.join(OUTPUT_DIR, f"{STATION_NAME}_staloc.txt"),
                 STATION_NAME, outlet_row, outlet_col, grid_params['nrows'])
    print(f"  {STATION_NAME}_staloc.txt")

    write_uh_file(os.path.join(OUTPUT_DIR, "UH.all"))
    print(f"  UH.all")

    write_rout_global(os.path.join(OUTPUT_DIR, "rout_global.txt"),
                      grid_params, STATION_NAME)
    print(f"  rout_global.txt")

    # 创建输出目录
    os.makedirs(os.path.join(OUTPUT_DIR, "rout_out"), exist_ok=True)

    # 输出统计
    print("\n" + "=" * 60)
    print("完成!")
    print("=" * 60)
    print(f"\n输出目录: {OUTPUT_DIR}")
    print(f"\n网格信息:")
    print(f"  行×列: {grid_params['nrows']} × {grid_params['ncols']}")
    print(f"  分辨率: {grid_params['cellsize']}°")
    print(f"  VIC格点数: {len(vic_lats)}")
    print(f"  有效格点数: {valid_frac}")
    print(f"\n出口站点: {STATION_NAME}")
    print(f"  位置: 行{outlet_row}, 列{outlet_col}")
    print(f"  staloc: 列{outlet_col+1}, 行{grid_params['nrows']-outlet_row}")

    print("\n下一步:")
    print(f"  1. 创建VIC输入链接: ln -sf /path/to/vic_for_routing vic_in")
    print(f"  2. 运行routing: /path/to/rout rout_global.txt")


if __name__ == "__main__":
    main()
