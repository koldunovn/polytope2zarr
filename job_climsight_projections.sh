#!/bin/bash
#SBATCH --job-name=CS_proj
#SBATCH --partition=compute
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=128
#SBATCH --exclusive
#SBATCH --time=08:00:00
#SBATCH --mail-type=FAIL
#SBATCH --account=ab0995
#SBATCH --output=timmean_%j.out
#SBATCH -e timmean_%j.err


# limit stacksize and core file size
ulimit -s 204800
ulimit -c 0

echo "Processing years ${START_YEAR} to ${END_YEAR}"
echo "Job started at $(date)"

# Run the python script
python download_to_zarr.py --stream clmn --year-range 2015 2049 --param 235165 --levtype sfc --activity projections --experiment "ssp3-7.0" --model ifs-fesom
python download_to_zarr.py --stream clmn --year-range 2015 2049 --param 235165 --levtype sfc --activity projections --experiment "ssp3-7.0" --model icon
python download_to_zarr.py --stream clmn --year-range 2015 2049 --param 235165 --levtype sfc --activity projections --experiment "ssp3-7.0" --model ifs-nemo


python download_to_zarr.py --stream clmn --year-range 2015 2049 --param 235166 --levtype sfc --activity projections --experiment "ssp3-7.0" --model ifs-fesom
python download_to_zarr.py --stream clmn --year-range 2015 2049 --param 235166 --levtype sfc --activity projections --experiment "ssp3-7.0" --model icon
python download_to_zarr.py --stream clmn --year-range 2015 2049 --param 235166 --levtype sfc --activity projections --experiment "ssp3-7.0" --model ifs-nemo


python download_to_zarr.py --stream clmn --year-range 2015 2049 --param 228004 --levtype sfc --activity projections --experiment "ssp3-7.0" --model ifs-fesom
python download_to_zarr.py --stream clmn --year-range 2015 2049 --param 228004 --levtype sfc --activity projections --experiment "ssp3-7.0" --model icon
python download_to_zarr.py --stream clmn --year-range 2015 2049 --param 228004 --levtype sfc --activity projections --experiment "ssp3-7.0" --model ifs-nemo


python download_to_zarr.py --stream clmn --year-range 2015 2049 --param 235055 --levtype sfc --activity projections --experiment "ssp3-7.0" --model ifs-fesom
python download_to_zarr.py --stream clmn --year-range 2015 2049 --param 235055 --levtype sfc --activity projections --experiment "ssp3-7.0" --model icon
python download_to_zarr.py --stream clmn --year-range 2015 2049 --param 235055 --levtype sfc --activity projections --experiment "ssp3-7.0" --model ifs-nemo
 
echo "Job finished at $(date)"
