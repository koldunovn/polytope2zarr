#!/bin/bash
#SBATCH --job-name=nemo
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
python download_to_zarr.py --stream clte --year-range 1990 2014 --param 263124 --model ifs-nemo

echo "Job finished at $(date)"
