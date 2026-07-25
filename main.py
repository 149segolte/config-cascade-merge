#!/usr/bin/env -S uv run
# SPDX-License-Identifier: MPL-2.0

import sys
from argparse import ArgumentParser
from pathlib import Path

from utils import (
    OverlayError,
    SchemaError,
    configure_logging,
    load_overlays,
    load_yaml,
    logger,
    parse_schema,
)

configure_logging()


def run(base_path: Path, overlays_dir: Path) -> None:
    base = base_path.read_text()
    base = load_yaml(base, file_name=base_path)
    if base is None:
        logger.info("base config is empty, exiting.")
        return

    try:
        base = parse_schema(base)
    except SchemaError as e:
        logger.error(e)
        sys.exit(1)

    logger.debug(f"base config: {base}")

    try:
        operations = load_overlays(overlays_dir, base)
    except OverlayError as e:
        logger.error(e)
        sys.exit(1)

    logger.debug("overlay operations: %s", operations)


def main() -> None:
    parser = ArgumentParser()
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
