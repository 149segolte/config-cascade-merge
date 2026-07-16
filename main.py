"""Thin entrypoint: load example_config.yaml and run a demo merge."""

from __future__ import annotations

from pathlib import Path

import yaml

from config_merger import merge


def main() -> None:
    config_file = Path("example_config.yaml")
    config = yaml.safe_load(config_file.read_text())

    # Two sample inputs that exercise most schema features.
    input1 = {
        "data": {
            "user": {"name": "Alice", "email": "alice@example.com"},
        },
        "environment": {
            "packages": [
                {"kind": "brew", "name": "git"},
                {"kind": "mise", "name": "node", "version": "20.0.0"},
                {"kind": "custom", "name": "dotfiles", "files": ["~/.zshrc"]},
            ],
            "shell": {
                "aliases": {"gs": "git status", "gl": "git log"},
                "config": ["set -e", "set -u"],
            },
        },
        "modules": {
            "work": {"theme": "dark", "font": "JetBrains Mono"},
        },
    }

    input2 = {
        "environment": {
            "packages": [
                {"kind": "brew", "name": "ripgrep"},
                # Override the node version from input1.
                {"kind": "mise", "name": "node", "version": "22.0.0"},
            ],
            "shell": {
                "aliases": {"gco": "git checkout"},
                "abbreviations": {"gc": "git commit"},
            },
        },
        "modules": {
            "personal": {"theme": "light"},
            # Merge into the 'work' module from input1.
            "work": {"font-size": 14},
        },
    }

    result = merge(config, [{}, input1, input2])
    print(
        yaml.dump(result, default_flow_style=False, allow_unicode=True, sort_keys=False)
    )


if __name__ == "__main__":
    main()
