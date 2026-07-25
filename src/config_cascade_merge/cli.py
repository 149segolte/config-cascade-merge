# SPDX-License-Identifier: MPL-2.0

"""Command-line interface for config-cascade-merge."""

import sys
from argparse import ArgumentParser
from pathlib import Path

from config_cascade_merge import (
    ConfigError,
    MergePlan,
    configure_logging,
    load_merge_plan,
    logger,
)


def run(base_path: Path, overlays_dir: Path) -> MergePlan | None:
    """Load a merge plan and render library errors for CLI users."""
    try:
        plan = load_merge_plan(base_path, overlays_dir)
    except ConfigError as error:
        logger.error(error)
        sys.exit(1)

    if plan is None:
        logger.info("base config is empty, exiting.")
        return None

    logger.debug("base config: %s", plan.schema)
    logger.debug("overlay operations: %s", plan.operations)
    return plan


def main() -> None:
    """Run the config-cascade-merge command-line interface."""
    configure_logging()
    parser = ArgumentParser(
        prog="config-cascade-merge",
        description="Validate YAML overlay operations against a base schema.",
    )
    parser.add_argument(
        "-b", "--base_config", type=str, help="path to the base config file"
    )
    parser.add_argument(
        "-o",
        "--overlays_dir",
        type=str,
        help="directory containing overlay config files",
    )
    args = parser.parse_args()

    if not args.base_config or not args.overlays_dir:
        parser.print_help()
        sys.exit(1)

    base_config_path = Path(args.base_config)
    if not base_config_path.exists() or not base_config_path.is_file():
        logger.error(f"base config not found at `{base_config_path}`")
        sys.exit(1)

    overlays_dir = Path(args.overlays_dir)
    if not overlays_dir.exists() or not overlays_dir.is_dir():
        logger.error(
            f"overlays directory `{overlays_dir}` does not exist or is not a directory"
        )
        sys.exit(1)

    run(base_config_path, overlays_dir)


if __name__ == "__main__":
    main()
