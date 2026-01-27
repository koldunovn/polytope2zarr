"""
Download monthly climate data from DESP polytope API and save to zarr.

Retrieves data via earthkit.data, converts per-record to xarray,
concatenates along time, and writes to a chunked zarr store.

Prerequisites:
  - Authentication token at ~/.polytopeapirc (run desp-authentication.py)
  - zarr installed: pip install zarr

Usage examples:
  python download_to_zarr.py --year-range 2005 2010
  python download_to_zarr.py --year-range 2006 2006 --model ifs-nemo --param 263001
  python download_to_zarr.py --year-range 2005 2010 --activity projection --experiment ssp3-7.0
"""

import argparse
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
SERVER_ADDRESS = "polytope.lumi.apps.dte.destination-earth.eu"
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
        help="Level type (default: o2d)",
    )
    parser.add_argument(
        "--param", default="263101",
        help="Parameter ID (default: 263101)",
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


def convert_to_dataset(data) -> xr.Dataset:
    """Convert earthkit data records to a single xarray Dataset.

    Collection-level to_xarray() does not work reliably for monthly (clmn)
    data, so we convert each record individually and concatenate.
    Per-record datasets have no time dimension — only a ``date`` attribute
    (e.g. ``20060101``), so we parse it and assign a proper time coordinate.
    """
    datasets = []
    times = []
    for i in range(len(data)):
        ds = data[i].to_xarray()

        # Extract date from attributes (format: YYYYMMDD as int or str)
        date_val = ds.attrs.get("date")
        if date_val is not None:
            times.append(pd.Timestamp(str(date_val)))
        else:
            times.append(pd.Timestamp(f"1970-01-01"))
            logger.warning("Record %d has no date attribute, using epoch", i)

        # Expand a new 'time' dimension so concat works
        ds = ds.expand_dims("time")
        datasets.append(ds)

    combined = xr.concat(datasets, dim="time")
    combined["time"] = ("time", pd.DatetimeIndex(times))

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

    ds = ds.chunk({"time": 1})

    # LZ4 compression for all data variables
    compressor = numcodecs.LZ4()
    encoding = {var: {"compressor": compressor} for var in ds.data_vars}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(str(output_path), mode="w", encoding=encoding)
    logger.info("Saved zarr store to %s", output_path)


def main():
    args = parse_args()

    start_year, end_year = args.year_range
    if start_year > end_year:
        raise ValueError(f"Start year ({start_year}) must be <= end year ({end_year})")

    request_config = {
        "class": "d1",
        "dataset": "climate-dt",
        "activity": args.activity,
        "experiment": args.experiment,
        "generation": "2",
        "model": args.model,
        "realization": "1",
        "expver": "0001",
        "stream": "clmn",
        "type": "fc",
        "resolution": args.resolution,
        "levtype": args.levtype,
        "param": args.param,
    }

    for year in range(start_year, end_year + 1):
        year_str = str(year)
        logger.info("===== Processing year %s =====", year_str)

        # Build request
        request = {**request_config, "year": year_str, "month": MONTHS}
        logger.info("Request: %s", request)

        # Download
        data = download_data(request, SERVER_ADDRESS)
        print("\n--- Record listing ---")
        print(data.ls())
        print()

        # Convert to xarray
        ds = convert_to_dataset(data)

        # Add metadata attributes
        for key in ("model", "activity", "experiment", "generation", "realization"):
            ds.attrs[key] = request_config[key]
        ds.attrs["year"] = year_str

        # Build output filename
        zarr_name = (
            f"{request_config['model']}_{request_config['activity']}_{request_config['experiment']}"
            f"_{request_config['levtype']}_{request_config['param']}_y{year_str}.zarr"
        )
        output_path = args.output_dir / zarr_name

        # Save
        save_to_zarr(ds, output_path)

        # Verify by reopening
        print("\n--- Verification: reopened dataset ---")
        reopened = xr.open_zarr(str(output_path))
        print(reopened)
        print()


if __name__ == "__main__":
    main()
