> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.

---

<!-- NOTE: Mac development paths below are stale on the server. Use KISSPATH_ROOT/ paths instead. -->

# VIC模型自动化运行 Skill

## 📖 功能说明

本skill用于自动化运行VIC水文模型，从流域shapefile到径流输出的完整流程。支持任意流域，只需提供流域边界shapefile即可。

## 🎯 使用场景

- 新流域VIC模型快速启动
- 标准化VIC参数准备流程
- 自动化VIC运行和后处理

## ⚡ 快速开始

### 前置条件

1. **流域边界文件**: shapefile格式（.shp及配套文件）
2. **气象数据**: CMFD 0.1度3小时数据（位于`data/forcing/Data_forcing_03hr_010deg/`）
3. **Python环境**: 必须使用指定虚拟环境

### 基本用法

```bash
# 🔴 易错点1: 必须先激活正确的Python虚拟环境！
source /Users/yc/Desktop/project/python_env/bin/activate

# 1. 准备流域shapefile
# 🔴 易错点2: shapefile命名可能是两种格式之一：
#    - data/shp/{basin_name}_shp/{basin_name}_clip.shp (如bengbu)
#    - data/shp/{basin_name}_shp/{basin_name}.shp (如wangjiaba)
# 需要在config_paths.py中修改shp_file路径匹配实际文件名

# 2. 修改config_paths.py中的BASIN_NAME变量
cd /Volumes/Expansion2t/hydro-model-workspace/scripts
# 编辑config_paths.py: BASIN_NAME = "your_basin_name"

# 3. 运行配置脚本（必须在虚拟环境中）
# **WARNING**: config_paths.py modifies scripts in-place via regex. When switching basins,
# verify that all scripts have correct paths after running config_paths.py.
# Check for truncated os.path.join() calls.
python config_paths.py

# 4. 手动运行VIC准备和模拟步骤
# 见下方"完整流程"部分
```

---

## 📋 完整流程（推荐手动执行）

### 🔴 重要：执行顺序

**关键顺序**:
```
步骤1(格网) → 步骤2(土壤参数) → 步骤3(植被参数) → 步骤4(气象数据) → 步骤5(配置检查) → 步骤6(运行VIC) → 步骤7(后处理转NC)
```

**顺序原因**:
- `process_forcing.py`需要读取`SOIL_PARAM_COMPLETE.txt`获取格网坐标，**土壤必须在气象之前**
- 植被参数只依赖格网文件，可在土壤之后任意时间执行

### 🔴 重要：正确的路径结构

**所有输出应组织在流域专属目录下**：

```
outputs/{basin_name}/
├── vic_temp/              # VIC中间文件
│   ├── grid/             # 格网文件
│   ├── forcing/          # 气象数据
│   │   ├── forcing_1d/   # 裁剪后的NC文件
│   │   └── forcing_final/# VIC输入forcing文件
│   ├── soil/             # 土壤参数
│   ├── veg/              # 植被参数
│   └── logs/             # 日志
├── vic_result/           # VIC模型输出
└── cama_input/           # 转换后的CaMa输入（可选）
```

### 步骤0: 环境准备

```bash
# 🔴🔴🔴 最重要：激活Python虚拟环境（每次新开终端都要执行）🔴🔴🔴
source /Users/yc/Desktop/project/python_env/bin/activate

# 设置工作目录
cd /Volumes/Expansion2t/hydro-model-workspace

# 设置流域名称（环境变量）
export BASIN_NAME="your_basin_name"
```

### 🔴 易错点汇总（必读）

1. **Python环境**: 每次运行Python脚本前必须执行 `source /Users/yc/Desktop/project/python_env/bin/activate`

2. **shapefile命名**: 检查实际文件名是 `{basin}.shp` 还是 `{basin}_clip.shp`，在config_paths.py中对应修改shp_file路径

