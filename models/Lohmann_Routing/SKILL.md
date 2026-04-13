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

---

<!-- NOTE: Mac development paths below are stale on the server. Use /mnt/disk1/Hydrocraft_server/ paths instead. -->

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
