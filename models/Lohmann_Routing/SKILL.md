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
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (1 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (3 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (23 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (15 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `s5_routing_param/run_build_routing_new.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s5_routing_param/run_build_routing_new.py --help` |
| `tools/preprocess_vic_for_routing.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/preprocess_vic_for_routing.py --help` |

*2 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---

# Lohmann Routing -- Knowledge Infrastructure Skill Document

> **Version**: route_1.0
> **Domain**: hydrology / river routing
> **Last updated**: 2026-08-18
> **Validation status**: see `knowledge_infrastructure.yaml` and `docs/validation_convention.yaml`

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | Lohmann Routing / VIC Routing module |
| Version | route_1.0 |
| Language | Fortran |
| Primary domain | Hydrology, river routing |
| Spatial mode | Distributed gridded routing to defined station/outlet locations |
| Executable | `route_1.0/src/rout` after compilation |
| KI contract | `dag.yaml` defines observable outputs; `docs/validation_convention.yaml` defines the cited validation bars |

## 2. What This Model Does

This KI runs the Lohmann/VIC routing module to route upstream hydrological-model runoff and baseflow into streamflow at configured stations or outlets. The model uses gridded flow direction, fraction, distance mask, station location, and unit hydrograph inputs, then writes daily, monthly, yearly, and depth-normalized discharge products.

## 3. Input Requirements

**Exact shapes live in `docs/format_spec.yaml`** (projected from `dag.yaml` and `diagnostics/triplets.yaml`; regenerate it, never hand-edit it). This section explains intent and common traps; the spec file is the contract.

### 3.1 Upstream Hydrological Inputs

Routing expects preprocessed VIC-style daily files with exactly seven no-header columns:

```text
YEAR MONTH DAY PREC EVAP RUNOFF BASEFLOW
```

For VIC 5.x output, do not feed the raw 22+ column files directly. Preprocess each file to the seven routing columns documented below in "重要：VIC输出预处理（必须步骤）".

### 3.2 Static Routing Inputs

| Input | Purpose | Notes |
|-------|---------|-------|
| Flow direction file (`*_direc.txt`) | D8 routing direction grid | Prepared by the routing parameter build workflow |
| Fraction file (`*_frac.txt`) | Active basin/grid area fraction | Must align with the VIC grid |
| Distance mask (`*_xmask.txt`) | Flow distance / mask grid | Coordinate origin must match VIC file naming |
| Station file (`*_staloc.txt`) | Outlet/station position | Must include the required second line (`NONE` or `.uh_s` path) |
| Unit hydrograph file (`UH.all`) | Routing response parameters | Must use the documented 12-line format |
| Global configuration (`rout_global.txt`) | Model run control | See the checklist below for line-by-line expectations |

### 3.3 Configuration Files

| File | Format | Notes |
|------|--------|-------|
| `rout_global.txt` | Fixed-order text control file | Paths are line-position sensitive; avoid long absolute paths that Fortran may truncate |
| `*_staloc.txt` | Two-line station control | First line has station count/name/grid location; second line is `NONE` or a `.uh_s` file path |
| `UH.all` | Whitespace-delimited 12-line table | Each row contains a time index and unit-hydrograph weight |

## 4. Build Instructions

Compile the actual Fortran routing executable when `rout` is missing or stale:

```bash
cd /path/to/route_1.0/src
make clean
make
```

Known build issue: if the model reports `Incorrect dimensions: Reset nrow and ncol in main to X Y`, edit the Fortran `NROW` and `NCOL` parameters to fit the domain, then rebuild.

## 5. Execution

Before any run, execute the KI preflight:

```bash
python preflight_check.py
```

Then run the real model executable with the prepared global configuration:

```bash
/path/to/route_1.0/src/rout rout_global.txt
```

The complete operational sequence is documented below in "完整运行流程"; follow that sequence before attempting custom orchestration.

## 6. Output Description

**Source: `dag.yaml`.** The dag is the model's identity: every observable output's `var`, unit, description, and validation rank live there. If this section ever disagrees with `dag.yaml`, `dag.yaml` wins and this section must be corrected.

**Headline output** (the dag's `validation_rank: 1` variable -- the one this model is judged by):

> `discharge_daily` -- Routed daily streamflow at each defined station/outlet (FLOW). (`m3/s`)

| Output variable (dag `var`) | Rank / role | Unit stated in this section | Description |
|-----------------------------|-------------|-----------------------------|-------------|
| `discharge_daily` | rank 1 headline output | `m3/s` | Routed daily streamflow at each defined station/outlet (FLOW). |
| `discharge_monthly` | other dag output | see `dag.yaml` | listed by the dag; read `dag.yaml` for the source description |
| `discharge_yearly` | other dag output | see `dag.yaml` | listed by the dag; read `dag.yaml` for the source description |
| `discharge_daily_mm` | other dag output | see `dag.yaml` | listed by the dag; read `dag.yaml` for the source description |
| `discharge_monthly_mm` | other dag output | see `dag.yaml` | listed by the dag; read `dag.yaml` for the source description |

Runtime files documented by this KI include `XX.day`, `XX.day_mm`, `XX.month`, `XX.month_mm`, `XX.year`, and `XX.uh_s`; see "输出文件说明" for file-level details.

## 7. Tool Inventory

| Tool / component | Purpose | Inputs | Outputs |
|------------------|---------|--------|---------|
| `preflight_check.py` | Verify environment, binary/package, and data availability | KI directory | `PREFLIGHT_REPORT=` line and pass/fail status |
| `tools/` | Executable KI pipeline stages | Stage-specific inputs | Stage-specific outputs |
| `run_build_routing_new.py` workflow | Build routing parameter files | Soil parameters, DEM, basin boundary, outlet/station information | Direction, fraction, xmask, staloc, unit hydrograph, global config |
| `route_1.0/src/rout` | Run the actual routing model | `rout_global.txt` plus routing/VIC input files | Station/outlet discharge files |

Shared forcing utilities are available for upstream data work:

```python
from ki_tools_common.load_forcing import load_daily_forcing
```

## 8. Unit Table / Unit Conversion Table

**Source: `dag.yaml` and the KI's routing format notes.** This unit table documents the units that must be preserved or checked when preparing inputs and reading outputs. Do not infer additional output units here; for full machine-readable shapes, read `docs/format_spec.yaml`.

| Variable / file product | Source unit or source form | Model/output unit | Conversion / handling | Type |
|-------------------------|----------------------------|-------------------|-----------------------|------|
| `RUNOFF` input column | upstream VIC/routing-preprocessed daily value | routing input column | extracted from VIC output column 16 in the documented preprocessing script | column selection |
| `BASEFLOW` input column | upstream VIC/routing-preprocessed daily value | routing input column | extracted from VIC output column 17 in the documented preprocessing script | column selection |
| `EVAP` input column | upstream VIC/routing-preprocessed daily value | routing input column | extracted from VIC output column 18 in the documented preprocessing script | column selection |
| `discharge_daily` | model-routed streamflow | `m3/s` | no post-run unit conversion for the headline FLOW output | output unit |
| `XX.day` | routing output file | `m3/s` | read as daily flow with columns `year month day flow` | output unit |
| `XX.day_mm` | routing output file | `mm` | read as daily depth-normalized flow | output unit |
| `XX.month` | routing output file | `m3/s` | read as monthly mean flow | output unit |
| `XX.month_mm` | routing output file | `mm` | read as monthly depth-normalized flow | output unit |
| `XX.year` | routing output file | `m3/s` | read as monthly flow summary by month | output unit |

## 8c. Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|--------------------------|--------------------|-----------------|
| `discharge_daily` | Routed streamflow at station/outlet in `m3/s` | Depth-normalized discharge in `mm` | Metrics compare wrong magnitude and may fail silently |
| `discharge_daily_mm` | Depth-normalized daily discharge output | Absolute streamflow in `m3/s` | Flow-volume interpretation is wrong |
| `RUNOFF` / `BASEFLOW` inputs | Routed from the preprocessed VIC runoff/baseflow columns | Raw VIC 22+ column file | Routing reads wrong columns, producing extreme or negative flows |

Output unit verification checklist:

- Read the `dag.yaml` output definition before scoring any output.
- Confirm that `discharge_daily` is the rank-1 `m3/s` FLOW variable.
- Print the first rows of `XX.day` and check that the four columns are year, month, day, and flow.
- Do not compare `XX.day_mm` or `XX.month_mm` directly against `m3/s` observed discharge.

## 9. Diagnostic Triplets (Top 5)

The full error corpus is `diagnostics/triplets.yaml`; check it first on any failure. These rows cite real triplet IDs and intentionally summarize rather than duplicate the YAML.

| ID | Error / symptom | Diagnosis | Remedy |
|----|-----------------|-----------|--------|
| `dt_001` | Routing runs but writes no output | Flow-direction network may not reach the outlet | Rebuild routing parameters with the documented connect-and-repair workflow |
| `dt_002` | Model exits immediately with no output | `staloc` file format is incomplete | Ensure the file has the station line and a second line containing `NONE` or a `.uh_s` path |
| `dt_003` | End-of-file while reading `UH.all` | Unit hydrograph file does not match the expected 12-line form | Regenerate or rewrite `UH.all` with index and weight on each line |
| `dt_005` | Extreme or negative discharge values | Raw VIC output columns were fed to routing | Preprocess VIC 5.x output to the seven routing columns |
| `dt_006` | `NOT FOUND` or all-zero/NaN output with existing files | Fortran path truncation | Use short symlinked paths or run from a short-path directory |

## 10. Coupling Interfaces

| Upstream model | Variable exchanged | Unit | Temporal resolution |
|----------------|-------------------|------|---------------------|
| VIC / mHM / other upstream hydrological model | Runoff and baseflow routed through the seven-column input format | use upstream-preprocessed routing columns | daily |

| Downstream use | Variable exchanged | Unit | Temporal resolution |
|----------------|-------------------|------|---------------------|
| Observed discharge validation / station hydrograph analysis | `discharge_daily` | `m3/s` | daily |
| Monthly validation / summaries | `discharge_monthly` | see `dag.yaml` | monthly |

## 11. Validated Results

**Source: `docs/validation_convention.yaml`.** A metric value without the field's pass-band is not a verdict. The convention file wins over remembered thresholds. Null convention bands are written as "no cited threshold".

### Headline Validation Variable

| Property | Value |
|----------|-------|
| Dag variable | `discharge_daily` |
| Rank | 1 |
| Unit | `m3/s` |
| Description | Routed daily streamflow at each defined station/outlet (FLOW). |

### Convention Bars

| Dag variable | Metric | Direction | Very good | Good | Satisfactory | Citation keys |
|--------------|--------|-----------|-----------|------|--------------|---------------|
| `discharge_daily` | `nse` | maximize | `0.8` (`moriasi2015`, `arnold2012`) | `0.7` (`moriasi2015`, `arnold2012`) | `0.5` (`moriasi2015`, `arnold2012`) | `moriasi2015`, `arnold2012` |
| `discharge_daily` | `pbias` | zero_centered | `5.0` (`moriasi2015`, `arnold2012`) | `10.0` (`moriasi2015`, `arnold2012`) | `15.0` (`moriasi2015`, `arnold2012`) | `moriasi2015`, `arnold2012` |
| `discharge_daily` | `csi` | maximize | no cited threshold | no cited threshold | no cited threshold | none |
| `discharge_monthly` | `nse` | maximize | `0.8` (`moriasi2015`, `arnold2012`) | `0.7` (`moriasi2015`, `arnold2012`) | `0.5` (`moriasi2015`, `arnold2012`) | `moriasi2015`, `arnold2012` |
| `discharge_monthly` | `pbias` | zero_centered | `5.0` (`moriasi2015`, `arnold2012`) | `10.0` (`moriasi2015`, `arnold2012`) | `15.0` (`moriasi2015`, `arnold2012`) | `moriasi2015`, `arnold2012` |

### Achieved Results

This SKILL does not state achieved calibration or validation metric values. To judge a run, compute metrics against observed discharge and compare them with the convention bars above; the cited bars come from `docs/validation_convention.yaml`.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Routing executable | Actual Fortran model | Required | The mandatory policy forbids substituting a simplified formula |
| Upstream runoff/baseflow | VIC, mHM, or equivalent hydrological-model outputs | Required | Must be converted to the seven-column routing input format |
| Observed discharge | `data_ki/ObservedQ/SKILL.md` | Required for validation | Use for station/outlet validation |
| Field performance bars | `docs/validation_convention.yaml` | Required for verdicts | Use cited per-variable bars above |

## 12. Parameter Selection by Region

This KI does not provide regional calibrated parameter tables. Use the routing parameter preparation workflow below to derive basin-specific direction, fraction, xmask, station, and unit hydrograph files from the domain DEM, basin boundary, VIC grid, and outlet information.

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: This model takes runoff from upstream hydrological models (VIC, mHM, etc.) as input.
See `data_ki/ObservedQ/SKILL.md` for observed discharge validation data.


<!-- NOTE: Mac development paths below are stale on the server. Use KISSPATH_ROOT/ paths instead. -->

# VIC Routing汇流模型运行指南

## 概述

本skill用于运行VIC水文模型的Routing汇流模块，将VIC产流结果转换为河道流量。

## 关键路径

- **Routing可执行文件 (route_1.0)**: `/Volumes/Expansion4t/hydro-space2/model/route_1.0/src/rout`
- **Routing参数制备脚本**: `/Volumes/Expansion4t/hydro-space2/skills/routing-run/s5_routing_param/run_build_routing_new.py`
- **Routing配置目录**: `/Volumes/Expansion4t/hydro-space2/docs/rout/`
- **VIC结果目录**: `/Volumes/Expansion4t/hydro-space2/outputs/{流域名}/vic_result/`
- **VIC预处理目录**: `/Volumes/Expansion4t/hydro-space2/outputs/{流域名}/vic_for_routing/`

---

## Routing参数自动制备

### 使用方法

1. 复制 `run_build_routing_new.py` 到工作目录
2. 修改脚本中的配置参数:
   - `SOIL_PARAM_PATH`: VIC土壤参数文件路径
   - `DEM_PATH`: DEM文件路径
   - `BASIN_SHP`: 流域边界shapefile路径
   - `OUTPUT_DIR`: 输出目录
   - `STATION_NAME`: 站点名称
   - `OUTLET_LON/LAT`: 出口经纬度（可选，脚本会自动找最大累积量点）
3. 运行脚本: `python run_build_routing_new.py`

### 生成文件

| 文件 | 说明 |
|------|------|
| XX_direc.txt | 流向文件 (D8编码) |
| XX_frac.txt | 面积比例文件 |
| XX_xmask.txt | 流动距离文件 |
| XX_staloc.txt | 站点位置文件 |
| UH.all | 单位线参数文件 |
| rout_global.txt | routing配置文件 |

### 流向计算算法

脚本使用**"先计算后修复"**的两阶段策略确保流向网络全连通:

**阶段1 - 初始计算**:
- 使用WhiteboxTools计算高分辨率DEM的D8流向和汇流累积量
- 将累积量聚合到粗分辨率VIC网格
- 每个VIC格点流向其8邻域中累积量最大且大于自身的邻居

**阶段2 - 迭代修复**:
- 检测无法到达出口的格点
- 将断开格点的流向设置为能到达出口的邻居中累积量最大者
- 重复迭代直到所有格点连通

---

## 重要：VIC输出预处理（必须步骤）

### 问题背景

Routing模型期望的输入格式为：
```
YEAR MONTH DAY PREC EVAP RUNOFF BASEFLOW
```
（共7列，无表头）

但VIC 5.x的输出格式包含22+列，且有3行头部信息。如果直接使用VIC输出，Routing会读取错误的列导致：
- 流量值极端偏大（几万m³/s）
- 出现大量负值流量

### 预处理Python脚本

```python
import os
import pandas as pd

source_dir = "/path/to/vic_result"
dest_dir = "/path/to/vic_for_routing"
os.makedirs(dest_dir, exist_ok=True)

for filename in os.listdir(source_dir):
    if filename.endswith(".txt") and not filename.startswith("._"):
        source_path = os.path.join(source_dir, filename)
        new_filename = filename[:-4]
        dest_path = os.path.join(dest_dir, new_filename)

        df = pd.read_csv(source_path, sep=r'\s+', skiprows=3, header=None)
        df_out = df.iloc[:, [0, 1, 2, 3, 18, 16, 17]]
        df_out.to_csv(dest_path, sep='\t', header=False, index=False,
                     float_format='%.4f')

print(f"处理完成，输出目录: {dest_dir}")
```

---

## 运行前检查清单

### 全局参数文件 (rout_global.txt)

```
第3行:  流向文件路径
第5-6行: 流速设置 (.false. + 值 或 .true. + 文件路径)
第8-9行: 扩散系数设置
第11-12行: xmask设置
第14-15行: fraction设置
第17行: 站点文件路径
第19行: VIC输入文件路径前缀
第20行: 精度 (通常为4)
第22行: 输出路径 (必须以/结尾)
第24行: VIC输出时间范围
第25行: Routing输出时间范围
第27行: 单位线文件路径
```

---

## 常见问题及解决方案

### 问题1: 流向网络不连通

**症状**:
- routing模型运行但没有输出文件
- 只有少量格点被处理

**原因**:
高分辨率DEM流向聚合到粗分辨率VIC网格时，可能形成断开的流向网络。

**解决方案**:
使用 `run_build_routing_new.py` 脚本的"先计算后修复"算法，确保所有格点都能到达出口。

---

### 问题2: staloc文件格式错误

**症状**:
- 运行routing时无任何输出
- 模型立即结束

**原因**:
staloc文件必须包含两行：
```
1 XX 列号 行号 -9999
NONE
```
第二行是UH_S文件路径，`NONE`表示重新计算。

**解决方案**:
确保staloc文件有两行，第二行写`NONE`或已有的.uh_s文件路径。

---

### 问题3: UH.all文件格式错误

**症状**:
- 运行时报"End of file"错误
- 读取UH.all时出错

**原因**:
UH.all必须是12行格式：
```
   0   0.15
   1   0.40
   2   0.25
   ...
   11  0.0
```

**解决方案**:
使用正确的12行单位线格式，每行包含序号和权重值。

---

### 问题4: 模型维度不足

**症状**:
- 报错 "Incorrect dimensions: Reset nrow and ncol in main to X Y"

**原因**:
routing模型源码中的NROW和NCOL参数小于实际网格大小。

**解决方案**:
修改 `/path/to/route_1.0/src/rout.f` 中的参数:
```fortran
PARAMETER (NROW = 100, NCOL = 100)  ! 根据需要调整
```
然后重新编译: `make clean && make`

---

### 问题5: 流量值极端偏大或出现负值

**症状**:
- 月流量达到几万m³/s
- 出现大量负几千的流量值

**原因**:
Routing模型读取了VIC输出的错误列。

**解决方案**:
必须使用预处理脚本提取正确的列（见上文VIC输出预处理）。

---

### 问题6: Fortran路径长度限制

**症状**:
- 文件存在但报"NOT FOUND"
- 输出全为0或NaN

**原因**:
Fortran字符串长度限制为60-80字符，绝对路径被截断。

**解决方案**:
创建符号链接并使用相对路径：
```bash
cd /path/to/routing_config/
ln -sf /long/path/to/vic_for_routing vic_in
```

---

### 问题7: 坐标系统不匹配

**症状**:
- 大量 "XX.XXXX_YYY.YYYY NOT FOUND, INSERTING ZEROS"
- 输出流量全为0

**原因**:
辅助文件的网格坐标与VIC输出文件名不一致。

**检查方法**:
```bash
ls vic_for_routing/ | head -5    # 查看VIC文件坐标
head -6 XX_xmask.txt             # 查看xmask坐标定义
```

**解决方案**:
确保 xllcorner 和 yllcorner 设置正确，使网格中心坐标匹配VIC文件名。

---

### 问题8: routing_param目录内出现自引用符号链接（无限递归）

**症状**:
- `shutil.copytree` 报错 "Too many levels of symbolic links"
- 目录结构出现 `routing_param/routing_param/routing_param/...` 无限嵌套
- 文件系统操作（复制、遍历）导致程序崩溃或超时

**原因**:
在 `routing_param/` 目录内部创建了名为 `routing_param` 的符号链接，指向 `routing_param/` 目录本身，形成无限递归循环。这通常发生在处理 Fortran 路径长度限制时误操作。

**严格禁止的操作**:
```bash
# ❌ 绝对禁止！以下操作会创建自引用符号链接导致无限递归：
cd outputs/{basin_name}/routing_param/
ln -sf /path/to/outputs/{basin_name}/routing_param routing_param
# 这会在 routing_param/ 内创建 routing_param -> 自身，形成无限循环！

# ❌ 同样禁止：在 routing_param 内创建任何指向其自身或父级 routing_param 的链接
```

**正确做法**:
```bash
# ✅ 正确：在 routing_param 的外部（如/tmp）创建指向它的符号链接
ln -sf /long/path/to/outputs/{basin_name}/routing_param /tmp/rout_work
cd /tmp/rout_work
./rout_exe rout_global.txt

# ✅ 正确：在 routing_param 内部只创建指向其他目录的符号链接
cd outputs/{basin_name}/routing_param/
ln -sf /path/to/vic_for_routing vic_in          # OK：vic_in 指向不同的目录
ln -sf /path/to/route_1.0/src/rout rout_exe     # OK：rout_exe 指向可执行文件
```

**关键规则**: `routing_param/` 目录内部创建的符号链接的名称，绝不能与 `routing_param` 同名，也不能指向包含自身的路径。

---

### 问题9: UH_S文件已存在

**症状**:
- 报错 "Cannot open file 'XX .uh_s': File exists"

**解决方案**:
```bash
rm -f "XX   .uh_s"
```

---

## 完整运行流程

```bash
# 1. 制备routing参数
python run_build_routing_new.py

# 2. 创建VIC输入链接
cd /path/to/output_dir
ln -sf /path/to/vic_for_routing vic_in

# 3. 删除旧的UH_S文件
rm -f "XX   .uh_s"

# 4. 运行routing
/path/to/route_1.0/src/rout rout_global.txt

# 5. 查看结果
cat rout_out/XX*.day | head -10
```

---

## 输出文件说明

| 文件 | 内容 | 格式 |
|------|------|------|
| XX.day | 日流量 | 年 月 日 流量(m³/s) |
| XX.day_mm | 日流量 | 年 月 日 流量(mm) |
| XX.month | 月平均流量 | 年 月 流量(m³/s) |
| XX.month_mm | 月流量 | 年 月 流量(mm) |
| XX.year | 各月流量汇总 | 月 流量(m³/s) |
| XX.uh_s | 单位线响应 | 内部使用 |

---

## 编译route_1.0（如需要）

```bash
cd /path/to/route_1.0/src
make clean
make
```

需要gfortran编译器。编译成功后生成`rout`可执行文件。
