#!/bin/bash

#==========================================================
# CaMa-Flood 降尺度主脚本
# 一键完成: CaMa模拟(Binary) → 降尺度计算 → 可视化生成
#==========================================================

set -e  # 遇到错误立即退出

# --- 参数解析 ---
BASIN="$1"
YEAR="$2"
SMON="$3"
EMON="$4"
RES="${5:-1min}"
VISUALIZE="${6:-yes}"

# --- 帮助信息 ---
if [ -z "$BASIN" ] || [ -z "$YEAR" ] || [ -z "$SMON" ] || [ -z "$EMON" ]; then
  cat << EOF
========================================
🌊 CaMa-Flood 降尺度一键运行脚本
========================================

用法: $0 <流域名> <年份> <开始月> <结束月> [分辨率] [是否可视化]

参数说明:
  流域名      : 如 yichang, huaihe, huanghe
  年份        : 如 2024
  开始月      : 1-12
  结束月      : 1-12
  分辨率      : 1min (默认), 15sec, 30sec
  是否可视化  : yes (默认), no

示例:
  $0 yichang 2024 7 7                    # 宜昌流域2024年7月
  $0 huaihe 2020 6 9 1min yes            # 淮河流域2020年6-9月，生成可视化
  $0 huanghe 2019 1 12 15sec no          # 黄河流域2019年全年，不可视化

========================================
EOF
  exit 1
fi

# --- 路径配置 ---
BASE="/Volumes/Expansion2t/hydro-model-workspace"
SKILL_DIR="${BASE}/skills/cama-downscale"
CAMA_BASE="${BASE}/model/cmf_v420_pkg"
RESULT_DIR="${BASE}/outputs/${BASIN}/cama_downscale"

# --- 输出配置信息 ---
echo "========================================"
echo "🌊 CaMa-Flood 降尺度一键运行"
echo "========================================"
echo "流域:   $BASIN"
echo "时间:   ${YEAR}年${SMON}月 - ${YEAR}年${EMON}月"
echo "分辨率: $RES"
echo "可视化: $VISUALIZE"
echo "========================================"
echo ""

# --- Step 1: 运行CaMa-Flood (Binary输出) ---
echo "📍 Step 1/3: 运行CaMa-Flood模拟 (Binary输出模式)"
echo "----------------------------------------"

CAMA_SCRIPT="${CAMA_BASE}/gosh/run_${BASIN}_bin.sh"
CAMA_OUTPUT="${CAMA_BASE}/out/${BASIN}_${YEAR}_bin"

# 检查CaMa运行脚本
if [ ! -f "$CAMA_SCRIPT" ]; then
  echo "❌ CaMa运行脚本不存在: $CAMA_SCRIPT"
  echo ""
  echo "请先创建Binary输出版本的CaMa运行脚本:"
  echo "  1. 复制现有脚本: cp ${CAMA_BASE}/gosh/run_yichang_bin.sh ${CAMA_SCRIPT}"
  echo "  2. 修改流域名和年份配置"
  echo "  3. 确保 LOUTCDF = .FALSE. 和 CVARSOUT = 'flddph'"
  exit 1
fi

# 检查是否已有输出
BINARY_FILE="${CAMA_OUTPUT}/flddph${YEAR}.bin"
if [ -f "$BINARY_FILE" ]; then
  FILE_SIZE=$(ls -lh "$BINARY_FILE" | awk '{print $5}')
  echo "✓ Binary文件已存在: $BINARY_FILE (${FILE_SIZE})"
  echo "  跳过CaMa模拟步骤"
  echo ""
else
  echo "运行: $CAMA_SCRIPT"
  echo ""

  START_TIME=$(date +%s)
  bash "$CAMA_SCRIPT"
  END_TIME=$(date +%s)
  ELAPSED=$((END_TIME - START_TIME))

  # 验证输出
  if [ ! -f "$BINARY_FILE" ]; then
    echo ""
    echo "❌ CaMa模拟失败: Binary文件未生成"
    exit 1
  fi

  FILE_SIZE=$(ls -lh "$BINARY_FILE" | awk '{print $5}')
  echo ""
  echo "✅ CaMa模拟完成 (耗时: ${ELAPSED}秒)"
  echo "   输出文件: $BINARY_FILE (${FILE_SIZE})"
  echo ""
fi

# --- Step 2: 降尺度计算 ---
echo "📍 Step 2/3: 降尺度计算 (15min → ${RES})"
echo "----------------------------------------"

DOWNSCALE_SCRIPT="${SKILL_DIR}/run_downscale.sh"

