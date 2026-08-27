#!/usr/bin/env python3
"""
数据完整性检查脚本
检查VIC模型运行所需的所有数据文件
"""

from pathlib import Path
from datetime import datetime

WORKSPACE_ROOT = Path("/Volumes/Expansion2t/hydro-model-workspace")
BASIN_NAME = "bengbu"

# 必需文件
REQUIRED_FILES = {
    "流域边界": WORKSPACE_ROOT / "data" / "shp" / f"{BASIN_NAME}_shp" / f"{BASIN_NAME}_clip.shp",
    "全球土壤参数": WORKSPACE_ROOT / "data" / "插值" / "global_soil_param_new.txt",
    "地表覆盖栅格": WORKSPACE_ROOT / "data" / "landcover" / "AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif",
    "土壤栅格": WORKSPACE_ROOT / "data" / "soil" / "HWSD_China_Geo.img",
    "植被库文件": WORKSPACE_ROOT / "docs" / "vic_param" / "veglib.LDAS",
    "VIC可执行文件": WORKSPACE_ROOT / "model" / "VIC-5.1.0" / "vic" / "drivers" / "classic" / "vic_classic.exe",
    "历史年均降水": WORKSPACE_ROOT / "data" / "his_average_prec" / "prec_CMFD_010deg_meanAnnual_1951-2020_mm.nc",
    "高程数据": WORKSPACE_ROOT / "data" / "elev" / "elev_CMFD_V0200_B-00_fx_010deg.nc",
}

# 可选文件
OPTIONAL_FILES = {}

# 目录
REQUIRED_DIRS = {
    "气象数据目录": WORKSPACE_ROOT / "data" / "forcing" / "Data_forcing_03hr_010deg",
}


def check_files():
    """检查文件完整性"""
    print("="*80)
    print("VIC模型数据完整性检查")
    print("="*80)
    print(f"工作空间: {WORKSPACE_ROOT}")
    print(f"流域名称: {BASIN_NAME}")
    print(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    missing_required = []
    missing_optional = []

    # 检查必需文件
    print("\n【必需文件】")
    print("-"*80)
    for name, path in REQUIRED_FILES.items():
        if path.exists():
            size = path.stat().st_size
            print(f"✓ {name:<20} {path}")
            print(f"  大小: {size:,} bytes")
        else:
            print(f"✗ {name:<20} {path}")
            missing_required.append((name, path))

    # 检查可选文件
    print("\n【可选文件】")
    print("-"*80)
    for name, path in OPTIONAL_FILES.items():
        if path.exists():
            size = path.stat().st_size
            print(f"✓ {name:<20} {path}")
            print(f"  大小: {size:,} bytes")
        else:
            print(f"⚠  {name:<20} {path} (缺失，但可使用默认值)")
            missing_optional.append((name, path))

    # 检查目录
    print("\n【数据目录】")
    print("-"*80)
    for name, path in REQUIRED_DIRS.items():
        if path.exists():
            # 统计NC文件数量
            nc_files = list(path.rglob("*.nc"))
            print(f"✓ {name:<20} {path}")
            print(f"  包含 {len(nc_files)} 个NC文件")
        else:
            print(f"✗ {name:<20} {path}")
            missing_required.append((name, path))

    # 总结
    print("\n" + "="*80)
    print("检查总结")
    print("="*80)

    if not missing_required:
        print("✓ 所有必需文件和目录都已就绪！")
    else:
        print(f"✗ 缺少 {len(missing_required)} 个必需文件/目录：")
        for name, path in missing_required:
            print(f"  - {name}: {path}")

    if missing_optional:
        print(f"\n⚠  缺少 {len(missing_optional)} 个可选文件：")
        for name, path in missing_optional:
            print(f"  - {name}: {path}")
        print("  这些文件缺失时，脚本会使用默认值，不影响模型运行。")

    # 建议
    print("\n" + "="*80)
    print("建议操作")
    print("="*80)

    if not missing_required:
        print("1. 所有必需数据已就绪，可以开始运行VIC模型流程")
        print("2. 激活虚拟环境:")
        print("   source /Users/yc/Desktop/project/python_env/bin/activate")
        print("3. 运行命令:")
        print(f"   python3 {WORKSPACE_ROOT}/scripts/run_vic_pipeline.py")
    else:
        print("1. 请先准备缺失的必需数据文件")
        print("2. 数据准备完成后，重新运行此检查脚本")

    print("\n" + "="*80)


if __name__ == "__main__":
    check_files()
