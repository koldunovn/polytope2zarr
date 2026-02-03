"""
Consolidate multiple time-chunk zarr files into single datasets.

Scans a directory of zarr files created by download_to_zarr.py and combines
all time chunks for each variable into a single consolidated zarr store.

Expected input naming convention:
  {activity}_{experiment}_{generation}_{model}_{realization}_{expver}_{stream}_{resolution}_{levtype}_{param}_{start_date}_{end_date}.zarr

Output naming convention (consolidated):
  {activity}_{experiment}_{generation}_{model}_{realization}_{expver}_{stream}_{resolution}_{levtype}_{param}.zarr

By default, skips datasets that already exist in the output directory.
If source data has changed (different time range or time steps),
a warning is logged but the dataset is still skipped unless --force is used.

Usage examples:
  # List available datasets
  python consolidate_zarr.py --list

  # Consolidate a specific dataset
  python consolidate_zarr.py --datasets baseline_hist_2_ifs-fesom_1_0001_clmn_high_sfc_235165

  # Consolidate all available datasets
  python consolidate_zarr.py --all

  # Force reconsolidation even if output exists
  python consolidate_zarr.py --datasets my_dataset --force
"""

import argparse
import logging
import re
from collections import defaultdict
from pathlib import Path

import numcodecs
import xarray as xr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_INPUT_DIR = Path("/work/ab0995/a270088/DestinE/GENERATION2/")
DEFAULT_OUTPUT_DIR = Path("/work/ab0995/a270088/DestinE/GENERATION2_joint/")

# Target chunk size in bytes (~100 MB)
TARGET_CHUNK_BYTES = 100 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consolidate multiple time-step zarr files into single datasets."
    )
    parser.add_argument(
        "--list", "-l", action="store_true",
        help="List available datasets with year ranges",
    )
    parser.add_argument(
        "--datasets", "-d", nargs="+",
        help="Dataset name(s) to consolidate (base name without year suffix)",
    )
    parser.add_argument(
        "--all", "-a", action="store_true",
        help="Consolidate all available datasets",
    )
    parser.add_argument(
        "--input-dir", type=Path, default=DEFAULT_INPUT_DIR,
        help=f"Input directory (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--time-chunk", type=int, default=10,
        help="Chunk size for time dimension (default: 10)",
    )
    parser.add_argument(
        "--values-chunk", type=int, default=3_000_000,
        help="Chunk size for values dimension (default: 3000000)",
    )
    parser.add_argument(
        "--level-chunk", type=int, default=None,
        help="Chunk size for level dimension (3D data). If not specified, "
             "calculated automatically to target ~100MB chunks.",
    )
    parser.add_argument(
        "--target-chunk-mb", type=int, default=100,
        help="Target chunk size in MB for automatic level chunking (default: 100)",
    )
    parser.add_argument(
        "--force", "-f", action="store_true",
        help="Force reconsolidation even if output already exists",
    )
    return parser.parse_args()


def extract_base_name_and_period(zarr_path: Path) -> tuple[str, str]:
    """Extract the base name (without date suffix) and period from a zarr path.

    Expected format:
      {activity}_{experiment}_{generation}_{model}_{realization}_{expver}_{stream}_{resolution}_{levtype}_{param}_{start_date}_{end_date}.zarr

    Returns:
      (base_name, period) where period is "YYYY-MM-DD_YYYY-MM-DD"
    """
    name = zarr_path.name.replace(".zarr", "")

    # Match: base_YYYY-MM-DD_YYYY-MM-DD
    match = re.match(r"(.+)_(\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2})$", name)
    if match:
        return match.group(1), match.group(2)

    # No match - return as-is (will be logged as warning)
    return name, ""


def extract_dates_from_period(period: str) -> tuple[str, str]:
    """Extract start and end dates from period string.

    Args:
        period: String in format "YYYY-MM-DD_YYYY-MM-DD"

    Returns:
        (start_date, end_date) tuple
    """
    if "_" in period:
        parts = period.split("_")
        if len(parts) == 2:
            return parts[0], parts[1]
    return "", ""


