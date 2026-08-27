#!/usr/bin/env python3
"""
VIC模型自动化运行脚本 (增强版)
新增功能:
- 命令行参数支持
- Dry-run模式
- 步骤选择运行
- 更详细的进度报告
- 配置验证
"""

import subprocess
import sys
import argparse
from pathlib import Path
from datetime import datetime
import os
import json

# 工作空间根目录
WORKSPACE_ROOT = Path("/Volumes/Expansion2t/hydro-model-workspace")
SCRIPTS_DIR = WORKSPACE_ROOT / "scripts"

# Python解释器
PYTHON_EXE = sys.executable


class VICPipeline:
    """VIC流程管理类"""

    def __init__(self, basin_name, shapefile_path=None, dry_run=False, verbose=False):
        self.basin_name = basin_name
        self.shapefile_path = Path(shapefile_path) if shapefile_path else None
        self.dry_run = dry_run
        self.verbose = verbose
        self.stats = {
            "start_time": datetime.now(),
            "steps_completed": 0,
            "steps_failed": 0,
            "steps_skipped": 0,
        }

        # 设置日志文件路径
        self.log_dir = WORKSPACE_ROOT / "outputs" / basin_name / "vic_temp" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"vic_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    def log_message(self, message, level="INFO"):
        """记录日志消息"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level:7s}] {message}"

        # 控制台输出（带颜色）
        colors = {
            "INFO": "\033[0m",      # 默认
            "SUCCESS": "\033[92m",  # 绿色
            "WARNING": "\033[93m",  # 黄色
            "ERROR": "\033[91m",    # 红色
            "DEBUG": "\033[94m",    # 蓝色
        }
        color = colors.get(level, "\033[0m")
        print(f"{color}{log_line}\033[0m")

        # 写入日志文件
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_line + "\n")

    def validate_environment(self):
        """验证运行环境"""
        self.log_message("="*80, "INFO")
        self.log_message("环境验证", "INFO")
        self.log_message("="*80, "INFO")

        checks = []

        # 检查Python包
        required_packages = ['xarray', 'pandas', 'numpy', 'rasterio', 'geopandas', 'netCDF4']
        for pkg in required_packages:
            try:
                __import__(pkg)
                checks.append((f"Python包: {pkg}", True, ""))
            except ImportError:
                checks.append((f"Python包: {pkg}", False, f"请运行: pip install {pkg}"))

        # 检查关键文件
        critical_files = [
            ("VIC可执行文件", WORKSPACE_ROOT / "model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe"),
            ("植被库文件", WORKSPACE_ROOT / "docs/vic_param/veglib.LDAS"),
        ]

        # 如果提供了shapefile路径，检查它
        if self.shapefile_path:
            critical_files.insert(1, ("流域边界文件", self.shapefile_path))
        else:
            # 否则检查默认位置
            default_shp = WORKSPACE_ROOT / "data/shp" / f"{self.basin_name}_shp" / f"{self.basin_name}.shp"
            critical_files.insert(1, ("流域边界文件(默认)", default_shp))

        for name, path in critical_files:
            if path.exists():
                checks.append((name, True, str(path)))
            else:
                checks.append((name, False, f"文件不存在: {path}"))

        # 检查气象数据
        forcing_dir = WORKSPACE_ROOT / "data/forcing/Data_forcing_03hr_010deg"
        if forcing_dir.exists():
            nc_count = len(list(forcing_dir.rglob("*.nc")))
            checks.append(("CMFD气象数据", nc_count > 0, f"{nc_count} 个NC文件"))
        else:
            checks.append(("CMFD气象数据", False, "目录不存在"))

        # 输出检查结果
        all_passed = True
        for name, passed, detail in checks:
            if passed:
                self.log_message(f"✓ {name}: {detail}", "SUCCESS")
            else:
                self.log_message(f"✗ {name}: {detail}", "ERROR")
                all_passed = False

        if not all_passed:
            self.log_message("环境验证失败，请修复上述问题", "ERROR")
            return False

        self.log_message("环境验证通过", "SUCCESS")
        return True

    def run_python_script(self, script_path, step_name, timeout=3600):
        """运行Python脚本"""
        self.log_message(f"开始执行: {step_name}", "INFO")
        self.log_message(f"脚本: {script_path}", "DEBUG" if self.verbose else "INFO")

        if self.dry_run:
            self.log_message(f"[DRY-RUN] 跳过执行", "WARNING")
            return True

        if not script_path.exists():
            self.log_message(f"脚本不存在: {script_path}", "ERROR")
            return False

        try:
            result = subprocess.run(
                [PYTHON_EXE, str(script_path)],
                cwd=script_path.parent,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            # 记录输出
            if self.verbose and result.stdout:
                for line in result.stdout.split('\n'):
                    if line.strip():
                        self.log_message(f"  {line}", "DEBUG")

            if result.stderr:
                for line in result.stderr.split('\n'):
                    if line.strip() and self.verbose:
                        self.log_message(f"  {line}", "WARNING")

            if result.returncode == 0:
                self.log_message(f"✓ {step_name} 完成", "SUCCESS")
                self.stats["steps_completed"] += 1
                return True
            else:
                self.log_message(f"✗ {step_name} 失败 (返回码: {result.returncode})", "ERROR")
                self.stats["steps_failed"] += 1
                return False

        except subprocess.TimeoutExpired:
            self.log_message(f"✗ {step_name} 超时 (>{timeout}秒)", "ERROR")
            self.stats["steps_failed"] += 1
            return False
        except Exception as e:
            self.log_message(f"✗ {step_name} 异常: {e}", "ERROR")
            self.stats["steps_failed"] += 1
            return False

    def check_output_file(self, file_path, description):
        """检查输出文件"""
        if file_path.exists():
            if file_path.is_file():
                size = file_path.stat().st_size
                size_mb = size / 1024 / 1024
                self.log_message(f"✓ {description}: {size_mb:.2f} MB", "SUCCESS")
            else:
                files = list(file_path.glob("*"))
                self.log_message(f"✓ {description}: {len(files)} 个文件", "SUCCESS")
            return True
        else:
            self.log_message(f"✗ {description} 未生成", "ERROR")
            return False

    def run_step1_grid(self):
        """步骤1: 生成流域格网"""
        self.log_message("="*80, "INFO")
        self.log_message("步骤 1/6: 生成流域格网 (0.25°)", "INFO")
        self.log_message("="*80, "INFO")

        script = SCRIPTS_DIR / "s1_grid" / "make_basin_grid_nc.py"
        output_file = WORKSPACE_ROOT / "outputs" / self.basin_name / "vic_temp" / "grid" / f"grid_{self.basin_name}_025deg.nc"

        if not self.run_python_script(script, "S1_Grid"):
            return False

        return self.check_output_file(output_file, "格网文件")

    def run_step2_forcing(self):
        """步骤2: 处理气象数据"""
        self.log_message("="*80, "INFO")
        self.log_message("步骤 2/6: 处理气象数据", "INFO")
        self.log_message("⚠️  关键步骤: 降水单位转换 (kg/m²/s → mm/3hr)", "WARNING")
        self.log_message("="*80, "INFO")

        script_process = SCRIPTS_DIR / "s2_forcing" / "process_forcing.py"
        output_dir = WORKSPACE_ROOT / "outputs" / self.basin_name / "vic_temp" / "forcing" / "forcing_final"

        # 验证关键代码
        if not self.dry_run:
            with open(script_process, 'r', encoding='utf-8') as f:
                content = f.read()
                if '* 10800' not in content:
                    self.log_message("⚠️  警告: process_forcing.py 可能存在降水单位转换bug", "WARNING")
                    self.log_message("  请检查第167行是否为: df_out['prec'] = df['prec'] * 10800", "WARNING")

        if not self.run_python_script(script_process, "S2_Forcing_Process", timeout=600):
            return False

        return self.check_output_file(output_dir, "气象强迫文件")

    def run_step3_soil(self):
        """步骤3: 生成土壤参数"""
        self.log_message("="*80, "INFO")
        self.log_message("步骤 3/6: 生成土壤参数 (2步)", "INFO")
        self.log_message("="*80, "INFO")

        # 3.1 框架生成
        script_1 = SCRIPTS_DIR / "s3_soil" / "fill_parameters1.py"
        output_1 = WORKSPACE_ROOT / "outputs" / self.basin_name / "vic_temp" / "soil" / "SOIL_PARAM_FINAL.txt"

        if not self.run_python_script(script_1, "S3_Soil_Framework"):
            return False
        if not self.check_output_file(output_1, "土壤参数框架"):
            return False

        # 3.2 插值填充
        script_2 = SCRIPTS_DIR / "s3_soil" / "fill_parameters2.py"
        output_2 = WORKSPACE_ROOT / "outputs" / self.basin_name / "vic_temp" / "soil" / "SOIL_PARAM_COMPLETE.txt"

        if not self.run_python_script(script_2, "S3_Soil_Interpolation"):
            return False

        return self.check_output_file(output_2, "完整土壤参数")

    def run_step4_veg(self):
        """步骤4: 生成植被参数"""
        self.log_message("="*80, "INFO")
        self.log_message("步骤 4/6: 生成植被参数", "INFO")
        self.log_message("="*80, "INFO")

        script = SCRIPTS_DIR / "s4_veg" / "process_vegetation_detailed.py"
        output_file = WORKSPACE_ROOT / "outputs" / self.basin_name / "vic_temp" / "veg" / "vic_veg_param_final.txt"

        if not self.run_python_script(script, "S4_Vegetation"):
            return False

        return self.check_output_file(output_file, "植被参数文件")

    def run_step5_prepare_global_param(self):
        """步骤5: 准备全局参数"""
        self.log_message("="*80, "INFO")
        self.log_message("步骤 5/6: 检查全局参数文件", "INFO")
        self.log_message("="*80, "INFO")

        global_param = WORKSPACE_ROOT / "outputs" / self.basin_name / "vic_temp" / f"global_param_{self.basin_name}.txt"

        if global_param.exists():
            self.log_message(f"✓ 全局参数文件存在", "SUCCESS")

            # 验证关键配置
            with open(global_param, 'r') as f:
                content = f.read()
                if 'FORCE_STEPS_PER_DAY' in content and '8' in content:
                    self.log_message("✓ FORCE_STEPS_PER_DAY = 8 (正确)", "SUCCESS")
                else:
                    self.log_message("⚠️  FORCE_STEPS_PER_DAY 配置可能不正确", "WARNING")

            return True
        else:
            self.log_message(f"✗ 全局参数文件不存在", "ERROR")
            self.log_message(f"  请先运行: python scripts/config_paths.py", "INFO")
            return False

    def run_step6_vic_model(self):
        """步骤6: 运行VIC模型"""
        self.log_message("="*80, "INFO")
        self.log_message("步骤 6/6: 运行VIC模型", "INFO")
        self.log_message("="*80, "INFO")

        vic_exe = WORKSPACE_ROOT / "model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe"
        global_param = WORKSPACE_ROOT / "outputs" / self.basin_name / "vic_temp" / f"global_param_{self.basin_name}.txt"
        output_dir = WORKSPACE_ROOT / "outputs" / self.basin_name / "vic_result"

        if self.dry_run:
            self.log_message("[DRY-RUN] 跳过VIC模型运行", "WARNING")
            return True

        if not vic_exe.exists() or not global_param.exists():
            self.log_message("VIC可执行文件或全局参数文件缺失", "ERROR")
            return False

        try:
            self.log_message("VIC模型运行中... (可能需要15-30分钟)", "INFO")
            result = subprocess.run(
                [str(vic_exe), "-g", str(global_param)],
                cwd=vic_exe.parent,
                capture_output=True,
                text=True,
                timeout=7200
            )

            if self.verbose and result.stdout:
                for line in result.stdout.split('\n')[-20:]:  # 只显示最后20行
                    if line.strip():
                        self.log_message(f"  {line}", "DEBUG")

            if result.returncode == 0:
                self.log_message("✓ VIC模型运行成功", "SUCCESS")
                self.stats["steps_completed"] += 1
                return self.check_output_file(output_dir, "VIC输出目录")
            else:
                self.log_message(f"✗ VIC模型失败 (返回码: {result.returncode})", "ERROR")
                self.stats["steps_failed"] += 1
                return False

        except subprocess.TimeoutExpired:
            self.log_message("✗ VIC模型超时 (>2小时)", "ERROR")
            self.stats["steps_failed"] += 1
            return False
        except Exception as e:
            self.log_message(f"✗ VIC模型异常: {e}", "ERROR")
            self.stats["steps_failed"] += 1
            return False

    def print_summary(self, success):
        """打印运行总结"""
        end_time = datetime.now()
        duration = end_time - self.stats["start_time"]

        self.log_message("="*80, "INFO")
        if success:
            self.log_message("🎉 VIC流程完成！", "SUCCESS")
        else:
            self.log_message("❌ VIC流程失败", "ERROR")
        self.log_message("="*80, "INFO")

        self.log_message(f"完成步骤: {self.stats['steps_completed']}", "INFO")
        self.log_message(f"失败步骤: {self.stats['steps_failed']}", "INFO")
        self.log_message(f"总耗时: {duration}", "INFO")
        self.log_message(f"日志文件: {self.log_file}", "INFO")

        if success:
            self.log_message("\n下一步操作:", "INFO")
            self.log_message(f"1. 检查VIC输出: ls outputs/{self.basin_name}/vic_result/", "INFO")
            self.log_message("2. 转换为NetCDF: cd scripts/vic_post && python process_data_windows_ymd.py", "INFO")
            self.log_message(f"3. 运行CaMa-Flood: cd model/cmf_v420_pkg/gosh && bash run_{self.basin_name}_1d.sh", "INFO")

        self.log_message("="*80, "INFO")

    def run(self, steps=None):
        """运行流程"""
        self.log_message("="*80, "INFO")
        self.log_message("VIC模型自动化流程 (增强版)", "INFO")
        self.log_message("="*80, "INFO")
        self.log_message(f"工作空间: {WORKSPACE_ROOT}", "INFO")
        self.log_message(f"流域名称: {self.basin_name}", "INFO")
        self.log_message(f"Dry-run模式: {self.dry_run}", "INFO")
        self.log_message(f"详细输出: {self.verbose}", "INFO")
        self.log_message("="*80, "INFO")

        # 环境验证
        if not self.validate_environment():
            return False

        # 定义步骤（注意：S3必须在S2之前，因为S2需要读取土壤参数文件）
        all_steps = [
            ("S1", "生成流域格网", self.run_step1_grid),
            ("S3", "生成土壤参数", self.run_step3_soil),
            ("S2", "处理气象数据", self.run_step2_forcing),
            ("S4", "生成植被参数", self.run_step4_veg),
            ("S5", "准备全局参数", self.run_step5_prepare_global_param),
            ("S6", "运行VIC模型", self.run_step6_vic_model),
        ]

        # 筛选要运行的步骤
        if steps:
            steps_to_run = [(s, n, f) for s, n, f in all_steps if s in steps]
        else:
            steps_to_run = all_steps

        # 执行步骤
        success = True
        for step_id, step_name, step_func in steps_to_run:
            if not step_func():
                self.log_message(f"✗ {step_id}: {step_name} 失败，流程中止", "ERROR")
                success = False
                break

        # 打印总结
        self.print_summary(success)
        return success


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="VIC模型自动化运行脚本 (增强版)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 运行完整流程
  python run_vic_pipeline_enhanced.py

  # Dry-run模式（不实际执行）
  python run_vic_pipeline_enhanced.py --dry-run

  # 仅运行指定步骤
  python run_vic_pipeline_enhanced.py --steps S2 S6

  # 详细输出
  python run_vic_pipeline_enhanced.py --verbose
        """
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run模式：验证配置但不实际执行"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出模式：显示所有脚本输出"
    )

    parser.add_argument(
        "--steps",
        nargs="+",
        choices=["S1", "S2", "S3", "S4", "S5", "S6"],
        help="仅运行指定步骤（默认运行全部）"
    )

    parser.add_argument(
        "--basin",
        type=str,
        default=None,
        help="流域名称（用于命名输出目录和文件）"
    )

    parser.add_argument(
        "--shapefile",
        type=str,
        default=None,
        help="流域边界shapefile的完整路径"
    )

    args = parser.parse_args()

    # 如果没有提供basin或shapefile，进入交互模式
    basin_name = args.basin
    shapefile_path = args.shapefile

    if not basin_name:
        print("\n" + "="*80)
        print("VIC模型运行 - 交互式参数输入")
        print("="*80)

        basin_name = input("流域名称（用于命名输出目录）: ").strip()
        if not basin_name:
            print("错误：流域名称不能为空")
            sys.exit(1)

        if not shapefile_path:
            shapefile_path = input("流域边界shapefile完整路径（可选，按Enter跳过）: ").strip()

    # 创建流程对象并运行
    pipeline = VICPipeline(
        basin_name=basin_name,
        shapefile_path=shapefile_path if shapefile_path else None,
        dry_run=args.dry_run,
        verbose=args.verbose
    )
    success = pipeline.run(steps=args.steps)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
