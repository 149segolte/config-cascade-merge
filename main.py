#!/usr/bin/env -S uv run

import logging
import sys
from argparse import ArgumentParser
from pathlib import Path

import yaml

from utils import parse_schema

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")


def run(base_path: Path, overlays_dir: Path) -> None:
    base = base_path.read_text()
    base = yaml.safe_load(base)

    try:
        base = parse_schema(base)
    except (TypeError, ValueError) as e:
        logging.error(f"failed to parse base config: {e}")
        sys.exit(1)

    overlays = list(overlays_dir.glob("*.yaml"))
    logging.debug(overlays)

    for overlay in overlays:
        overlay = overlay.read_text()
        overlay = yaml.safe_load(overlay)
        logging.debug(overlay)


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
        logging.error(f"base config not found at `{base_config_path}`")
        sys.exit(1)

    overlays_dir = Path(args.overlays_dir)
    if not overlays_dir.exists() or not overlays_dir.is_dir():
        logging.error(
            f"overlays directory `{overlays_dir}` does not exist or is not a directory"
        )
        sys.exit(1)

    run(base_config_path, overlays_dir)


if __name__ == "__main__":
    main()
