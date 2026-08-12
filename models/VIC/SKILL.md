> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.md` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.md` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
VIC forcing tools are in `s2_forcing/` in this KI:
- `s2_forcing/forcing_1d.py` — Consolidates regional CMFD/MSWX into 1D NetCDF per variable
- `s2_forcing/process_forcing.py` — Generates per-cell VIC ASCII forcing (3-hourly, 7 columns)
- `s2_forcing/forcing_nasa_power.py` — NASA POWER API fallback for non-CMFD/MSWX regions

### Soil properties

**Data Sources**: Use `from ki_tools_common.soil_utils import lookup_hwsd` for soil properties.

**Data Validation Reference**: CMFD units and traps — `data_ki/dataset_index.yaml` +
`data_ki/kdt_dataset_layouts.yaml`. (The old `data_ki/CMFD/SKILL.md` and
`data_ki/HWSD/SKILL.md` paths were removed in KDT 5.0; soil/forcing helpers now
live in `ki_tools_common.soil_utils` / `ki_tools_common.load_forcing`.)

Key CMFD unit facts for this KI: `prec` is `kg m-2 s-1` → ×10800 for mm/3hr
(×86400 for mm/day); `temp` is K; `pres` is Pa → /1000 for kPa;
vapour pressure is derived from `shum` + `pres`. `process_forcing.py` already
does all of this — verify with `validators/preflight_forcing.py` before running.

---

## ⚡ Server quickstart (2026-07-09) — READ THIS BEFORE THE CHINESE SECTIONS BELOW

The Chinese walkthrough further down is the original macOS authoring notes. Its
`/Users/yc/...` and `/Volumes/Expansion2t/...` paths are DEAD, and its advice to
"edit the variables at the top of each script" has been superseded.

**Every stage script now reads its configuration from environment variables**
(defaults reproduce the old hard-coded behaviour). Set these once, then run the
stages unmodified — no in-place editing, no `config_paths.py` regex rewriting:

| variable | meaning |
|---|---|
| `VIC_BASIN_NAME` | basin tag; drives `outputs/<name>/…` and all filenames |
| `VIC_BASIN_SHP` | basin boundary shapefile |
| `VIC_OUT_ROOT` | default `/mnt/disk1/Hydrocraft_server/outputs` |
| `VIC_CMFD_DIR` | forcing root, e.g. `data/forcing/Data_forcing_03hr_010deg` |
| `VIC_YEAR_START`, `VIC_YEAR_END` | forcing + simulation years (one place, not three) |
| `VIC_START_DATE`, `VIC_END_DATE` | `process_forcing.py` slice |
| `VIC_FORCING_PREFIX` | must equal the `FORCING1` prefix, e.g. `tangnaihai_025deg_` |
| `VIC_GLOBAL_PARAM_TEMPLATE` | global param to clone; defaults to the KI-shipped `docs/vic_param/global_param_template.txt` (dt_vic_024) |
| `VIC_STATION_NAME` | routing station tag, e.g. `HRB`; names `<STA>_direc.txt` etc. |
| `VIC_OUTLET_LON`, `VIC_OUTLET_LAT` | gauge coords — **required** for a new basin (s9 pour point + max-accum assertion) |
| `VIC_DEM` | DEM for delineation, e.g. `data/dem/china_dem_90m/china_dem_90m.tif` |
| `VIC_STREAM_THRESHOLD` | stream threshold in **native DEM cells**; scale with basin size (20k for 10³ km², 200k for 4×10⁵ km²) |
| `VIC_ROUT_VELOCITY` | Lohmann channel celerity, m/s. **Default 1.5 is a Bengbu value — do NOT inherit it.** See "routing travel time" below (dt_vic_028) |
| `VIC_ROUT_DIFF` | Lohmann diffusivity, m²/s. Default 800. Larger values *advance* the peak as well as broaden it |

The last four DEM/outlet variables are read only by `s5_routing/build_routing_param.py`,
and omitting `VIC_OUTLET_LON/LAT` fails there, not at setup time (dt_vic_025).

### The full chain

```
s0  ki_tools_common.terrain_ops.delineate_basin   -> basin.tif + flow_accum.tif -> basin shapefile
s1  s1_grid/make_basin_grid_nc.py                 -> grid_<basin>_025deg.nc
s2  s3_soil/fill_parameters1.py                   -> SOIL_PARAM_FINAL.txt
s3  s3_soil/fill_parameters2.py                   -> SOIL_PARAM_COMPLETE.txt
s4  s4_veg/process_vegetation_detailed.py         -> vic_veg_param_final.txt
s5  s2_forcing/forcing_1d.py                      -> per-month basin NetCDF (resumable)
s6  s2_forcing/process_forcing.py                 -> per-cell ASCII forcing (7 col, 8 steps/day)
s7  config_paths.create_global_param()            -> global_param_<basin>.txt
s8  model/VIC-5.1.0/.../vic_classic.exe -g …      -> daily flux per cell (mm)
s9  s5_routing/build_routing_param.py             -> direc/frac/xmask/staloc/UH.all   ← NEW
s10 s5_routing/run_routing.py                     -> daily discharge (m3/s) at the gauge  ← NEW
      (wraps model/route_1.0/src/rout; use it, don't shell out to the binary by hand)
```

