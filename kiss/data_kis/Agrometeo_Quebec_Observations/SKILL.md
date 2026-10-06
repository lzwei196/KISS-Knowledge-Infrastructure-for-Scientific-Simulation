# Agrometeo Québec observations data KI / 魁北克土壤温度观测 KI

This task-workflow KI reads acquired `soilTemp10cm_*.csv` files. It does not run
SHAW or another model. Its supported delivery contains soil temperature only;
catalogue weather descriptions are not proof that weather is in these files.
Attribute its preparation results to `Agrometeo_Quebec_Observations`.

## Mandatory execution policy

Use `tools/read_observations.py` in a reviewed `check` or `prepare` step. Read
`docs/format_spec.yaml`. Select the exact native station name and date range.
Preserve raw bytes and use a fresh output directory outside the input directory.
The reader streams the complete supplied files and preserves selected raw field
texts. It performs no interpolation, resampling, unit conversion or model work.

```text
python tools/read_observations.py --source inputs/observations/agrometeo_quebec --station Compton --start 2022-01-01 --end 2022-12-31 --output-dir outputs/agrometeo_station
```

Use the installed KI's absolute tool path and configured Python, with the
project as working directory. A source directory scans matching yearly files;
explicit file arguments can limit the scan to selected years. The example needs
separately acquired observations, which are not bundled with this package.
Distinct sources must have unique basenames because exported rows identify their
source by basename and CSV record number; ambiguous names are rejected.

Read `audit.json` after exit 0. `review_required` reports missing/invalid data,
duplicate/off-hour timestamps, coordinate inconsistencies or suspected sentinel
values. Selected rows outside the period or with unreadable timestamps are
preserved separately with reasons. `extracted` is not scientific QC or agreement
with SHAW. Native timestamps contain no timezone; the nominal 10 cm depth comes
from filenames, not a per-sensor field. Do not invent UTC, QC flags, weather,
soil moisture, snow or site parameters from this delivery.

`preflight_check.py` checks standard-library imports and the help entrypoint;
`tests/test_agrometeo_reader.py` exercises clearly synthetic fixtures, including UTF-8 and
CP1252 headers. Python 3.11+ is sufficient. The Desktop development source bundles
this data KI; server-side companion delivery is not claimed.

## 中文说明

本 KI 读取已获取的年度土壤温度 CSV，结果归属于 `Agrometeo_Quebec_Observations`，
不代表 SHAW 已运行。选择准确站名和时段，保留原始文件，结果另存新目录。
逐行读取全部指定文件，保留原始字段、缺失值及重复时间；有问题时审计报告标为
`review_required`。时段外或时间无法解析的目标站记录另存并注明原因。
原始文件没有明确时区、QC、气象、土壤水分或积雪字段；不能编造。10 cm 深度仅有
文件名依据，仍需核实传感器信息。读取成功不等于观测通过科学质量审核，更不等于
模型通过实测验证。随包示例是合成格式测试，环境只需 Python 3.11+ 标准库。
多个不同源文件必须具有唯一文件名，避免输出的来源名称和记录序号产生歧义。
