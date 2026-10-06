# HYDAT observations data KI / HYDAT 观测数据 KI

This task-workflow KI reads already acquired HYDAT SQLite data. It does not run
CRHM or another scientific model, supply weather, calibrate a model, or download
data. Attribute its preparation results to `HYDAT_Observations`.

## Mandatory execution policy

Use `tools/read_observations.py` for a reviewed `check` or `prepare` step. Read
`docs/format_spec.yaml` first. Require an exact station number and native date
range; inspect the returned station coordinates before using the extraction.
Preserve the acquired database. Choose a new output directory outside raw data.
Do not silently drop quality symbols, interpolate missing days, assign UTC, or
convert discharge into basin-depth runoff. Those need a separate scientific
decision and documented transformation.

```text
python tools/read_observations.py --source inputs/observations/Hydat.sqlite3 --station 05AA008 --start 2018-01-01 --end 2020-12-31 --output-dir outputs/hydat_station
```

Run the tool from the project's working directory, using the installed KI's
absolute tool path and configured Python. The example names a real station but
requires a separately acquired database; no raw national archive is bundled.
Exit 0 means extraction completed. Inspect `audit.json`: `review_required`
means gaps, invalid values, duplicates or negative flows need review. Even
`extracted` does not assert field QC or model agreement. Every native quality
symbol is retained, including ice-condition flags; decide inclusion separately.

`preflight_check.py` checks runtime imports and the reader's help entrypoint.
`tests/test_hydat_reader.py` exercises the clearly synthetic fixture. Installation
requires Python 3.11+ standard library only, not a native model executable.
This package is suitable for the installed data-KI library; this does not claim
the database server currently attaches KIs to downloads.

## 中文说明

本 KI 只读取已经获取的 HYDAT SQLite 文件，输出实测逐日流量及审计报告；不运行
CRHM，不提供气象，不校准模型，也不下载数据。结果归属于 `HYDAT_Observations`。
先确认站号、时段和实际坐标，再将读取步骤纳入批准计划。原始数据库保持不变，
输出目录必须是新目录。缺日、NULL、重复日、无效数值和原始质量符号均保留或明确报告。
不得自动补齐数据、丢弃冰况标记、假定 UTC，或把流量直接当作流域平均径流深度。
返回码 0 仅代表提取成功，仍须阅读审计报告；它不证明观测通过质量审核或模型吻合。
随包示例是合成格式测试，不是真实观测。运行环境只需 Python 3.11+ 标准库。