3. **时间范围**: 需要在**三个位置**同步修改：
   - `scripts/s2_forcing/forcing_1d.py`: YEAR_START, YEAR_END (第26-27行)
   - `scripts/s2_forcing/process_forcing.py`: START_DATE, END_DATE (第85-86行)
   - 全局参数文件: STARTYEAR, ENDYEAR, FORCEYEAR

4. **forcing_1d.py的GRID_NC_PATH**: config_paths.py**不会**自动更新此路径，需手动修改：
   ```python
   GRID_NC_PATH = Path(r"/Volumes/Expansion2t/hydro-model-workspace/outputs/{basin}/vic_temp/grid/grid_{basin}_025deg.nc")
   ```

5. **全局参数文件**: 运行config_paths.py后**必须手动检查**：
   - FROZEN_SOIL 必须是 `FALSE`（不是路径）
   - LAI_SRC 必须是 `FROM_VEGPARAM`（不带额外路径）
   - FORCING1 前缀必须与实际文件名匹配（通常是 `huai_01dy_025deg_`）

---

## 🌊 CaMa-Flood集成

VIC后处理完成后，如需运行CaMa-Flood汇流模型，请参见 **`cama-flood-integration`** skill。

---

## 📋 VIC完整流程

### 步骤1: 生成流域格网 (0.25°)

```bash
cd scripts/s1_grid
python make_basin_grid_nc.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/grid/grid_${BASIN_NAME}_025deg.nc`

**检查**:
```bash
ls -lh outputs/${BASIN_NAME}/vic_temp/grid/
# 应该看到grid_xxx_025deg.nc文件
```

### 步骤2: 生成土壤参数（先于forcing处理）

**⚠️ 重要顺序**: 必须先生成土壤参数，因为forcing处理脚本需要读取土壤参数文件来获取格网坐标信息。

#### 2.1 生成土壤参数框架

```bash
cd scripts/s3_soil
python fill_parameters1.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/soil/SOIL_PARAM_FINAL.txt`

#### 2.2 插值填充土壤参数

```bash
python fill_parameters2.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt`

### 步骤3: 处理气象数据（依赖土壤参数）

**⚠️ 依赖**: 此步骤必须在土壤参数生成之后执行，因为`process_forcing.py`需要读取`SOIL_PARAM_COMPLETE.txt`来获取准确的格网经纬度坐标。

#### 3.1 裁剪CMFD数据到流域范围

```bash
cd scripts/s2_forcing
python forcing_1d.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/forcing/forcing_1d/*.nc` (96个文件)

**关键点**:
- 此步骤从0.1度CMFD数据裁剪到流域网格
- 自动处理边界格网的NaN值

#### 3.2 生成VIC forcing文件

```bash
python process_forcing.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/forcing/forcing_final/huai_01dy_025deg_*.txt` (每个格点一个文件)

**⚠️ 重要**: 检查路径配置
- `INPUT_DATA_DIR`: 应指向 `forcing_1d/`
- `OUTPUT_FORCING_DIR`: 应指向 `forcing_final/`
- `SOIL_PARAM_FILE`: 应指向 `SOIL_PARAM_COMPLETE.txt` (必须存在)

### 步骤4: 生成植被参数

```bash
cd scripts/s4_veg
python process_vegetation_detailed.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/veg/vic_veg_param_final.txt`

### 步骤5: 配置并检查全局参数文件

```bash
cd scripts
python config_paths.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/global_param_${BASIN_NAME}.txt`

**⚠️ 关键配置检查**:

编辑 `outputs/${BASIN_NAME}/vic_temp/global_param_${BASIN_NAME}.txt`，确认：

1. **时间设置**（根据需要调整）:
```
STARTYEAR               2024
STARTMONTH              01
STARTDAY                01
ENDYEAR                 2024
ENDMONTH                12
ENDDAY                  31
```

2. **Forcing路径**（文件名前缀要匹配实际文件）:
```
FORCING1                /path/to/forcing_final/huai_01dy_025deg_
```

3. **时间步长**（必须匹配forcing数据）:
```
MODEL_STEPS_PER_DAY     8
FORCE_STEPS_PER_DAY     8
```