Order matters: `process_forcing.py` reads the grid coordinates out of
`SOIL_PARAM_COMPLETE.txt`, so **soil must precede forcing** (dt_vic_010).

### 🔴 VIC DOES NOT ROUTE — discharge requires step s9 + s10

`dag.yaml` is explicit: `OUT_DISCHARGE` is emitted only by the optional lake
module. VIC's own output is runoff/baseflow **in mm, per cell**. To compare
against a gauge you MUST run the Lohmann `route_1.0` binary. Summing
runoff+baseflow over the basin is not discharge — it has no travel time, so the
hydrograph has no lag and no attenuation (dt_vic_019).

Preprocess each flux file to the 7 columns `rout` expects
(`year month day prec evap runoff baseflow` = `df.iloc[:, [0,1,2,3,18,16,17]]`
for the standard OUTVAR list) into `routing_param/vic_in/fluxes_<LAT>_<LON>`,
then run `rout`. Routing parameters for a NEW basin are built by
`s5_routing/build_routing_param.py`; feed it the native-resolution
`flow_accum.tif` / `basin.tif` / `dem_filled.tif` from `delineate_basin` via
`VIC_FLOW_ACCUM` / `VIC_BASIN_RASTER` / `VIC_FILLED_DEM`. Never let it derive
flow directions from a coarsened DEM (dt_vic_020).

Validate the routing grid before trusting any hydrograph:
* `max_accum × pixel_area` must equal the delineated basin area;
* the arg-max accumulation cell must BE the gauge cell;
* connectivity must be `N/N` — `rout` silently drops disconnected cells.

### 🔴 Also validate the routing TRAVEL TIME — a correct grid is not enough (dt_vic_028)

A routing grid can be perfect and the hydrograph still worthless, because
`VIC_ROUT_VELOCITY` defaults to **1.5 m/s — the value that reproduced Bengbu**
(121,330 km²). Inheriting it at a larger, flatter basin makes the model respond
weeks too early. Two numbers settle it, both from `s5_routing/run_routing.py`:

```python
from s5_routing.run_routing import route, observed_lag_days, basin_mean_uh_lag
sim = route(routing_param_dir, velocity=1.5, diffusivity=800.0)   # ~7 s, 866 cells
print(sim.attrs["uh_lag_days"])                 # what the MODEL's UH_S actually does
print(observed_lag_days(obs_cal, sim_cal))      # what the OBSERVATION says it should do
```

If the observed lag exceeds the UH lag, **identify** velocity by bisecting until the
two agree — on the **calibration window only**. Never fit velocity to NSE.

**First probe `v → 0` (one 7 s call) to learn what the scheme can actually reach.**
`MAKE_UHM` clips each cell's impulse response at `LE*DT = 48 h` and renormalises it, so
once `xmask/velocity > 48 h` the kernel stops changing and `uh_lag` asymptotes to
`mean(UH.all) + mean_path_in_cells × ~1.3 d`. Below that threshold velocity is an **inert
knob** and an optimiser will walk to its lower bound while reporting "improvement". At
哈尔滨 the ceiling is 29.8 d against an observed demand of ~33 d: v = 0.002 and v = 0.15
differ by 2 d of lag and 0.03 of held-out NSE. When the target is unreachable, pin
velocity to the `rout_velocity` `range` lower bound in `calibration.yaml` (0.10 m/s),
report the plateau's NSE spread, and state that the scheme is structurally insufficient.

Two facts that keep being rediscovered the hard way:

* **`NSE ≤ r²`.** Compute zero-lag `r` *before* concluding a bad NSE needs soil
  calibration. At 哈尔滨 the default velocity held `r` at 0.589, so NSE could not
  exceed 0.347 — the target of 0.5 was arithmetically unreachable and no soil
  parameter could have rescued it.
* **Routing conserves mass at every velocity.** `rout` renormalises `UH_S`
  (`unit_hyd_routines.f`), so velocity moves *timing* and can NEVER move PBIAS.
  A volume bias is therefore never evidence that the routing is right, and a
  routing fix will never close a volume bias.

`velocity` in a large flat basin is an **effective basin residence time, not a channel
celerity** — Lohmann's linearised Saint-Venant scheme lumps hillslope, floodplain,
wetland and reservoir storage into `(velocity, diffusivity)`. Where storage dominates,
prefer CaMa-Flood 4.20 (`cama_maps_15min_extracted`), which represents it explicitly.
`rout.f` caps the routed response at `UH_DAY = 96` d and `UH.all` at `KE = 12` d, so
the within-cell UH alone can never supply more than ~12 d of lag.