def scan_datasets(input_dir: Path) -> dict[str, list[Path]]:
    """Scan input directory and group zarr files by base name."""
    datasets = defaultdict(list)

    for zarr_path in input_dir.glob("*.zarr"):
        if zarr_path.is_dir():
            base_name, _ = extract_base_name_and_period(zarr_path)
            datasets[base_name].append(zarr_path)

    # Sort files within each dataset by period
    for base_name in datasets:
        datasets[base_name] = sorted(
            datasets[base_name],
            key=lambda p: extract_base_name_and_period(p)[1]
        )

    return dict(datasets)


def list_datasets(input_dir: Path) -> None:
    """List all available datasets with their date ranges."""
    datasets = scan_datasets(input_dir)

    if not datasets:
        print(f"No zarr datasets found in {input_dir}")
        return

    print(f"\nAvailable datasets in {input_dir}:\n")
    print("-" * 100)

    for base_name in sorted(datasets.keys()):
        paths = datasets[base_name]
        periods = [extract_base_name_and_period(p)[1] for p in paths]

        # Extract all start and end dates
        all_starts = []
        all_ends = []
        for period in periods:
            start, end = extract_dates_from_period(period)
            if start:
                all_starts.append(start)
            if end:
                all_ends.append(end)

        n_files = len(paths)
        if all_starts and all_ends:
            first_date = min(all_starts)
            last_date = max(all_ends)
            print(f"{base_name} | {first_date} to {last_date} | files: {n_files}")
        else:
            print(f"{base_name} | (no date info) | files: {n_files}")

    print("-" * 100)
    print(f"\nTotal: {len(datasets)} dataset(s)")


def calculate_3d_chunks(
    ds: xr.Dataset,
    time_chunk: int,
    values_chunk: int,
    level_chunk: int | None = None,
    target_chunk_mb: int = 100,
) -> dict:
    """Calculate chunk sizes for 3D data targeting ~100MB chunks.

    For 3D data with dimensions (time, level, values), we need to determine
    the level chunk size to achieve roughly target_chunk_mb MB per chunk.

    Args:
        ds: The dataset to chunk
        time_chunk: Chunk size for time dimension
        values_chunk: Chunk size for values dimension
        level_chunk: If provided, use this fixed level chunk size
        target_chunk_mb: Target chunk size in MB (used if level_chunk not specified)
    """
    chunks = {"time": time_chunk, "values": values_chunk}

    if "level" not in ds.dims:
        return chunks

    n_levels = ds.dims["level"]

    # If level_chunk is explicitly provided, use it
    if level_chunk is not None:
        chunks["level"] = min(level_chunk, n_levels)
        logger.info(
            "3D chunking (user-specified level): time=%d, level=%d, values=%d",
            time_chunk, chunks["level"], values_chunk
        )
        return chunks

    # Get the data variable to estimate size
    data_vars = list(ds.data_vars)
    if not data_vars:
        chunks["level"] = 5
        return chunks

    var = ds[data_vars[0]]

    # Get dtype size in bytes (assume float32 if unknown)
    dtype_size = var.dtype.itemsize if hasattr(var.dtype, "itemsize") else 4

    # Calculate bytes per (time, level, values) element
    # A chunk of (time_chunk, level_chunk, values_chunk) should be ~target_chunk_mb MB
    # bytes = time_chunk * level_chunk * values_chunk * dtype_size
    # level_chunk = target_bytes / (time_chunk * values_chunk * dtype_size)

    target_bytes = target_chunk_mb * 1024 * 1024
    bytes_per_level = time_chunk * values_chunk * dtype_size

    if bytes_per_level > 0:
        calc_level_chunk = max(1, int(target_bytes / bytes_per_level))
        calc_level_chunk = min(calc_level_chunk, n_levels)  # Don't exceed total levels
    else:
        calc_level_chunk = 5

    chunks["level"] = calc_level_chunk
    estimated_mb = (time_chunk * calc_level_chunk * values_chunk * dtype_size) / (1024 * 1024)
    logger.info(
        "3D chunking (auto-calculated): time=%d, level=%d, values=%d "
        "(target: %dMB, estimated: %.1fMB per chunk)",
        time_chunk, calc_level_chunk, values_chunk, target_chunk_mb, estimated_mb
    )

    return chunks


