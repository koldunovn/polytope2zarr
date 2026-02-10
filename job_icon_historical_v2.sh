#!/bin/bash
#SBATCH --job-name=icon_hist_v2
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=128
#SBATCH --exclusive
#SBATCH --time=08:00:00
#SBATCH --mail-type=FAIL
#SBATCH --account=ab0995
#SBATCH --output=icon_hist_v2_%j.out
#SBATCH -e icon_hist_v2_%j.err

# limit stacksize and core file size
ulimit -s 204800
ulimit -c 0

echo "Model: icon, Experiment: historical (v2 - remaining monthly variables)"
echo "Job started at $(date)"

# Common parameters
MODEL="icon"
STREAM="clmn"
YEAR_START=1990
YEAR_END=2014

# ============================================================================
# Surface variables (sfc) - remaining monthly variables not in original script
# Comment out lines to skip specific variables
# ============================================================================
SFC_VARS=(
    "235021:avg_ssurfror"     # Time-mean sub-surface runoff rate
    "235031:avg_tsrwe"        # Time-mean total snowfall rate water equivalent
    "235033:avg_ishf"         # Time-mean surface sensible heat flux
    "235034:avg_slhtf"        # Time-mean surface latent heat flux
    "235035:avg_sdswrf"       # Time-mean surface downward short-wave radiation flux
    "235036:avg_sdlwrf"       # Time-mean surface downward long-wave radiation flux
    "235037:avg_snswrf"       # Time-mean surface net short-wave radiation flux
    "235038:avg_snlwrf"       # Time-mean surface net long-wave radiation flux
    "235041:avg_iews"         # Time-mean eastward turbulent surface stress
    "235042:avg_inss"         # Time-mean northward turbulent surface stress
    "235043:avg_ie"           # Time-mean moisture flux
    "235049:avg_tnswrfcs"     # Time-mean top net short-wave radiation flux, clear sky
    "235050:avg_tnlwrfcs"     # Time-mean top net long-wave radiation flux, clear sky
    "235051:avg_snswrfcs"     # Time-mean surface net short-wave radiation flux, clear sky
    "235052:avg_snlwrfcs"     # Time-mean surface net long-wave radiation flux, clear sky
    "235053:avg_tdswrf"       # Time mean top downward short-wave radiation flux
    "228004:avg_2t"           # Time-mean 2 metre temperature
    "228005:avg_10ws"         # Time-mean 10 metre wind speed
    "235079:avg_skt"          # Time-mean skin temperature
    "235087:avg_tclw"         # Time-mean total column liquid water
    "235088:avg_tciw"         # Time-mean total column cloud ice water
    "235134:avg_sp"           # Time-mean surface pressure
    "235137:avg_tcwv"         # Time-mean total column vertically-integrated water vapour
    "235288:avg_tcc"          # Time-mean total cloud cover
)

echo "=== Processing SFC variables ==="
for var in "${SFC_VARS[@]}"; do
    param="${var%%:*}"
    name="${var##*:}"
    echo "Downloading $name (param $param)..."
    python download_to_zarr.py --stream $STREAM --year-range $YEAR_START $YEAR_END \
        --param $param --levtype sfc --model $MODEL
done

# ============================================================================
# Ocean 2D variables (o2d) - remaining monthly variables not in original script
# ============================================================================
O2D_VARS=(
    "263008:avg_sivol"        # Time-mean sea ice volume per unit area
)

echo "=== Processing O2D variables ==="
for var in "${O2D_VARS[@]}"; do
    param="${var%%:*}"
    name="${var##*:}"
    echo "Downloading $name (param $param)..."
    python download_to_zarr.py --stream $STREAM --year-range $YEAR_START $YEAR_END \
        --param $param --levtype o2d --model $MODEL
done

echo "Job finished at $(date)"
