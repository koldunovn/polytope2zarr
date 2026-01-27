"""
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
  # clmn stream — 2D surface data (o2d)
  python download_to_zarr.py --year-range 2005 2010
  python download_to_zarr.py --year-range 2006 2006 --model ifs-nemo --param 263001
  python download_to_zarr.py --year-range 2005 2010 --activity projection --experiment ssp3-7.0

  # clmn stream — 3D ocean data (o3d)
  python download_to_zarr.py --year-range 2006 2006 --levtype o3d --resolution standard --nlevels 70 --param 263501

  # clte stream — daily data, processed month by month
  python download_to_zarr.py --stream clte --year-range 1990 1990 --param 263124
  python download_to_zarr.py --stream clte --year-range 1990 1991 --param 263124 --time 0000
"""

import argparse
import calendar
import logging
import time
from pathlib import Path

import numcodecs
import numpy as np
import pandas as pd
import xarray as xr

import earthkit.data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
SERVER_ADDRESSES = {
    "ifs-fesom": "polytope.lumi.apps.dte.destination-earth.eu",
    "icon":      "polytope.lumi.apps.dte.destination-earth.eu",
    "ifs-nemo":  "polytope.mn5.apps.dte.destination-earth.eu",
}
MONTHS = "1/2/3/4/5/6/7/8/9/10/11/12"