def get_dataset_metadata(zarr_path: Path) -> dict | None:
    """Extract metadata from an existing zarr dataset for comparison.

    Returns dict with keys: n_time_steps, values_size, time_range, or None if cannot read.
    """
    try:
        ds = xr.open_zarr(zarr_path, consolidated=True)
    except Exception:
        try:
            ds = xr.open_zarr(zarr_path, consolidated=False)
        except Exception:
            return None

    metadata = {
        "n_time_steps": ds.sizes.get("time", 0),
        "values_size": ds.sizes.get("values", 0),
    }

    # Extract time range from time coordinate
    if "time" in ds.coords and ds.sizes.get("time", 0) > 0:
        try:
            time_vals = ds.time.values
            metadata["time_range"] = (str(time_vals.min())[:10], str(time_vals.max())[:10])
        except Exception:
            metadata["time_range"] = ("", "")
    else:
        metadata["time_range"] = ("", "")

    ds.close()
    return metadata


def get_source_metadata(paths: list[Path]) -> dict:
    """Extract expected metadata from source zarr files.

    Returns dict with keys: n_time_steps, values_size, time_range.
    """
    total_time_steps = 0
    values_size = 0
    all_times = []

    for p in paths:
        try:
            ds = xr.open_zarr(p, consolidated=True)
        except Exception:
            try:
                ds = xr.open_zarr(p, consolidated=False)
            except Exception:
                continue

        total_time_steps += ds.sizes.get("time", 0)
        if values_size == 0:
            values_size = ds.sizes.get("values", 0)

        if "time" in ds.coords and ds.sizes.get("time", 0) > 0:
            try:
                time_vals = ds.time.values
                all_times.extend([time_vals.min(), time_vals.max()])
            except Exception:
                pass

        ds.close()

    time_range = ("", "")
    if all_times:
        time_range = (str(min(all_times))[:10], str(max(all_times))[:10])

    return {
        "n_time_steps": total_time_steps,
        "values_size": values_size,
        "time_range": time_range,
    }


def check_existing_dataset(
    base_name: str,
    paths: list[Path],
    output_dir: Path,
) -> bool:
    """Check if dataset already exists and compare metadata.

    Returns True if dataset should be skipped, False if it should be processed.
    """
    output_path = output_dir / f"{base_name}.zarr"

    if not output_path.exists():
        return False

    logger.info("Found existing dataset: %s", output_path)

    existing_meta = get_dataset_metadata(output_path)
    if existing_meta is None:
        logger.warning("Cannot read existing dataset %s, will reconsolidate", output_path)
        return False

    source_meta = get_source_metadata(paths)

    differences = []

    # Check time range
    if existing_meta["time_range"] != source_meta["time_range"]:
        differences.append(
            f"Time range changed: existing={existing_meta['time_range'][0]} to {existing_meta['time_range'][1]}, "
            f"source={source_meta['time_range'][0]} to {source_meta['time_range'][1]}"
        )

    # Check values dimension size
    if existing_meta["values_size"] != source_meta["values_size"]:
        differences.append(
            f"Values size changed: existing={existing_meta['values_size']}, "
            f"source={source_meta['values_size']}"
        )

    # Check number of time steps
    if existing_meta["n_time_steps"] != source_meta["n_time_steps"]:
        differences.append(
            f"Number of time steps changed: existing={existing_meta['n_time_steps']}, "
            f"source={source_meta['n_time_steps']}"
        )

    if differences:
        logger.warning("Dataset %s exists but has changed:", base_name)
        for diff in differences:
            logger.warning("  - %s", diff)
        logger.info("Skipping %s (use --force to reconsolidate)", base_name)
        return True

    logger.info("Dataset %s already exists and is up-to-date, skipping", base_name)
    return True


