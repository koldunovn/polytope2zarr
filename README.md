Download climate data from DESP polytope API and save to zarr.

Retrieves data via earthkit.data, converts per-record to xarray,
concatenates along time, and writes to a chunked zarr store.

Supports two stream modes:
  - clmn (default): Monthly climatology data. Requested by year/month,
    processed one year at a time.
  - clte: Daily climate data. Requested by date range, processed one
    month at a time (polytope cannot handle yearly requests for clte).

Prerequisites:
  - Authentication token at ~/.polytopeapirc (run desp-authentication.py)
  - zarr installed: pip install zarr

Usage examples:
```python
  # clmn stream — 2D surface data (o2d)
  python download_to_zarr.py --year-range 2005 2010
  python download_to_zarr.py --year-range 2006 2006 --model ifs-nemo --param 263001
  python download_to_zarr.py --year-range 2005 2010 --activity projection --experiment ssp3-7.0

  # clmn stream — 3D ocean data (o3d)
  python download_to_zarr.py --year-range 2006 2006 --levtype o3d --resolution standard --nlevels 70 --param 263501

  # clte stream — daily data, processed month by month
  python download_to_zarr.py --stream clte --year-range 1990 1990 --param 263124
  python download_to_zarr.py --stream clte --year-range 1990 1991 --param 263124 --time 0000
```
