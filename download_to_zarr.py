"""
Download climate data from DESP polytope API and save to zarr.

Retrieves data via earthkit.data, converts per-record to xarray,
concatenates along time, and writes to a chunked zarr store.

Supports two stream modes:
  - clmn (default): Monthly climatology data. Requested by year/month.
  - clte: Daily climate data. Requested by date range.

Chunking strategy:
  - Monthly surface data (clmn + sfc): 5-year chunks
  - Daily surface data (clte, o2d): 6-month chunks
  - Other combinations: 1-year chunks (configurable via --chunk-years/--chunk-months)

Output naming convention:
  {activity}_{experiment}_{generation}_{model}_{realization}_{expver}_{stream}_{resolution}_{levtype}_{param}_{start_date}_{end_date}.zarr

Prerequisites:
  - Authentication token at ~/.polytopeapirc (run desp-authentication.py)
  - zarr installed: pip install zarr

Usage examples:
  # clmn stream — monthly surface data (5-year chunks)
  python download_to_zarr.py --year-range 2006 2010 --levtype sfc --param 235165
  python download_to_zarr.py --year-range 2006 2015 --activity projections --experiment ssp3-7.0

  # clmn stream — monthly ocean 2D data (1-year chunks by default)
  python download_to_zarr.py --year-range 2006 2010 --levtype o2d --param 263101

  # clmn stream — 3D ocean data (o3d) with sequential levels
  python download_to_zarr.py --year-range 2006 2006 --levtype o3d --resolution standard --nlevels 69 --param 263501

  # clmn stream — 3D pressure level data (pl) with custom levels
  python download_to_zarr.py --year-range 2006 2006 --levtype pl --resolution standard --levelist "1/5/10/20/30/50/70/100/150/200/250/300/400/500/600/700/850/925/1000" --param 235130

  # clte stream — daily data (6-month chunks)
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
DEFAULT_OUTPUT_DIR = Path("/work/ab0995/a270088/DestinE/GENERATION2/")

SERVER_ADDRESSES = {
    "ifs-fesom": "polytope.lumi.apps.dte.destination-earth.eu",
    "icon":      "polytope.lumi.apps.dte.destination-earth.eu",
    "ifs-nemo":  "polytope.mn5.apps.dte.destination-earth.eu",
}
MONTHS = "1/2/3/4/5/6/7/8/9/10/11/12"

MAX_RETRIES = 3
RETRY_DELAY = 30  # seconds

# Chunking defaults
MONTHLY_SFC_CHUNK_YEARS = 5    # 5-year chunks for monthly surface data
DAILY_CHUNK_MONTHS = 6         # 6-month chunks for daily data
DEFAULT_CHUNK_YEARS = 1        # Default: 1-year chunks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download climate data from DESP polytope API and save to zarr."
    )
    parser.add_argument(
        "--year-range", nargs=2, type=int, required=True,
        metavar=("START", "END"),
        help="Start and end year (inclusive), e.g. --year-range 2005 2010",
    )
    parser.add_argument(
        "--stream", default="clmn", choices=("clmn", "clte"),
        help="Data stream (default: clmn). "
             "clmn = monthly climatology. "
             "clte = daily climate data.",
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
        "--generation", default="2",
        help="Generation (default: 2)",
    )
    parser.add_argument(
        "--model", default="ifs-fesom",
        help="Model (default: ifs-fesom)",
    )
    parser.add_argument(
        "--realization", default="1",
        help="Realization (default: 1)",
    )
    parser.add_argument(
        "--expver", default="0001",
        help="Experiment version (default: 0001)",
    )
    parser.add_argument(
        "--resolution", default="high",
        help="Resolution (default: high)",
    )
    parser.add_argument(
        "--levtype", default="sfc",
        help="Level type (default: sfc). Use o2d for ocean 2D, o3d for 3D ocean data.",
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
        "--levelist", type=str, default=None,
        help="Custom level list for 3D data, e.g. '1/5/10/20/30/50/70/100/150/200/250/300/400/500/600/700/850/925/1000'. "
             "Takes precedence over --nlevels if both are specified.",
    )
    parser.add_argument(
        "--chunk-years", type=int, default=None,
        help="Override chunk size in years for clmn stream (default: auto-detected based on levtype)",
    )
    parser.add_argument(
        "--chunk-months", type=int, default=None,
        help="Override chunk size in months for clte stream (default: 6)",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def get_chunk_size(stream: str, levtype: str, chunk_years: int | None, chunk_months: int | None) -> tuple[int, int]:
    """Determine chunk size based on stream and levtype.

    Returns (chunk_years, chunk_months) where one will be 0.
    For clmn stream: returns (years, 0)
    For clte stream: returns (0, months)
    """
    if stream == "clte":
        # Daily data: use 6-month chunks
        months = chunk_months if chunk_months is not None else DAILY_CHUNK_MONTHS
        return (0, months)

    # clmn stream
    if chunk_years is not None:
        return (chunk_years, 0)

    # Auto-detect based on levtype
    if levtype == "sfc":
        # Monthly surface data: 5-year chunks
        return (MONTHLY_SFC_CHUNK_YEARS, 0)
    else:
        # Other monthly data (o2d, o3d): 1-year chunks
        return (DEFAULT_CHUNK_YEARS, 0)


def generate_zarr_filename(config: dict, start_date: str, end_date: str) -> str:
    """Generate zarr filename following the new naming convention.

    Format: {activity}_{experiment}_{generation}_{model}_{realization}_{expver}_{stream}_{resolution}_{levtype}_{param}_{start_date}_{end_date}.zarr
    """
    return (
        f"{config['activity']}_{config['experiment']}_{config['generation']}_"
        f"{config['model']}_{config['realization']}_{config['expver']}_"
        f"{config['stream']}_{config['resolution']}_{config['levtype']}_"
        f"{config['param']}_{start_date}_{end_date}.zarr"
    )


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


def _generate_year_chunks(start_year: int, end_year: int, chunk_years: int) -> list[tuple[int, int]]:
    """Generate list of (chunk_start_year, chunk_end_year) tuples."""
    chunks = []
    current = start_year
    while current <= end_year:
        chunk_end = min(current + chunk_years - 1, end_year)
        chunks.append((current, chunk_end))
        current = chunk_end + 1
    return chunks


def _generate_month_chunks(start_year: int, end_year: int, chunk_months: int) -> list[tuple[str, str]]:
    """Generate list of (start_date, end_date) tuples for month-based chunks.

    Returns dates in YYYY-MM-DD format.
    """
    chunks = []
    current_year = start_year
    current_month = 1

    while current_year < end_year or (current_year == end_year and current_month <= 12):
        # Start of chunk
        start_date = f"{current_year}-{current_month:02d}-01"

        # Calculate end of chunk
        end_month = current_month + chunk_months - 1
        end_year_chunk = current_year + (end_month - 1) // 12
        end_month = ((end_month - 1) % 12) + 1

        # Don't go past the requested end year
        if end_year_chunk > end_year:
            end_year_chunk = end_year
            end_month = 12

        last_day = calendar.monthrange(end_year_chunk, end_month)[1]
        end_date = f"{end_year_chunk}-{end_month:02d}-{last_day:02d}"

        chunks.append((start_date, end_date))

        # Move to next chunk
        current_month = end_month + 1
        if current_month > 12:
            current_month = 1
            current_year = end_year_chunk + 1
        else:
            current_year = end_year_chunk

        # Stop if we've passed the end year
        if current_year > end_year:
            break

    return chunks


def main():
    args = parse_args()

    start_year, end_year = args.year_range
    if start_year > end_year:
        raise ValueError(f"Start year ({start_year}) must be <= end year ({end_year})")

    has_levels = args.nlevels is not None or args.levelist is not None

    server_address = SERVER_ADDRESSES.get(
        args.model, "polytope.lumi.apps.dte.destination-earth.eu"
    )
    logger.info("Using server: %s (model=%s)", server_address, args.model)

    # Determine chunk size
    chunk_years, chunk_months = get_chunk_size(
        args.stream, args.levtype, args.chunk_years, args.chunk_months
    )
    if args.stream == "clte":
        logger.info("Chunking: %d-month chunks (daily data)", chunk_months)
    else:
        logger.info("Chunking: %d-year chunks (monthly data, levtype=%s)", chunk_years, args.levtype)

    request_config = {
        "class": "d1",
        "dataset": "climate-dt",
        "activity": args.activity,
        "experiment": args.experiment,
        "generation": args.generation,
        "model": args.model,
        "realization": args.realization,
        "expver": args.expver,
        "stream": args.stream,
        "type": "fc",
        "resolution": args.resolution,
        "levtype": args.levtype,
        "param": args.param,
    }

    if has_levels:
        if args.levelist is not None:
            # Use custom level list (e.g., "1/5/10/20/30/50/70/100")
            request_config["levelist"] = args.levelist
        else:
            # Generate sequential levels 1..N
            request_config["levelist"] = "/".join(str(i) for i in range(1, args.nlevels + 1))

    if args.stream == "clte":
        # clte: daily data — process in month-based chunks
        if args.time is None:
            logger.info("No --time specified for clte stream, defaulting to 0000")
        time_val = args.time or "0000"
        request_config["time"] = time_val

        month_chunks = _generate_month_chunks(start_year, end_year, chunk_months)
        logger.info("Will process %d chunk(s)", len(month_chunks))

        for start_date, end_date in month_chunks:
            label = f"{start_date} to {end_date}"
            logger.info("===== Processing %s =====", label)

            date_range = f"{start_date}/to/{end_date}"
            request = {**request_config, "date": date_range}

            zarr_name = generate_zarr_filename(request_config, start_date, end_date)
            output_path = args.output_dir / zarr_name

            _process_chunk(request, request_config, label,
                           has_levels, output_path, server_address)

    else:
        # clmn: monthly climatology — process in year-based chunks
        year_chunks = _generate_year_chunks(start_year, end_year, chunk_years)
        logger.info("Will process %d chunk(s)", len(year_chunks))

        for chunk_start, chunk_end in year_chunks:
            label = f"{chunk_start}-{chunk_end}" if chunk_start != chunk_end else str(chunk_start)
            logger.info("===== Processing years %s =====", label)

            # Build year string for multi-year requests
            years_list = "/".join(str(y) for y in range(chunk_start, chunk_end + 1))
            request = {**request_config, "year": years_list, "month": MONTHS}

            # Generate filename with date range
            start_date = f"{chunk_start}-01-01"
            end_date = f"{chunk_end}-12-31"
            zarr_name = generate_zarr_filename(request_config, start_date, end_date)
            output_path = args.output_dir / zarr_name

            _process_chunk(request, request_config, label,
                           has_levels, output_path, server_address)


if __name__ == "__main__":
    main()
