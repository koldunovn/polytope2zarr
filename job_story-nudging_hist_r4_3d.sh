#!/bin/bash
#SBATCH --job-name=story_hist_r4_3d
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=128
#SBATCH --exclusive
#SBATCH --time=08:00:00
#SBATCH --mail-type=FAIL
#SBATCH --account=ab0995
#SBATCH --output=story_hist_r4_3d_%j.out
#SBATCH -e story_hist_r4_3d_%j.err

ulimit -s 204800
ulimit -c 0

echo "Model: ifs-fesom, Activity: story-nudging, Experiment: hist, Realization: 4 (3D data)"
echo "Job started at $(date)"

MODEL="ifs-fesom"
STREAM="clmn"
ACTIVITY="story-nudging"
histERIMENT="hist"
REALIZATION="4"
YEAR_START=2017
YEAR_END=2024
RESOLUTION="standard"
OUTPUT_DIR="/work/ab0995/a270088/DestinE/GENERATION2/3D"
SERVER_ADDRESS="polytope.mn5.apps.dte.destination-earth.eu"

O3D_NLEVELS=69
PL_LEVELIST="1/5/10/20/30/50/70/100/150/200/250/300/400/500/600/700/850/925/1000"

O3D_VARS=(
    "263500:avg_so" "263501:avg_thetao" "263505:avg_von" "263506:avg_uoe" "263507:avg_wo"
)

echo "=== Processing O3D variables (${#O3D_VARS[@]} total) ==="
for var in "${O3D_VARS[@]}"; do
    param="${var%%:*}"; name="${var##*:}"
    echo "Downloading $name (param $param) with $O3D_NLEVELS levels..."
    for year in $(seq $YEAR_START $YEAR_END); do
        echo "  Year: $year"
        python download_to_zarr.py --stream $STREAM --year-range $year $year \
            --param $param --levtype o3d --resolution $RESOLUTION \
            --nlevels $O3D_NLEVELS --chunk-years 1 \
            --model $MODEL --output-dir $OUTPUT_DIR \
            --activity $ACTIVITY --experiment $histERIMENT \
            --realization $REALIZATION --address $SERVER_ADDRESS
    done
done

PL_VARS=(
    "235100:avg_pv" "235129:avg_z" "235130:avg_t" "235131:avg_u" "235132:avg_v"
    "235133:avg_q" "235135:avg_w" "235157:avg_r" "235246:avg_clwc"
)

echo "=== Processing PL variables (${#PL_VARS[@]} total) ==="
for var in "${PL_VARS[@]}"; do
    param="${var%%:*}"; name="${var##*:}"
    echo "Downloading $name (param $param) on pressure levels..."
    for year in $(seq $YEAR_START $YEAR_END); do
        echo "  Year: $year"
        python download_to_zarr.py --stream $STREAM --year-range $year $year \
            --param $param --levtype pl --resolution $RESOLUTION \
            --levelist "$PL_LEVELIST" --chunk-years 1 \
            --model $MODEL --output-dir $OUTPUT_DIR \
            --activity $ACTIVITY --experiment $histERIMENT \
            --realization $REALIZATION --address $SERVER_ADDRESS
    done
done

echo "Job finished at $(date)"
