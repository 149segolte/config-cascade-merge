# SPDX-License-Identifier: MPL-2.0

"""Command-line interface for config-cascade-merge."""

import sys
from argparse import ArgumentParser
from collections.abc import Sequence
from pathlib import Path

import yaml

from config_cascade_merge import ConfigError, MergePlan, Overlay, Schema
from config_cascade_merge.logging import configure_logging, logger


def run(
    base_path: Path,
    overlays: Path | Sequence[Path],
) -> MergePlan:
    """Load and execute a merge plan, emitting the completed object as YAML."""
    try:
        schema = Schema.from_file(base_path)
        overlay_paths = _overlay_paths(overlays)
        loaded_overlays = (
            Overlay.from_file(overlay_path, schema)
            for overlay_path in overlay_paths
        )
        plan = MergePlan(schema).with_overlays(loaded_overlays)
        result = plan.create_object()
    except ConfigError as error:
        logger.error(error)
        sys.exit(1)

    logger.debug("base config: %s", plan.schema)
    logger.debug("overlays: %s", plan.overlays)
    yaml.safe_dump(result, sys.stdout, sort_keys=False)
    return plan


def _overlay_paths(overlays: Path | Sequence[Path]) -> tuple[Path, ...]:
    """Resolve CLI overlay input while preserving its documented ordering."""
    if isinstance(overlays, Path):
        return tuple(
            sorted(
                (
                    path
                    for path in overlays.iterdir()
                    if path.suffix.lower() in {".yaml", ".yml"}
                ),
                key=lambda path: path.name,
            )
        )
    return tuple(overlays)


def main() -> None:
    """Run the config-cascade-merge command-line interface."""
    configure_logging()
    parser = ArgumentParser(
        prog="config-cascade-merge",
        description="Create a merged YAML object from validated overlay operations.",
    )
    parser.add_argument(
        "-b", "--base_config", type=str, help="path to the base config file"
    )
    overlays_group = parser.add_mutually_exclusive_group()
    overlays_group.add_argument(
        "--overlays_dir",
        type=str,
        help="directory containing overlay config files",
    )
    overlays_group.add_argument(
        "-o",
        "--overlays",
        dest="overlay_paths",
        nargs="+",
        metavar="PATH",
        help="ordered list of overlay config files",
    )
    args = parser.parse_args()

    if not args.base_config or not (args.overlays_dir or args.overlay_paths):
        parser.print_help()
        sys.exit(1)

    base_config_path = Path(args.base_config)
    if not base_config_path.exists() or not base_config_path.is_file():
        logger.error(f"base config not found at `{base_config_path}`")
        sys.exit(1)

    if args.overlays_dir:
        overlays: Path | list[Path] = Path(args.overlays_dir)
        if not overlays.exists() or not overlays.is_dir():
            logger.error(
                f"overlays directory `{overlays}` does not exist or is not a directory"
            )
            sys.exit(1)
    else:
        overlays = [Path(path) for path in args.overlay_paths]
        for overlay_path in overlays:
            if not overlay_path.exists() or not overlay_path.is_file():
                logger.error(
                    f"overlay path `{overlay_path}` does not exist or is not a file"
                )
                sys.exit(1)

    run(base_config_path, overlays)


if __name__ == "__main__":
    main()
