"""
Create an intake catalog from consolidated zarr files.

Scans the joint output directory and creates an intake catalog that groups
zarr files by model, activity, experiment, and level type. Files with the
same group but different dimensions are split into separate sources.

Usage:
    python create_intake_catalog.py
    python create_intake_catalog.py --input-dir /path/to/zarr/files
    python create_intake_catalog.py --output catalog.yaml
"""

import argparse
import logging
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import xarray as xr
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_INPUT_DIR = Path("/work/ab0995/a270088/DestinE/PHASE2_zarr_joint/")

# Resolution values based on values dimension (exact values)
HIGH_RES_VALUES = 12582912  # High resolution grid points
STANDARD_RES_VALUES = 196608  # Standard resolution grid points


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create intake catalog from consolidated zarr files."
    )
    parser.add_argument(
        "--input-dir", type=Path, default=DEFAULT_INPUT_DIR,
        help=f"Input directory with consolidated zarr files (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output catalog filename (default: catalog.yaml in input directory)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print catalog to stdout without writing file",
    )
    return parser.parse_args()


def parse_zarr_filename(filename: str) -> dict | None:
    """Parse a consolidated zarr filename into components.

    Expected pattern: {model}_{activity}_{experiment}_{levtype}_{param}.zarr

    Examples:
        ifs-fesom_baseline_hist_sfc_228004.zarr
        icon_projections_ssp3-7.0_o2d_263101.zarr
    """
    name = filename.replace(".zarr", "")

    # Pattern: model_activity_experiment_levtype_param
    # model can contain hyphens (e.g., ifs-fesom, ifs-nemo)
    # activity: baseline, projections
    # experiment: hist, ssp3-7.0, etc.
    # levtype: sfc, o2d, o3d
    # param: numeric code
    pattern = r"^(.+?)_(baseline|projections)_(.+?)_(sfc|o2d|o3d)_(\d+)$"
    match = re.match(pattern, name)

    if match:
        return {
            "model": match.group(1),
            "activity": match.group(2),
            "experiment": match.group(3),
            "levtype": match.group(4),
            "param": match.group(5),
            "full_name": name,
        }
    return None


def get_group_key(parsed: dict) -> str:
    """Create a group key from parsed components (without param)."""
    return f"{parsed['model']}_{parsed['activity']}_{parsed['experiment']}_{parsed['levtype']}"


def get_dataset_info(zarr_path: Path) -> dict | None:
    """Get dimensions, sizes, and time frequency from a zarr dataset."""
    try:
        ds = xr.open_zarr(zarr_path, consolidated=True)
    except Exception as e:
        logger.warning("Failed to read %s with consolidated=True: %s", zarr_path, e)
        try:
            ds = xr.open_zarr(zarr_path, consolidated=False)
        except Exception as e2:
            logger.error("Cannot open %s: %s", zarr_path, e2)
            return None

    dims = dict(ds.sizes)

    # Try to determine time frequency
    time_freq = None
    if "time" in ds.dims and ds.sizes["time"] > 1:
        try:
            time_vals = ds["time"].values
            if len(time_vals) >= 2:
                # Calculate median time difference
                time_diffs = np.diff(time_vals).astype("timedelta64[h]").astype(float)
                median_hours = np.median(time_diffs)

                if median_hours <= 1.5:
                    time_freq = "hourly"
                elif median_hours <= 6:
                    time_freq = "3hourly"
                elif median_hours <= 12:
                    time_freq = "6hourly"
                elif median_hours <= 36:
                    time_freq = "daily"
                elif median_hours <= 24 * 45:  # up to ~45 days covers monthly
                    time_freq = "monthly"
                else:
                    time_freq = "yearly"
        except Exception as e:
            logger.debug("Could not determine time frequency for %s: %s", zarr_path, e)

    ds.close()

    return {
        "dims": dims,
        "time_freq": time_freq,
    }


def get_resolution_label(values_size: int) -> str:
    """Get resolution label based on values dimension size (exact match)."""
    if values_size == HIGH_RES_VALUES:
        return "high"
    elif values_size == STANDARD_RES_VALUES:
        return "standard"
    else:
        # Unknown resolution - include the actual value
        return f"res{values_size}"