MAX_RETRIES = 3
RETRY_DELAY = 30  # seconds


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download monthly climate data from DESP polytope API and save to zarr."
    )
    parser.add_argument(
        "--year-range", nargs=2, type=int, required=True,
        metavar=("START", "END"),
        help="Start and end year (inclusive), e.g. --year-range 2005 2010",
    )
    parser.add_argument(
        "--stream", default="clmn", choices=("clmn", "clte"),
        help="Data stream (default: clmn). "
             "clmn = monthly climatology (year-by-year). "
             "clte = daily climate data (month-by-month).",
    )
    parser.add_argument(
        "--time", default=None,
        help="Forecast time, e.g. 0000. Required for clte stream, ignored for clmn.",
    )
    parser.add_argument(
        "--activity", default="baseline",
        help="Activity (default: baseline)",
    )
    parser.add_argument(
        "--experiment", default="hist",
        help="Experiment (default: hist)",
    )
    parser.add_argument(
        "--model", default="ifs-fesom",
        help="Model (default: ifs-fesom)",
    )
    parser.add_argument(
        "--resolution", default="high",
        help="Resolution (default: high)",
    )
    parser.add_argument(
        "--levtype", default="o2d",
        help="Level type (default: o2d). Use o3d for 3D ocean data.",
    )
    parser.add_argument(
        "--param", default="263101",
        help="Parameter ID (default: 263101)",
    )
    parser.add_argument(
        "--nlevels", type=int, default=None,
        help="Number of vertical levels for 3D data (e.g. 70). "
             "Generates levelist 1..N and includes it in the request.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("/work/ab0995/a270088/DestinE/PHASE2_zarr/"),
        help="Output directory (default: /work/ab0995/a270088/DestinE/PHASE2_zarr/)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Pipeline functions
# ---------------------------------------------------------------------------

def download_data(request: dict, address: str):
    """Retrieve data from the polytope API with retry logic."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("Download attempt %d/%d", attempt, MAX_RETRIES)
            data = earthkit.data.from_source(
                "polytope",
                "destination-earth",
                request,
                address=address,
                stream=False,
            )
            logger.info("Retrieved %d record(s)", len(data))
            return data
        except Exception as exc:
            logger.warning("Attempt %d failed: %s", attempt, exc)
            if attempt < MAX_RETRIES:
                logger.info("Retrying in %d seconds...", RETRY_DELAY)
                time.sleep(RETRY_DELAY)
            else:
                raise


def convert_to_dataset(data, has_levels: bool = False) -> xr.Dataset:
    """Convert earthkit data records to a single xarray Dataset.

    Collection-level to_xarray() does not work reliably for monthly (clmn)
    data, so we convert each record individually and concatenate.
    Per-record datasets have no time dimension — only a ``date`` attribute
    (e.g. ``20060101``), so we parse it and assign a proper time coordinate.

    For 3D data (has_levels=True), each record also carries a level value
    which is extracted and used to build the ``level`` dimension.
    """
    datasets = []

    for i in range(len(data)):
        ds = data[i].to_xarray()

        # Extract date from attributes (format: YYYYMMDD as int or str)
        date_val = ds.attrs.get("date")
        if date_val is not None:
            time_val = pd.Timestamp(str(date_val))
        else:
            time_val = pd.Timestamp("1970-01-01")
            logger.warning("Record %d has no date attribute, using epoch", i)

        if has_levels:
            # Extract level from earthkit record metadata or xarray attrs
            try:
                level_val = int(data[i].metadata("level"))
            except Exception:
                level_val = ds.attrs.get("level", ds.attrs.get("levelist"))
                if level_val is not None:
                    level_val = int(level_val)
                else:
                    level_val = 0
                    logger.warning("Record %d: could not determine level", i)

            ds = ds.expand_dims({"time": [time_val], "level": [level_val]})
        else:
            ds = ds.expand_dims({"time": [time_val]})

        datasets.append(ds)

    if has_levels:
        combined = xr.combine_by_coords(datasets, combine_attrs="drop_conflicts")
    else:
        combined = xr.concat(datasets, dim="time")

    logger.info("Combined dataset: %s", dict(combined.sizes))
    return combined


def _clean_attrs(attrs: dict) -> dict:
    """Remove or convert attributes that are not JSON-serializable (e.g. bytes)."""
    clean = {}
    for k, v in attrs.items():
        if isinstance(v, bytes):
            try:
                clean[k] = v.decode("utf-8")
            except UnicodeDecodeError:
                logger.warning("Dropping non-serializable attribute: %s", k)
                continue
        elif isinstance(v, dict):
            clean[k] = _clean_attrs(v)
        else:
            clean[k] = v
    return clean


def save_to_zarr(ds: xr.Dataset, output_path: Path) -> None:
    """Chunk, downcast to float32, and write the dataset to zarr."""
    # Downcast float64 data variables to float32
    for var in ds.data_vars:
        if ds[var].dtype == np.float64:
            ds[var] = ds[var].astype(np.float32)
            logger.info("Downcast %s from float64 → float32", var)

    # Clean non-serializable attributes (GRIB metadata can contain bytes)
    ds.attrs = _clean_attrs(ds.attrs)
    for var in list(ds.data_vars) + list(ds.coords):
        if var in ds:
            ds[var].attrs = _clean_attrs(ds[var].attrs)

    chunks = {"time": 1}
    if "level" in ds.dims:
        chunks["level"] = 5
    ds = ds.chunk(chunks)

    # LZ4 compression for all data variables
    compressor = numcodecs.LZ4()
    encoding = {var: {"compressor": compressor} for var in ds.data_vars}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(str(output_path), mode="w", encoding=encoding)
    logger.info("Saved zarr store to %s", output_path)


def _process_chunk(request: dict, request_config: dict, label: str,
                    has_levels: bool, output_path: Path,
                    server_address: str) -> None:
    """Download one chunk (a year or a month), convert, and save to zarr."""
    logger.info("Request: %s", request)

    data = download_data(request, server_address)
    print("\n--- Record listing ---")
    print(data.ls())
    print()

    ds = convert_to_dataset(data, has_levels=has_levels)

    for key in ("model", "activity", "experiment", "generation", "realization"):
        ds.attrs[key] = request_config[key]
    ds.attrs["stream"] = request_config["stream"]
    ds.attrs["period"] = label

    save_to_zarr(ds, output_path)

    print("\n--- Verification: reopened dataset ---")
    reopened = xr.open_zarr(str(output_path))
    print(reopened)
    print()


def main():
    args = parse_args()

    start_year, end_year = args.year_range
    if start_year > end_year:
        raise ValueError(f"Start year ({start_year}) must be <= end year ({end_year})")

    has_levels = args.nlevels is not None

    server_address = SERVER_ADDRESSES.get(
        args.model, "polytope.lumi.apps.dte.destination-earth.eu"
    )
    logger.info("Using server: %s (model=%s)", server_address, args.model)

    request_config = {
        "class": "d1",
        "dataset": "climate-dt",
        "activity": args.activity,
        "experiment": args.experiment,
        "generation": "2",
        "model": args.model,
        "realization": "1",
        "expver": "0001",
        "stream": args.stream,
        "type": "fc",
        "resolution": args.resolution,
        "levtype": args.levtype,
        "param": args.param,
    }

    if has_levels:
        request_config["levelist"] = [str(i) for i in range(1, args.nlevels + 1)]

    if args.stream == "clte":
        # clte: daily data — process month by month using date ranges
        if args.time is None:
            logger.info("No --time specified for clte stream, defaulting to 0000")
        time_val = args.time or "0000"
        request_config["time"] = time_val

        for year in range(start_year, end_year + 1):
            for month in range(1, 13):
                label = f"{year}-{month:02d}"
                logger.info("===== Processing %s =====", label)

                first_day = f"{year}-{month:02d}-01"
                last_day_num = calendar.monthrange(year, month)[1]
                last_day = f"{year}-{month:02d}-{last_day_num:02d}"
                date_range = f"{first_day}/to/{last_day}"

                request = {**request_config, "date": date_range}

                zarr_name = (
                    f"{request_config['model']}_{request_config['activity']}"
                    f"_{request_config['experiment']}_{request_config['levtype']}"
                    f"_{request_config['param']}_y{year}m{month:02d}.zarr"
                )
                output_path = args.output_dir / zarr_name

                _process_chunk(request, request_config, label,
                               has_levels, output_path, server_address)

    else:
        # clmn: monthly climatology — process year by year
        for year in range(start_year, end_year + 1):
            year_str = str(year)
            logger.info("===== Processing year %s =====", year_str)

            request = {**request_config, "year": year_str, "month": MONTHS}

            zarr_name = (
                f"{request_config['model']}_{request_config['activity']}"
                f"_{request_config['experiment']}_{request_config['levtype']}"
                f"_{request_config['param']}_y{year_str}.zarr"
            )
            output_path = args.output_dir / zarr_name

            _process_chunk(request, request_config, year_str,
                           has_levels, output_path, server_address)


if __name__ == "__main__":
    main()
