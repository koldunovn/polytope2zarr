#!/bin/bash
#SBATCH --job-name=story_hist_r4_all
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=128
#SBATCH --exclusive
#SBATCH --time=08:00:00
#SBATCH --mail-type=FAIL
#SBATCH --account=ab0995
#SBATCH --output=story_hist_r4_all_%j.out
#SBATCH -e story_hist_r4_all_%j.err

ulimit -s 204800
ulimit -c 0

echo "Model: ifs-fesom, Activity: story-nudging, Experiment: hist, Realization: 4"
echo "Job started at $(date)"

MODEL="ifs-fesom"
STREAM="clmn"
ACTIVITY="story-nudging"
histERIMENT="hist"
REALIZATION="4"
YEAR_START=2017
YEAR_END=2024
SERVER_ADDRESS="polytope.mn5.apps.dte.destination-earth.eu"

SFC_VARS=(
    "235020:avg_surfror" "235021:avg_ssurfror" "235031:avg_tsrwe" "235055:avg_tprate"
    "235033:avg_ishf" "235034:avg_slhtf" "235035:avg_sdswrf" "235036:avg_sdlwrf"
    "235037:avg_snswrf" "235038:avg_snlwrf" "235051:avg_snswrfcs" "235052:avg_snlwrfcs"
    "235039:avg_tnswrf" "235040:avg_tnlwrf" "235049:avg_tnswrfcs" "235050:avg_tnlwrfcs"
    "235053:avg_tdswrf" "235041:avg_iews" "235042:avg_inss" "235043:avg_ie"
    "235137:avg_tcwv" "235136:avg_tcw" "235087:avg_tclw" "235088:avg_tciw"
    "228004:avg_2t" "235168:avg_2d" "235079:avg_skt" "235165:avg_10u" "235166:avg_10v"
    "228005:avg_10ws" "235151:avg_msl" "235134:avg_sp" "235288:avg_tcc"
)

echo "=== Processing SFC variables (${#SFC_VARS[@]} total) ==="
for var in "${SFC_VARS[@]}"; do
    param="${var%%:*}"; name="${var##*:}"
    echo "Downloading $name (param $param)..."
    python download_to_zarr.py --stream $STREAM --year-range $YEAR_START $YEAR_END \
        --param $param --levtype sfc --model $MODEL \
        --activity $ACTIVITY --experiment $histERIMENT \
        --realization $REALIZATION --address $SERVER_ADDRESS
done

O2D_VARS=(
    "263000:avg_sithick" "263001:avg_siconc" "263003:avg_siue" "263004:avg_sivn"
    "263008:avg_sivol" "263009:avg_snvol" "263100:avg_sos" "263101:avg_tos"
    "263124:avg_zos" "263121:avg_hc300m" "263122:avg_hc700m" "263123:avg_hcbtm"
)

echo "=== Processing O2D variables (${#O2D_VARS[@]} total) ==="
for var in "${O2D_VARS[@]}"; do
    param="${var%%:*}"; name="${var##*:}"
    echo "Downloading $name (param $param)..."
    python download_to_zarr.py --stream $STREAM --year-range $YEAR_START $YEAR_END \
        --param $param --levtype o2d --model $MODEL \
        --activity $ACTIVITY --experiment $histERIMENT \
        --realization $REALIZATION --address $SERVER_ADDRESS
done

echo "Job finished at $(date)"
