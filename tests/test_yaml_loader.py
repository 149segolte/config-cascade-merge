# SPDX-License-Identifier: MPL-2.0

from pathlib import Path

import pytest
from yaml.constructor import ConstructorError

from config_merger.logging import ConfigError
from config_merger.yaml_loader import (
    SourceLocation,
    field_location,
    item_location,
    load_yaml,
    node_location,
)


def test_load_yaml_preserves_file_and_line_locations() -> None:
    document = load_yaml(
        "root:\n  values:\n    - first\n    - second\n",
        file_name=Path("config.yaml"),
    )

    root = document["root"]
    values = root["values"]

    assert node_location(document) == SourceLocation("config.yaml", 1)
    assert field_location(document, "root") == SourceLocation("config.yaml", 2)
    assert node_location(root) == SourceLocation("config.yaml", 2)
    assert field_location(root, "values") == SourceLocation("config.yaml", 3)
    assert node_location(values) == SourceLocation("config.yaml", 3)
    assert item_location(values, 1) == SourceLocation("config.yaml", 4)


def test_location_helpers_use_fallback_for_plain_python_values() -> None:
    fallback = SourceLocation("fallback.yaml", 9)

    assert node_location({}, fallback) == fallback
    assert field_location({}, "missing", fallback) == fallback
    assert item_location([], 0, fallback) == fallback


def test_load_yaml_rejects_unhashable_mapping_keys() -> None:
    with pytest.raises(ConstructorError, match="found unhashable key"):
        load_yaml("? [one, two]\n: value\n")


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        (None, "invalid config"),
        (SourceLocation(line_number=4), "line 4: invalid config"),
        (SourceLocation(file_name="base.yaml"), "base.yaml: invalid config"),
        (
            SourceLocation(file_name="base.yaml", line_number=4),
            "base.yaml:4: invalid config",
        ),
    ],
)
def test_config_error_formats_available_source_location(
    location: SourceLocation | None, expected: str
) -> None:
    assert str(ConfigError("invalid config", location)) == expected
