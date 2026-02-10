#!/bin/bash
#SBATCH --job-name=icon_hist
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=128
#SBATCH --exclusive
#SBATCH --time=08:00:00
#SBATCH --mail-type=FAIL
#SBATCH --account=ab0995
#SBATCH --output=icon_hist_%j.out
#SBATCH -e icon_hist_%j.err

# limit stacksize and core file size
ulimit -s 204800
ulimit -c 0

echo "Model: icon, Experiment: historical"
echo "Job started at $(date)"

# Surface variables (sfc)
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 235020 --levtype sfc --model icon  # avg_surfror
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 235040 --levtype sfc --model icon  # avg_tnlwrf
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 235039 --levtype sfc --model icon  # avg_tnswrf
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 235055 --levtype sfc --model icon  # avg_tprate
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 235151 --levtype sfc --model icon  # avg_msl
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 235136 --levtype sfc --model icon  # avg_tcw
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 235165 --levtype sfc --model icon  # avg_10u
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 235166 --levtype sfc --model icon  # avg_10v
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 235168 --levtype sfc --model icon  # avg_2d

# Ocean 2D variables (o2d)
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 263000 --levtype o2d --model icon  # avg_sithick
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 263001 --levtype o2d --model icon  # avg_siconc
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 263003 --levtype o2d --model icon  # avg_siue
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 263004 --levtype o2d --model icon  # avg_sivn
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 263009 --levtype o2d --model icon  # avg_snvol
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 263100 --levtype o2d --model icon  # avg_sos
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 263101 --levtype o2d --model icon  # avg_tos
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 263121 --levtype o2d --model icon  # avg_hc300m
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 263122 --levtype o2d --model icon  # avg_hc700m
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 263123 --levtype o2d --model icon  # avg_hcbtm
python download_to_zarr.py --stream clmn --year-range 1990 2014 --param 263124 --levtype o2d --model icon  # avg_zos

echo "Job finished at $(date)"