4. **输出路径**（应该在流域专属目录下）:
```
RESULT_DIR              /path/to/outputs/${BASIN_NAME}/vic_result/
```

5. **参数文件路径**（确保所有路径正确）:
```
SOIL                    /path/to/outputs/${BASIN_NAME}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt
VEGPARAM                /path/to/outputs/${BASIN_NAME}/vic_temp/veg/vic_veg_param_final.txt
```

### 步骤6: 运行VIC模型

```bash
# 创建输出目录
mkdir -p outputs/${BASIN_NAME}/vic_result

# 运行VIC
/Volumes/Expansion2t/hydro-model-workspace/model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe \
  -g outputs/vic_temp/global_param_${BASIN_NAME}.txt
```

**预期输出**:
- `outputs/${BASIN_NAME}/vic_result/huaihe_fluxes_*.txt` (每个格点一个文件)
- 运行时间: 几秒到几分钟（取决于格点数和模拟时长）

**检查输出**:
```bash
ls outputs/${BASIN_NAME}/vic_result/*.txt | wc -l
# 应该等于格点数
```

### 步骤7: VIC后处理（转换为NetCDF）

**仅当需要CaMa-Flood输入时执行**

```bash
cd scripts/vic_post
python process_${BASIN_NAME}.py
```

**输出**: `outputs/${BASIN_NAME}/cama_input/${BASIN_NAME}_runoff_1d_YYYY.nc`

**⚠️ 路径配置**: 确保脚本中的路径变量正确：
- `INPUT_DIR`: VIC输出目录
- `OUTPUT_DIR`: CaMa输入目录

---

## 🔧 常见问题和解决方案

### ⚠️ 问题0: FROZEN_SOIL参数错误

**错误**: `is neither TRUE nor FALSE`

**原因**: 全局参数文件中FROZEN_SOIL后面跟了路径，而不是布尔值

**解决**:
```bash
# 检查全局参数文件
grep FROZEN_SOIL outputs/${BASIN_NAME}/vic_temp/global_param_${BASIN_NAME}.txt

# 应该显示:
# FROZEN_SOIL             FALSE   # Not simulating frozen soil

# 如果显示路径，手动修改为上述格式
```

**根本解决**:
- 已修复模板文件 `docs/vic_param/global_param_huaihe_cama.txt`
- 重新运行 `python scripts/config_paths.py` 生成新的全局参数文件

### 问题1: Forcing文件找不到

**错误**: `Unable to open File .../forcing_XX.XXXX_XXX.XXXX`

**原因**: 全局参数文件中的FORCING1前缀与实际文件名不匹配

**解决**:
```bash
# 检查实际文件名
ls outputs/${BASIN_NAME}/vic_temp/forcing/forcing_final/ | head -1

# 示例输出: huai_01dy_025deg_31.1250_115.6250
# 则FORCING1应设置为: .../forcing_final/huai_01dy_025deg_
```

### 问题2: 时间步数不足

**错误**: `Not enough records in forcing file`

**原因**: 全局参数文件的模拟时段超出forcing数据范围

**解决**: 确保STARTYEAR/ENDYEAR与forcing数据时间范围一致

### 问题3: 路径混乱

**错误**: 各种"文件不存在"错误

**原因**: 输出文件散落在不同目录（vic_temp vs. ${BASIN_NAME}/vic_temp）

**解决**:
1. 统一使用 `outputs/${BASIN_NAME}/` 作为流域专属根目录
2. 检查所有脚本中的路径配置
3. 必要时手动创建符号链接或移动文件

### 问题4: 植被参数根系分布之和>1

**警告**: `Root zone fractions sum to more than 1`

**原因**: 正常情况，VIC会自动归一化

**解决**: 无需处理，这是警告不是错误

---

## 📊 输出说明

### VIC模型输出文件

**位置**: `outputs/${BASIN_NAME}/vic_result/huaihe_fluxes_LAT_LON.txt`