def consolidate_dataset(
    base_name: str,
    paths: list[Path],
    output_dir: Path,
    time_chunk: int,
    values_chunk: int,
    level_chunk: int | None,
    target_chunk_mb: int,
    force: bool = False,
) -> None:
    """Consolidate multiple zarr files into a single dataset."""
    # Check if already exists (unless force is set)
    if not force and check_existing_dataset(base_name, paths, output_dir):
        return

    logger.info("Consolidating dataset: %s (%d files)", base_name, len(paths))

    # Open all datasets
    logger.info("Opening %d zarr files...", len(paths))
    datasets = []
    for p in paths:
        try:
            ds = xr.open_zarr(p, consolidated=True)
            datasets.append(ds)
        except Exception as e:
            logger.warning("Failed to open %s: %s", p, e)
            # Try without consolidated flag
            try:
                ds = xr.open_zarr(p, consolidated=False)
                datasets.append(ds)
            except Exception as e2:
                logger.error("Cannot open %s: %s", p, e2)

    if not datasets:
        logger.error("No datasets could be opened for %s", base_name)
        return

    # Concatenate along time
    logger.info("Concatenating %d datasets along time dimension...", len(datasets))
    ds = xr.concat(datasets, dim="time")
    logger.info("Combined dataset shape: %s", dict(ds.sizes))

    # Determine chunking
    is_3d = "level" in ds.dims
    if is_3d:
        chunks = calculate_3d_chunks(
            ds, time_chunk, values_chunk,
            level_chunk=level_chunk,
            target_chunk_mb=target_chunk_mb
        )
    else:
        chunks = {"time": time_chunk, "values": values_chunk}
        logger.info("2D chunking: time=%d, values=%d", time_chunk, values_chunk)

    logger.info("Applying chunks: %s", chunks)
    ds_out = ds.chunk(chunks)

    # Clear encoding on coordinates to avoid conflicts
    for coord in ds_out.coords:
        ds_out[coord].encoding.clear()

    # Setup compression
    comp = numcodecs.Blosc(cname="lz4", clevel=3, shuffle=numcodecs.Blosc.BITSHUFFLE)
    encoding = {var: {"compressor": comp} for var in ds_out.data_vars}

    # Output path
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{base_name}.zarr"

    logger.info("Writing to %s...", output_path)
    ds_out.to_zarr(
        str(output_path),
        mode="w",
        consolidated=True,
        zarr_format=2,
        encoding=encoding,
    )

    logger.info("Successfully wrote %s", output_path)

    # Verification
    reopened = xr.open_zarr(str(output_path), consolidated=True)
    logger.info("Verification - reopened dataset: %s", dict(reopened.sizes))


def main():
    args = parse_args()

    if args.list:
        list_datasets(args.input_dir)
        return

    if not args.datasets and not args.all:
        print("Error: Must specify --datasets, --all, or --list")
        print("Use --list to see available datasets")
        return

    datasets = scan_datasets(args.input_dir)

    if not datasets:
        print(f"No zarr datasets found in {args.input_dir}")
        return

    # Determine which datasets to process
    if args.all:
        to_process = list(datasets.keys())
    else:
        to_process = args.datasets
        # Validate that requested datasets exist
        for name in to_process:
            if name not in datasets:
                logger.error("Dataset not found: %s", name)
                logger.info("Available datasets: %s", ", ".join(sorted(datasets.keys())))
                return

    logger.info("Will consolidate %d dataset(s)", len(to_process))

    for base_name in to_process:
        paths = datasets[base_name]
        consolidate_dataset(
            base_name=base_name,
            paths=paths,
            output_dir=args.output_dir,
            time_chunk=args.time_chunk,
            values_chunk=args.values_chunk,
            level_chunk=args.level_chunk,
            target_chunk_mb=args.target_chunk_mb,
            force=args.force,
        )

    logger.info("Done!")


if __name__ == "__main__":
    main()
