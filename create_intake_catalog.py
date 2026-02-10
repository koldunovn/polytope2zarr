"""
Create an intake catalog from consolidated zarr files.

Scans the joint output directory and creates an intake catalog that groups
zarr files by activity, experiment, generation, model, realization, expver,
stream, resolution, and level type. Multiple parameters with the same
grouping are combined into a single source.

Expected input naming convention (consolidated files):
  {activity}_{experiment}_{generation}_{model}_{realization}_{expver}_{stream}_{resolution}_{levtype}_{param}.zarr

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

import xarray as xr
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_INPUT_DIR = Path("/work/ab0995/a270088/DestinE/GENERATION2_joint/")


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

    Expected pattern:
      {activity}_{experiment}_{generation}_{model}_{realization}_{expver}_{stream}_{resolution}_{levtype}_{param}.zarr

    Examples:
        baseline_hist_2_ifs-fesom_1_0001_clmn_high_sfc_228004.zarr
        projections_ssp3-7.0_2_icon_1_0001_clmn_standard_o2d_263101.zarr
    """
    name = filename.replace(".zarr", "")

    # Pattern breakdown:
    # activity: baseline, projections, story-nudging
    # experiment: hist, ssp3-7.0, cont, tplus2k, etc.
    # generation: numeric
    # model: can contain hyphens (ifs-fesom, ifs-nemo, icon)
    # realization: numeric
    # expver: numeric string (0001)
    # stream: clmn, clte
    # resolution: high, standard
    # levtype: sfc, o2d, o3d
    # param: numeric code
    pattern = (
        r"^(baseline|projections|story-nudging)_"  # activity
        r"([^_]+)_"                   # experiment
        r"(\d+)_"                     # generation
        r"([^_]+(?:-[^_]+)?)_"        # model (may contain hyphen)
        r"(\d+)_"                     # realization
        r"(\d+)_"                     # expver
        r"(clmn|clte)_"              # stream
        r"(high|standard)_"          # resolution
        r"(sfc|pl|o2d|o3d)_"         # levtype
        r"(\d+)$"                     # param
    )
    match = re.match(pattern, name)

    if match:
        return {
            "activity": match.group(1),
            "experiment": match.group(2),
            "generation": match.group(3),
            "model": match.group(4),
            "realization": match.group(5),
            "expver": match.group(6),
            "stream": match.group(7),
            "resolution": match.group(8),
            "levtype": match.group(9),
            "param": match.group(10),
            "full_name": name,
        }
    return None


def get_group_key(parsed: dict) -> str:
    """Create a group key from parsed components (without param).

    Groups files that should be combined into a single intake source.
    """
    return (
        f"{parsed['activity']}_{parsed['experiment']}_{parsed['generation']}_"
        f"{parsed['model']}_{parsed['realization']}_{parsed['expver']}_"
        f"{parsed['stream']}_{parsed['resolution']}_{parsed['levtype']}"
    )


def get_dataset_dims(zarr_path: Path) -> dict | None:
    """Get dimensions from a zarr dataset for logging purposes."""
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
    ds.close()
    return dims


def scan_and_group_zarrs(input_dir: Path) -> dict:
    """Scan directory for zarr files and group by common attributes (without param)."""
    groups = defaultdict(list)

    for zarr_path in sorted(input_dir.glob("*.zarr")):
        if not zarr_path.is_dir():
            continue

        parsed = parse_zarr_filename(zarr_path.name)
        if parsed is None:
            logger.warning("Could not parse filename: %s", zarr_path.name)
            continue

        group_key = get_group_key(parsed)
        dims = get_dataset_dims(zarr_path)

        groups[group_key].append({
            "path": zarr_path,
            "parsed": parsed,
            "dims": dims,
        })

    return dict(groups)


def create_catalog(input_dir: Path) -> dict:
    """Create the intake catalog structure."""
    groups = scan_and_group_zarrs(input_dir)

    sources = {}

    for group_key in sorted(groups.keys()):
        files = groups[group_key]
        logger.info("Processing group: %s (%d files)", group_key, len(files))

        # Use group_key directly as source name (already contains all relevant info)
        source_name = group_key

        # Log info
        params = [f["parsed"]["param"] for f in files]
        dims = files[0]["dims"] if files[0]["dims"] else {}
        stream = files[0]["parsed"]["stream"]
        logger.info(
            "  Source: %s | dims: %s | stream: %s | params: %s",
            source_name, dims, stream, params
        )

        # Build urlpath list
        urlpaths = [str(f["path"]) for f in sorted(files, key=lambda x: x["parsed"]["param"])]

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
