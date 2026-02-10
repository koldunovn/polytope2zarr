#!/bin/bash
#SBATCH --job-name=icon_ssp_3d
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=128
#SBATCH --exclusive
#SBATCH --time=08:00:00
#SBATCH --mail-type=FAIL
#SBATCH --account=ab0995
#SBATCH --output=icon_ssp_3d_%j.out
#SBATCH -e icon_ssp_3d_%j.err

# limit stacksize and core file size
ulimit -s 204800
ulimit -c 0

echo "Model: icon, Experiment: ssp3-7.0 (3D data: o3d + pl)"
echo "Job started at $(date)"

# Common parameters
MODEL="icon"
STREAM="clmn"
YEAR_START=2015
YEAR_END=2049
ACTIVITY="projections"
EXPERIMENT="ssp3-7.0"
RESOLUTION="standard"
OUTPUT_DIR="/work/ab0995/a270088/DestinE/GENERATION2/3D"

# Model-specific vertical levels
O3D_NLEVELS=72  # icon has 72 ocean levels
PL_LEVELIST="1/5/10/20/30/50/70/100/150/200/250/300/400/500/600/700/850/925/1000"

# ============================================================================
# Ocean 3D variables (o3d) - monthly
# Comment out lines to skip specific variables
# ============================================================================
O3D_VARS=(
    "263500:avg_so"       # Time-mean sea water practical salinity
    "263501:avg_thetao"   # Time-mean sea water potential temperature
    "263505:avg_von"      # Time-mean northward sea water velocity
    "263506:avg_uoe"      # Time-mean eastward sea water velocity
    "263507:avg_wo"       # Time-mean upward sea water velocity
)

echo "=== Processing O3D variables (${#O3D_VARS[@]} total) ==="
for var in "${O3D_VARS[@]}"; do
    param="${var%%:*}"
    name="${var##*:}"
    echo "Downloading $name (param $param) with $O3D_NLEVELS levels..."
    for year in $(seq $YEAR_START $YEAR_END); do
        echo "  Year: $year"
        python download_to_zarr.py --stream $STREAM --year-range $year $year \
            --param $param --levtype o3d --resolution $RESOLUTION \
            --nlevels $O3D_NLEVELS --chunk-years 1 \
            --activity $ACTIVITY --experiment "$EXPERIMENT" \
            --model $MODEL --output-dir $OUTPUT_DIR
    done
done

# ============================================================================
# Pressure level variables (pl) - monthly
# Comment out lines to skip specific variables
# ============================================================================
PL_VARS=(
    "235100:avg_pv"       # Time-mean potential vorticity
    "235129:avg_z"        # Time-mean geopotential
    "235130:avg_t"        # Time-mean temperature
    "235131:avg_u"        # Time-mean U component of wind
    "235132:avg_v"        # Time-mean V component of wind
    "235133:avg_q"        # Time-mean specific humidity
    "235135:avg_w"        # Time-mean vertical velocity
    "235157:avg_r"        # Time-mean relative humidity
    "235246:avg_clwc"     # Time-mean specific cloud liquid water content
)

echo "=== Processing PL variables (${#PL_VARS[@]} total) ==="
for var in "${PL_VARS[@]}"; do
    param="${var%%:*}"
    name="${var##*:}"
    echo "Downloading $name (param $param) on pressure levels..."
    for year in $(seq $YEAR_START $YEAR_END); do
        echo "  Year: $year"
        python download_to_zarr.py --stream $STREAM --year-range $year $year \
            --param $param --levtype pl --resolution $RESOLUTION \
            --levelist "$PL_LEVELIST" --chunk-years 1 \
            --activity $ACTIVITY --experiment "$EXPERIMENT" \
            --model $MODEL --output-dir $OUTPUT_DIR
    done
done

echo "Job finished at $(date)"