if [ ! -f "$DOWNSCALE_SCRIPT" ]; then
  echo "❌ 降尺度脚本不存在: $DOWNSCALE_SCRIPT"
  exit 1
fi

echo "运行: $DOWNSCALE_SCRIPT $BASIN $YEAR $SMON $YEAR $EMON $RES"
echo ""

START_TIME=$(date +%s)
bash "$DOWNSCALE_SCRIPT" "$BASIN" "$YEAR" "$SMON" "$YEAR" "$EMON" "$RES"
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

# 验证输出
TAG="${BASIN}_${YEAR}"
if [ "$SMON" != "1" ] || [ "$EMON" != "12" ]; then
  TAG="${TAG}_M$(printf %02d $SMON)-$(printf %02d $EMON)"
fi

FLOOD_DIR="${RESULT_DIR}/flood_${TAG}"
if [ ! -d "$FLOOD_DIR" ]; then
  echo ""
  echo "❌ 降尺度计算失败: 输出目录未生成"
  exit 1
fi

NUM_FILES=$(ls -1 "$FLOOD_DIR"/*.bin 2>/dev/null | wc -l | xargs)
TOTAL_SIZE=$(du -sh "$FLOOD_DIR" | awk '{print $1}')

echo ""
echo "✅ 降尺度计算完成 (耗时: ${ELAPSED}秒)"
echo "   输出目录: $FLOOD_DIR"
echo "   生成文件: ${NUM_FILES} 个 (${TOTAL_SIZE})"
echo ""

# --- Step 3: 可视化生成 (可选) ---
if [ "$VISUALIZE" == "yes" ] || [ "$VISUALIZE" == "y" ] || [ "$VISUALIZE" == "Y" ]; then
  echo "📍 Step 3/3: 生成可视化图片"
  echo "----------------------------------------"

  VIS_SCRIPT="${SKILL_DIR}/visualize_flddph.sh"

  if [ ! -f "$VIS_SCRIPT" ]; then
    echo "❌ 可视化脚本不存在: $VIS_SCRIPT"
    exit 1
  fi

  echo "运行: $VIS_SCRIPT $BASIN $YEAR $SMON $YEAR $EMON $RES"
  echo ""

  START_TIME=$(date +%s)
  bash "$VIS_SCRIPT" "$BASIN" "$YEAR" "$SMON" "$YEAR" "$EMON" "$RES"
  END_TIME=$(date +%s)
  ELAPSED=$((END_TIME - START_TIME))

  # 验证输出
  FIG_DIR="${RESULT_DIR}/fig_${TAG}"
  if [ ! -d "$FIG_DIR" ]; then
    echo ""
    echo "⚠️  可视化生成失败，但降尺度数据已完成"
  else
    NUM_FIGS=$(ls -1 "$FIG_DIR"/*.jpg 2>/dev/null | wc -l | xargs)
    TOTAL_SIZE=$(du -sh "$FIG_DIR" | awk '{print $1}')

    echo ""
    echo "✅ 可视化生成完成 (耗时: ${ELAPSED}秒)"
    echo "   输出目录: $FIG_DIR"
    echo "   生成图片: ${NUM_FIGS} 张 (${TOTAL_SIZE})"
    echo ""
  fi
else
  echo "📍 Step 3/3: 跳过可视化生成"
  echo "----------------------------------------"
  echo "如需生成可视化，运行:"
  echo "  bash ${SKILL_DIR}/visualize_flddph.sh $BASIN $YEAR $SMON $YEAR $EMON $RES"
  echo ""
fi

# --- 总结 ---
echo "========================================"
echo "✅ 降尺度处理全部完成！"
echo "========================================"
echo "📂 结果路径: ${RESULT_DIR}/"
echo ""
echo "📁 降尺度数据:"
echo "   ${FLOOD_DIR}/"
echo "   ${NUM_FILES} 个逐日binary文件"
echo ""

if [ "$VISUALIZE" == "yes" ] && [ -d "$FIG_DIR" ]; then
  echo "🖼️  可视化图片:"
  echo "   ${FIG_DIR}/"
  echo "   ${NUM_FIGS} 张JPEG图片"
  echo ""

  # 显示第一张图片路径供预览
  FIRST_FIG=$(ls "$FIG_DIR"/*.jpg 2>/dev/null | head -1)
  if [ -n "$FIRST_FIG" ]; then
    echo "🔍 预览第一张图片:"
    echo "   open \"$FIRST_FIG\""
    echo ""
  fi
fi

echo "========================================"
