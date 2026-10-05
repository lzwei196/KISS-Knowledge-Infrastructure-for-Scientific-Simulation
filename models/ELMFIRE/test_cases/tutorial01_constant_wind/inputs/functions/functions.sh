function replace_line {
   MATCH_PATTERN=$1
   NEW_VALUE="$2"
   IS_STRING=$3

   LINE=`grep -n "$MATCH_PATTERN" ./inputs/elmfire.data | cut -d: -f1`
   sed -i "$LINE d" ./inputs/elmfire.data
   if [ "$IS_STRING" = "yes" ]; then
      sed -i "$LINE i $MATCH_PATTERN = '$NEW_VALUE'" ./inputs/elmfire.data
   else
      sed -i "$LINE i $MATCH_PATTERN = $NEW_VALUE" ./inputs/elmfire.data
   fi
}

function create_transient_inputs {
   local WX_INPUTS_FILE=$1

   COLS=`head -n 1 $WX_INPUTS_FILE | tr ',' ' '`
   tail -n +2 $WX_INPUTS_FILE > $SCRATCH/wx.csv
   NUM_TIMES=`cat $SCRATCH/wx.csv | wc -l`

   ICOL=0
   for QUANTITY in $COLS; do
      let "ICOL = ICOL + 1"
      TIMESTEP=0
      FNLIST=''
      while read LINE; do
         VAL=`echo $LINE | cut -d, -f$ICOL`
         FNOUT=$SCRATCH/${QUANTITY}_$TIMESTEP.tif
         FNLIST="$FNLIST $FNOUT"
         gdal_calc.py -A $SCRATCH/float.tif --NoDataValue=-9999 --type=Float32 --outfile="$FNOUT" --calc="A + $VAL"
         let "TIMESTEP=TIMESTEP+1"
      done < $SCRATCH/wx.csv
      gdal_merge.py -separate -n -9999 -init -9999 -a_nodata -9999 -co "COMPRESS=DEFLATE" -co "ZLEVEL=9" -o $INPUTS/$QUANTITY.tif $FNLIST
   done

}
