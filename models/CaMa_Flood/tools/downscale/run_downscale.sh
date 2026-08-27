#!/bin/sh

#==========================================================
# CaMa-Flood 降尺度脚本 (通用版本)
# 用途: 将15min分辨率的洪水淹没深度降尺度到1min高分辨率
#==========================================================

# --- 用户配置区 ---
BASIN="$1"        # 流域名称
SYEAR="$2"        # 开始年份
SMON="$3"         # 开始月份
EYEAR="$4"        # 结束年份
EMON="$5"         # 结束月份
RES="${6:-1min}"  # 目标分辨率 (默认1min)

# 验证参数
if [ -z "$BASIN" ] || [ -z "$SYEAR" ] || [ -z "$SMON" ] || [ -z "$EYEAR" ] || [ -z "$EMON" ]; then
  echo "❌ 用法: $0 <流域名> <开始年> <开始月> <结束年> <结束月> [分辨率]"
  echo "示例: $0 yichang 2024 7 2024 7 1min"
  exit 1
fi

# --- 路径配置 (自动推断) ---
BASE="/Volumes/Expansion2t/hydro-model-workspace"
MAPDIR="${BASE}/model/cmf_v420_pkg/map/${BASIN}_15min/"
OUTDIR="${BASE}/model/cmf_v420_pkg/out/${BASIN}_${SYEAR}_bin/"
DOWNSCALE_TOOL="${BASE}/model/cmf_v420_pkg/etc/downscale_flddph"
RESULT_DIR="${BASE}/outputs/${BASIN}/cama_downscale"

# 验证路径
if [ ! -d "$MAPDIR" ]; then
  echo "❌ Map目录不存在: $MAPDIR"
  exit 1
fi

if [ ! -d "$OUTDIR" ]; then
  echo "❌ 输出目录不存在: $OUTDIR"
  echo "提示: 请先运行CaMa-Flood binary输出模式"
  exit 1
fi

if [ ! -d "$DOWNSCALE_TOOL" ]; then
  echo "❌ 降尺度工具不存在: $DOWNSCALE_TOOL"
  exit 1
fi

# 检查binary文件
BINARY_FILE="${OUTDIR}/flddph${SYEAR}.bin"
if [ ! -f "$BINARY_FILE" ]; then
  echo "❌ Binary文件不存在: $BINARY_FILE"
  exit 1
fi

# --- 读取空间范围 (从diminfo) ---
DIMINFO="${MAPDIR}/diminfo_${BASIN}_025deg.txt"
if [ ! -f "$DIMINFO" ]; then
  echo "❌ diminfo文件不存在: $DIMINFO"
  exit 1
fi

WEST=$(sed -n '8p' "$DIMINFO" | awk '{print $1}')
EAST=$(sed -n '9p' "$DIMINFO" | awk '{print $1}')
NORTH=$(sed -n '10p' "$DIMINFO" | awk '{print $1}')
SOUTH=$(sed -n '11p' "$DIMINFO" | awk '{print $1}')

# --- 输出配置信息 ---
TAG="${BASIN}_${SYEAR}"
if [ "$SMON" != "1" ] || [ "$EMON" != "12" ]; then
  TAG="${TAG}_M$(printf %02d $SMON)-$(printf %02d $EMON)"
fi

echo "========================================="
echo "🌊 CaMa-Flood 降尺度处理"
echo "========================================="
echo "流域:   $BASIN"
echo "时间:   ${SYEAR}年${SMON}月 - ${EYEAR}年${EMON}月"
echo "分辨率: $RES"
echo "范围:   $WEST°E - $EAST°E, $SOUTH°N - $NORTH°N"
echo "========================================="
echo ""

# --- 创建结果目录 ---
mkdir -p "$RESULT_DIR"

# --- 进入降尺度工具目录 ---
cd "$DOWNSCALE_TOOL" || exit 1

# --- 清理旧的软链接 ---
rm -f map out

# --- 创建软链接 ---
echo "📁 创建软链接..."
ln -sf "$MAPDIR" map
ln -sf "$OUTDIR" out

# --- 执行降尺度计算 ---
echo ""
echo "🔄 开始降尺度计算..."
echo "命令: ./t01-downscale.sh $WEST $EAST $SOUTH $NORTH $SYEAR $SMON $EYEAR $EMON $RES"
echo ""

./t01-downscale.sh $WEST $EAST $SOUTH $NORTH $SYEAR $SMON $EYEAR $EMON $RES

if [ $? -ne 0 ]; then
  echo ""
  echo "❌ 降尺度计算失败"
  exit 1
fi

echo ""
echo "✅ 降尺度计算完成"

# --- 执行可视化 ---
echo ""
echo "🎨 开始生成可视化..."

NGRID=1        # 网格显示参数
MAXDPH=10.0    # 最大深度(m)

./t02-draw_flddph.sh $WEST $EAST $SOUTH $NORTH $SYEAR $SMON $EYEAR $EMON $RES $NGRID $MAXDPH

if [ $? -ne 0 ]; then
  echo ""
  echo "⚠️  可视化生成失败，但降尺度数据已完成"
fi

echo ""
echo "✅ 可视化完成"

# --- 移动结果到指定目录 ---
echo ""
echo "📦 整理结果..."

# 删除可能存在的旧结果
rm -rf "${RESULT_DIR}/flood_${TAG}"
rm -rf "${RESULT_DIR}/fig_${TAG}"

# 移动新结果
if [ -d "flood" ]; then
  mv flood "${RESULT_DIR}/flood_${TAG}"
  echo "   ✓ 数据文件: ${RESULT_DIR}/flood_${TAG}/"
fi

if [ -d "fig" ]; then
  mv fig "${RESULT_DIR}/fig_${TAG}"
  echo "   ✓ 可视化图: ${RESULT_DIR}/fig_${TAG}/"
fi

# --- 统计结果 ---
echo ""
echo "========================================="
echo "✅ 降尺度处理完成！"
echo "========================================="

if [ -d "${RESULT_DIR}/flood_${TAG}" ]; then
  NUM_FILES=$(ls -1 "${RESULT_DIR}/flood_${TAG}"/*.nc 2>/dev/null | wc -l | xargs)
  TOTAL_SIZE=$(du -sh "${RESULT_DIR}/flood_${TAG}" | awk '{print $1}')
  echo "📊 生成 ${NUM_FILES} 个高分辨率NetCDF文件 (${TOTAL_SIZE})"
fi

if [ -d "${RESULT_DIR}/fig_${TAG}" ]; then
  NUM_FIGS=$(ls -1 "${RESULT_DIR}/fig_${TAG}"/*.png 2>/dev/null | wc -l | xargs)
  echo "🖼️  生成 ${NUM_FIGS} 张可视化PNG图片"
fi

echo ""
echo "📁 结果路径: ${RESULT_DIR}/"
echo "========================================="