### 🔴 Check the SPIN-UP before believing any cal/val gap (dt_vic_030)

`fill_parameters1.py` initialises every soil layer at `init_moist = 66.79 mm`
(~10-14% saturation) and the KI column is 1.9 m deep. The standard split gives it ONE
spin-up year. At 哈尔滨 the column needs **5-6 years**: baseflow climbs 22 → 111 mm/yr
and 31-Dec storage 320 → 500 mm across 1980-1987, so the *calibration* window is the
least equilibrated part of the record and PBIAS **grows** as the model equilibrates
(+19.5% → +28.5% → +36.8%). That reads exactly like overfitting and is not.

Before scoring, plot `OUT_SOIL_MOIST_* + OUT_SWE` on 31 Dec of each year and annual
`OUT_BASEFLOW`. If either still trends at `CAL_START`, start the simulation earlier —
CMFD covers 1951-2024 and water-balance mode costs only ~95 s per simulated year for
866 cells.

### 🔴 Profile the observation record BEFORE choosing the simulation period

The KDT standard split (spinup 1980 / cal 1981-85 / val 1986-90) assumes a
continuous record. Chinese gauge files pad gaps with `-99`. Always run
`v = q[q > -90]; v.groupby(v.index.year).size()` first and pick the first
contiguous fully-observed decade, or you will "validate" on zero days
(dt_vic_021). Example: 唐乃亥 has valid daily Q only for
{1985, 1987, 2007-2020, 2022, 2023}.

### Reference runs

| basin | cells | period | routed daily NSE |
|---|---|---|---|
| Bengbu 51080 (Huai, lowland, regulated) | 224 | 1981-90 | ~0.15 (PBIAS +44%) |
| 唐乃亥 Tangnaihai (upper Yellow, alpine) | 251 | cal 2007-11 / val 2012-16 | see `detached/real_case/result.json` |
| 哈尔滨 Harbin (Songhua, cold/snowmelt) | 866 | cal 1981-85 / val 1986-87 | see `detached/real_case/result.json` |

Harbin is the KI's first snow-dominated basin: 384,411 km² above the gauge (398,330 km²
of frac-weighted routed area), mean annual air temperature −5 … +7 °C, and a spring
freshet driven by snowmelt. The observed record is ice-affected in winter and the basin is
partly regulated (Fengman on the Second Songhua, Nierji on the Nen).

**Read this before rerunning Harbin — the 2026-07-10 run overturned three earlier
assumptions:**

1. The dominant error was **never** the soil parameters. It was `VIC_ROUT_VELOCITY = 1.5`
   m/s, giving a 6.2 d basin travel time against an observed 28 d lag. Zero-lag `r` was
   0.589, so NSE was capped at 0.347. Slowing the routing lifts `r` to ~0.90 and the NSE
   ceiling to ~0.80 — **without touching a single soil parameter and without changing
   PBIAS by one part in 10⁴** (dt_vic_028). But note the second half of dt_vic_028:
   `uh_lag` saturates at 29.8 d, the basin demands ~33 d, and velocity is **inert below
   ~0.15 m/s**. Harbin is run at the pool bound v = 0.10 m/s, and held-out NSE varies only
   0.488–0.521 across the entire plateau. Route_1.0 is structurally insufficient here;
   report that rather than optimising inside the plateau.
2. Spin-up of one year is **not enough** here; the deep store is still filling through the
   calibration period, and PBIAS grows +19.5% → +36.8% across the record (dt_vic_030).
3. `FROZEN_SOIL TRUE` was not merely "worth revisiting" — it was **impossible**: the soil
   file carried `bubble = -9999` and `fs_active = 0`, and `NODES` must be ≥ 10 once
   `EXP_TRANS` turns on. Both are fixed (dt_vic_031); the cold-region template is
   `docs/vic_param/global_param_template_frozen.txt`.

What remains after all of that is a **volume** bias (PBIAS ≈ +29% over 1981-87, +37% on
the equilibrated 1986-87 window) that routing physically cannot touch. Budyko (Fu, ω=2.6)
on CMFD `P = 589 mm/yr` and `PET ≈ 750 mm/yr` predicts a natural `Q ≈ 134 mm/yr`; VIC
gives ≈ 150 (trending to ≈ 180 as the store fills) and the gauge records 116. VIC is
modestly wet of Budyko and the gauge modestly dry of it — consistent with CMFD's
undercatch-corrected precipitation *plus* real consumptive use on the Songnen Plain and
reservoir regulation. Report it; do not calibrate it away. NSE at Harbin is **bias-limited,
not timing-limited**: remove the volume bias post hoc and NSE_val ≈ 0.80 = r².

---

<!-- NOTE: Mac development paths below are stale on the server. Use /mnt/disk1/Hydrocraft_server/ paths instead. -->

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