**格式**: ASCII文本，列分隔

**主要变量**:
- `OUT_PREC`: 降水
- `OUT_RUNOFF`: 地表径流
- `OUT_BASEFLOW`: 基流
- `OUT_EVAP`: 蒸散发
- `OUT_SOIL_MOIST`: 土壤湿度
- 等（见全局参数文件OUTVAR配置）

### NetCDF输出（后处理）

**位置**: `outputs/${BASIN_NAME}/cama_input/${BASIN_NAME}_runoff_1d_YYYY.nc`

**变量**:
- `Runoff`: 总径流 (OUT_RUNOFF + OUT_BASEFLOW)
- 单位: mm/day
- 维度: (time, lat, lon)

---

## 🎓 新流域适配指南

### 1. 准备流域数据

```bash
# 创建流域目录
mkdir -p data/shp/${BASIN_NAME}_shp

# 复制shapefile（确保包含.shp, .shx, .dbf, .prj等文件）
cp /path/to/your/basin.shp data/shp/${BASIN_NAME}_shp/${BASIN_NAME}_clip.shp
# ... 其他配套文件
```

### 2. 修改config_paths.py

编辑 `scripts/config_paths.py`:
```python
# 修改流域名称
BASIN_NAME = "your_basin_name"  # 改为你的流域名

# 其他配置会自动适配
```

### 3. 创建VIC后处理脚本

复制并修改现有脚本:
```bash
cd scripts/vic_post
cp process_bengbu.py process_${BASIN_NAME}.py
```

编辑新脚本，修改以下变量:
```python
# 输入输出路径
INPUT_DIR = f"/path/to/outputs/{BASIN_NAME}/vic_result"
OUTPUT_DIR = f"/path/to/outputs/{BASIN_NAME}/cama_input"

# 网格定义（从shapefile自动获取，或手动设置）
NX = 24        # 东西方向格点数
NY = 16        # 南北方向格点数
WEST = 111.875   # 西边界
EAST = 117.625   # 东边界
NORTH = 34.875  # 北边界
SOUTH = 31.125  # 南边界
GRID_SIZE = 0.25  # 分辨率

# 文件名前缀（根据实际forcing文件名调整）
FILE_PREFIX = "huaihe_fluxes_"
OUTPUT_NC_PREFIX = f"{BASIN_NAME}_runoff_1d_"
```

### 4. 按照"完整流程"执行

从步骤0开始，依次执行所有步骤。

---

## 💡 最佳实践

### 1. 路径管理
- ✅ 使用流域专属目录 `outputs/${BASIN_NAME}/`
- ✅ 保持一致的路径结构
- ❌ 避免硬编码绝对路径

### 2. 配置管理
- ✅ 运行前检查所有路径配置
- ✅ 验证forcing文件名前缀
- ✅ 确认时间范围匹配

### 3. 调试策略
- ✅ 逐步执行，检查每步输出
- ✅ 保存日志文件
- ✅ 使用 `ls -lh` 验证文件生成

### 4. 数据验证
- ✅ 检查格点数是否正确
- ✅ 验证时间序列长度
- ✅ 检查数值范围合理性

---

## 📚 参考资料

- VIC模型文档: https://vic.readthedocs.io/
- CMFD气象数据: http://www.tpdc.ac.cn/
- 本项目README: `/Volumes/Expansion2t/hydro-model-workspace/README.md`

---

## ✨ 版本历史

- **v1.1** (2025-02-01):
  - 修正路径结构说明
  - 明确流程顺序
  - 添加常见问题解决方案
  - 改进新流域适配指南

- **v1.0** (2025-01-31): 初始版本

---

## 📧 维护信息

**Skill路径**: `/Volumes/Expansion2t/hydro-model-workspace/skills/vic-auto-run/`

**核心脚本**: 见 `scripts/` 目录下各子目录

**依赖**:
- VIC 5.0.1+
- Python 3.8+
- 虚拟环境: `/Users/yc/Desktop/project/python_env/`
