#!/bin/bash
#==========================================================
# 修复版可视化脚本 (使用虚拟环境中的python)
#==========================================================

# 激活虚拟环境
source /Users/yc/Desktop/project/python_env/bin/activate

BASIN="$1"
SYEAR="$2"
SMON="$3"
EYEAR="$4"
EMON="$5"
RES="${6:-1min}"

if [ -z "$BASIN" ] || [ -z "$SYEAR" ] || [ -z "$SMON" ]; then
  echo "用法: $0 <流域名> <开始年> <开始月> <结束年> <结束月> [分辨率]"
  exit 1
fi

# 路径配置
BASE="/Volumes/Expansion2t/hydro-model-workspace"
MAPDIR="${BASE}/model/cmf_v420_pkg/map/${BASIN}_15min/"
DOWNSCALE_TOOL="${BASE}/model/cmf_v420_pkg/etc/downscale_flddph"
RESULT_DIR="${BASE}/outputs/${BASIN}/cama_downscale"

# 读取空间范围
DIMINFO="${MAPDIR}/diminfo_${BASIN}_025deg.txt"
WEST=$(sed -n '8p' "$DIMINFO" | awk '{print $1}')
EAST=$(sed -n '9p' "$DIMINFO" | awk '{print $1}')
NORTH=$(sed -n '10p' "$DIMINFO" | awk '{print $1}')
SOUTH=$(sed -n '11p' "$DIMINFO" | awk '{print $1}')

# TAG
TAG="${BASIN}_${SYEAR}"
if [ "$SMON" != "1" ] || [ "$EMON" != "12" ]; then
  TAG="${TAG}_M$(printf %02d $SMON)-$(printf %02d $EMON)"
fi

FLOOD_DIR="${RESULT_DIR}/flood_${TAG}"
FIG_DIR="${RESULT_DIR}/fig_${TAG}"

if [ ! -d "$FLOOD_DIR" ]; then
  echo "错误: 降尺度数据目录不存在: $FLOOD_DIR"
  exit 1
fi

echo "========================================="
echo "🎨 生成降尺度可视化"
echo "========================================="
echo "数据目录: $FLOOD_DIR"
echo "输出目录: $FIG_DIR"
echo "========================================="
echo ""

# 进入工具目录
cd "$DOWNSCALE_TOOL" || exit 1

# 创建软链接到降尺度结果
rm -f flood
ln -sf "$FLOOD_DIR" flood

# 创建fig目录
rm -rf fig
mkdir -p fig

# 可视化参数
NGRID=1
MAXDPH=10.0

# 生成slope文件
echo "📊 准备地形数据..."
rm -f slp.bin
./src/conv_slp $WEST $EAST $SOUTH $NORTH $RES $NGRID

# 定义修复版的u02函数（使用python3）
draw_one_day() {
  local CDATE=$1
  local WEST=$2
  local EAST=$3
  local SOUTH=$4
  local NORTH=$5
  local NGRID=$6
  local MAXDPH=$7
  local RES=$8

  rm -f dph${CDATE}.bin
  ./src/conv_flood $WEST $EAST $SOUTH $NORTH $CDATE $NGRID $RES $MAXDPH
  python ./draw_flddph.py $WEST $EAST $SOUTH $NORTH $CDATE $NGRID $RES $MAXDPH
  rm -f dph${CDATE}.bin
}

# 导出函数供并行使用
export -f draw_one_day

# 生成日期列表
SDATE=$(( $SYEAR * 10000 + $SMON * 100 + 1 ))
EDATE=$(( $EYEAR * 10000 + $EMON * 100 + 31 ))

echo "🎨 开始生成可视化图片..."
COUNT=0

IYEAR=$SYEAR
while [ $IYEAR -le $EYEAR ]; do
  IMON=$SMON
  while [ $IMON -le $EMON ]; do
    NDAY=$(./src/igetday $IYEAR $IMON)
    IDAY=1

    while [ $IDAY -le $NDAY ]; do
      CDATE=$(( $IYEAR * 10000 + $IMON * 100 + $IDAY ))

      if [ $CDATE -ge $SDATE ] && [ $CDATE -le $EDATE ]; then
        echo "  处理 $CDATE ..."
        draw_one_day $CDATE $WEST $EAST $SOUTH $NORTH $NGRID $MAXDPH $RES
        COUNT=$((COUNT + 1))
      fi

      IDAY=$(( $IDAY + 1 ))
    done
    IMON=$(( $IMON + 1 ))
  done
  IYEAR=$(( $IYEAR + 1 ))
done

# 清理
rm -f slp.bin
rm -f flood

# 移动结果
if [ -d "fig" ]; then
  rm -rf "$FIG_DIR"
  mv fig "$FIG_DIR"
  echo ""
  echo "✅ 可视化完成！"
  echo "📁 生成 $COUNT 张PNG图片"
  echo "📂 保存路径: $FIG_DIR/"
else
  echo ""
  echo "❌ 可视化生成失败"
  exit 1
fi
