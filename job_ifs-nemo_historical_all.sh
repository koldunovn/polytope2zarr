#!/bin/bash
#SBATCH --job-name=ifsn_hist_all
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=128
#SBATCH --exclusive
#SBATCH --time=08:00:00
#SBATCH --mail-type=FAIL
#SBATCH --account=ab0995
#SBATCH --output=ifsn_hist_all_%j.out
#SBATCH -e ifsn_hist_all_%j.err

# limit stacksize and core file size
ulimit -s 204800
ulimit -c 0

echo "Model: ifs-nemo, Experiment: historical (ALL monthly sfc and o2d variables)"
echo "Job started at $(date)"

# Common parameters
MODEL="ifs-nemo"
STREAM="clmn"
YEAR_START=1990
YEAR_END=2014

# ============================================================================
# ALL Surface variables (sfc) with monthly frequency
# Comment out lines to skip specific variables
# ============================================================================
SFC_VARS=(
    # --- Runoff variables ---
    "235020:avg_surfror"      # Time-mean surface runoff rate
    "235021:avg_ssurfror"     # Time-mean sub-surface runoff rate

    # --- Precipitation/snowfall ---
    "235031:avg_tsrwe"        # Time-mean total snowfall rate water equivalent
    "235055:avg_tprate"       # Time-mean total precipitation rate

    # --- Heat fluxes ---
    "235033:avg_ishf"         # Time-mean surface sensible heat flux
    "235034:avg_slhtf"        # Time-mean surface latent heat flux

    # --- Radiation fluxes (surface) ---
    "235035:avg_sdswrf"       # Time-mean surface downward short-wave radiation flux
    "235036:avg_sdlwrf"       # Time-mean surface downward long-wave radiation flux
    "235037:avg_snswrf"       # Time-mean surface net short-wave radiation flux
    "235038:avg_snlwrf"       # Time-mean surface net long-wave radiation flux
    "235051:avg_snswrfcs"     # Time-mean surface net short-wave radiation flux, clear sky
    "235052:avg_snlwrfcs"     # Time-mean surface net long-wave radiation flux, clear sky

    # --- Radiation fluxes (top of atmosphere) ---
    "235039:avg_tnswrf"       # Time-mean top net short-wave radiation flux
    "235040:avg_tnlwrf"       # Time-mean top net long-wave radiation flux
    "235049:avg_tnswrfcs"     # Time-mean top net short-wave radiation flux, clear sky
    "235050:avg_tnlwrfcs"     # Time-mean top net long-wave radiation flux, clear sky
    "235053:avg_tdswrf"       # Time mean top downward short-wave radiation flux

    # --- Surface stress ---
    "235041:avg_iews"         # Time-mean eastward turbulent surface stress
    "235042:avg_inss"         # Time-mean northward turbulent surface stress

    # --- Moisture ---
    "235043:avg_ie"           # Time-mean moisture flux
    "235137:avg_tcwv"         # Time-mean total column vertically-integrated water vapour
    "235136:avg_tcw"          # Time-mean total column water
    "235087:avg_tclw"         # Time-mean total column liquid water
    "235088:avg_tciw"         # Time-mean total column cloud ice water

    # --- Temperature ---
    "228004:avg_2t"           # Time-mean 2 metre temperature
    "235168:avg_2d"           # Time-mean 2 metre dewpoint temperature
    "235079:avg_skt"          # Time-mean skin temperature

    # --- Wind ---
    "235165:avg_10u"          # Time-mean 10 metre U wind component
    "235166:avg_10v"          # Time-mean 10 metre V wind component
    "228005:avg_10ws"         # Time-mean 10 metre wind speed

    # --- Pressure ---
    "235151:avg_msl"          # Time-mean mean sea level pressure
    "235134:avg_sp"           # Time-mean surface pressure

    # --- Cloud cover ---
    "235288:avg_tcc"          # Time-mean total cloud cover
)

echo "=== Processing SFC variables (${#SFC_VARS[@]} total) ==="
for var in "${SFC_VARS[@]}"; do
    param="${var%%:*}"
    name="${var##*:}"
    echo "Downloading $name (param $param)..."
    python download_to_zarr.py --stream $STREAM --year-range $YEAR_START $YEAR_END \
        --param $param --levtype sfc --model $MODEL
done

# ============================================================================
# ALL Ocean 2D variables (o2d) with monthly frequency
# Comment out lines to skip specific variables
# ============================================================================
O2D_VARS=(
    # --- Sea ice ---
    "263000:avg_sithick"      # Time-mean sea ice thickness
    "263001:avg_siconc"       # Time-mean sea ice area fraction
    "263003:avg_siue"         # Time-mean eastward sea ice velocity
    "263004:avg_sivn"         # Time-mean northward sea ice velocity
    "263008:avg_sivol"        # Time-mean sea ice volume per unit area
    "263009:avg_snvol"        # Time-mean snow volume over sea ice per unit area

    # --- Sea surface ---
    "263100:avg_sos"          # Time-mean sea surface practical salinity
    "263101:avg_tos"          # Time-mean sea surface temperature
    "263124:avg_zos"          # Time-mean sea surface height

    # --- Heat content ---
    "263121:avg_hc300m"       # Time-mean vertically-integrated heat content in the upper 300 m
    "263122:avg_hc700m"       # Time-mean vertically-integrated heat content in the upper 700 m
    "263123:avg_hcbtm"        # Time-mean total column heat content
)

echo "=== Processing O2D variables (${#O2D_VARS[@]} total) ==="
for var in "${O2D_VARS[@]}"; do
    param="${var%%:*}"
    name="${var##*:}"
    echo "Downloading $name (param $param)..."
    python download_to_zarr.py --stream $STREAM --year-range $YEAR_START $YEAR_END \
        --param $param --levtype o2d --model $MODEL
done

echo "Job finished at $(date)"