def generate_suffix(info: dict | None) -> str:
    """Generate an informative suffix based on dataset characteristics."""
    if info is None:
        return "_unknown"

    parts = []
    dims = info.get("dims", {})

    # Add resolution indicator
    if "values" in dims:
        res_label = get_resolution_label(dims["values"])
        parts.append(res_label)

    # Add time frequency if available
    time_freq = info.get("time_freq")
    if time_freq:
        parts.append(time_freq)

    if parts:
        return "_" + "_".join(parts)
    return "_unknown"


def info_matches(info1: dict, info2: dict) -> bool:
    """Check if two dataset info dictionaries match (same dims and time freq)."""
    if info1 is None or info2 is None:
        return False
    return info1.get("dims") == info2.get("dims") and info1.get("time_freq") == info2.get("time_freq")


def scan_and_group_zarrs(input_dir: Path) -> dict:
    """Scan directory for zarr files and group by model/activity/experiment/levtype."""
    groups = defaultdict(list)

    for zarr_path in sorted(input_dir.glob("*.zarr")):
        if not zarr_path.is_dir():
            continue

        parsed = parse_zarr_filename(zarr_path.name)
        if parsed is None:
            logger.warning("Could not parse filename: %s", zarr_path.name)
            continue

        group_key = get_group_key(parsed)
        info = get_dataset_info(zarr_path)

        groups[group_key].append({
            "path": zarr_path,
            "parsed": parsed,
            "info": info,
        })

    return dict(groups)


def split_by_info(files: list[dict]) -> list[list[dict]]:
    """Split a list of files into sublists with matching dimensions and time freq."""
    if not files:
        return []

    result = []

    for file_info in files:
        placed = False
        for sublist in result:
            if info_matches(file_info["info"], sublist[0]["info"]):
                sublist.append(file_info)
                placed = True
                break

        if not placed:
            result.append([file_info])

    return result


def create_catalog(input_dir: Path) -> dict:
    """Create the intake catalog structure."""
    groups = scan_and_group_zarrs(input_dir)

    sources = {}

    for group_key in sorted(groups.keys()):
        files = groups[group_key]
        logger.info("Processing group: %s (%d files)", group_key, len(files))

        # Split by matching dimensions and time frequency
        info_groups = split_by_info(files)

        for info_group in info_groups:
            # Always generate suffix based on resolution and time frequency
            suffix = generate_suffix(info_group[0]["info"])
            source_name = f"{group_key}{suffix}"

            # Log info
            info = info_group[0]["info"]
            dims = info.get("dims", {}) if info else {}
            time_freq = info.get("time_freq") if info else None
            params = [f["parsed"]["param"] for f in info_group]
            logger.info(
                "  Source: %s | dims: %s | time_freq: %s | params: %s",
                source_name, dims, time_freq, params
            )

            # Build urlpath list
            urlpaths = [str(f["path"]) for f in sorted(info_group, key=lambda x: x["parsed"]["param"])]

            # Build args - only include multi-file options when there are multiple files
            args = {
                "consolidated": True,
                "urlpath": urlpaths if len(urlpaths) > 1 else urlpaths[0],
            }
            if len(urlpaths) > 1:
                args["combine"] = "by_coords"
                args["compat"] = "override"
                args["parallel"] = True

            sources[source_name] = {
                "driver": "zarr",
                "args": args,
            }

    catalog = {"sources": sources}
    return catalog


def main():
    args = parse_args()

    if not args.input_dir.exists():
        logger.error("Input directory does not exist: %s", args.input_dir)
        return

    logger.info("Scanning zarr files in: %s", args.input_dir)
    catalog = create_catalog(args.input_dir)

    if not catalog["sources"]:
        logger.error("No valid zarr files found")
        return

    logger.info("Created catalog with %d sources", len(catalog["sources"]))

    # Custom YAML representer for better formatting
    def str_representer(dumper, data):
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    yaml.add_representer(str, str_representer)

    # Generate YAML with nice formatting
    yaml_content = yaml.dump(
        catalog,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=120,
    )

    if args.dry_run:
        print(yaml_content)
    else:
        output_path = args.output if args.output else args.input_dir / "catalog.yaml"
        output_path = Path(output_path)

        with open(output_path, "w") as f:
            f.write(yaml_content)

        logger.info("Catalog written to: %s", output_path)


if __name__ == "__main__":
    main()
