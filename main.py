from pathlib import Path
from typing import Iterable

import yaml


def merge(config: dict, iter: Iterable[dict]) -> dict:
    pass


def main():
    config_file = Path("example_config.yaml")
    config = yaml.safe_load(config_file.read_text())

    test = []
    data = merge(config, test)
    print(data)


if __name__ == "__main__":
    main()
