# SPDX-License-Identifier: MPL-2.0

from collections.abc import Mapping
from typing import Any

import pytest
import yaml

from config_cascade_merge import Schema, SchemaError


@pytest.mark.parametrize(
    "primitive_type",
    ["string", "integer", "float", "boolean", "any"],
)
def test_schema_normalizes_primitive_types(primitive_type: str) -> None:
    from_data = Schema.from_data({"type": primitive_type})
    from_yaml = Schema.from_yaml(f"type: {primitive_type}\n")

    assert from_data == from_yaml


def test_schema_normalizes_compound_defaults() -> None:
    implicit = Schema.from_data(
        {
            "type": "object",
            "keys": {
                "labels": {"type": "map", "value": {"type": "string"}},
                "members": {"type": "list", "value": {"type": "integer"}},
            },
        }
    )
    explicit = Schema.from_data(
        {
            "type": "object",
            "merge": "append",
            "keys": {
                "labels": {
                    "type": "map",
                    "merge": "append",
                    "value": {"type": "string"},
                },
                "members": {
                    "type": "list",
                    "merge": "append",
                    "value": {"type": "integer"},
                },
            },
        }
    )

    assert implicit == explicit


def test_schema_normalizes_union_branches() -> None:
    from_data = Schema.from_data(
        {
            "type": "union",
            "value": [{"type": "string"}, {"type": "integer"}],
        }
    )
    from_yaml = Schema.from_yaml(
        "type: union\n"
        "value:\n"
        "  - {type: string}\n"
        "  - {type: integer}\n"
    )

    assert from_data == from_yaml


def test_schema_normalizes_tagged_union() -> None:
    from_data = Schema.from_data(
        {
            "type": "tagged_union",
            "keys": {"label": {"type": "string"}},
            "tag": {
                "name": "kind",
                "options": {
                    "file": {"path": {"type": "string"}},
                    "disabled": None,
                },
            },
        }
    )
    from_yaml = Schema.from_yaml(
        "type: tagged_union\n"
        "keys:\n"
        "  label: {type: string}\n"
        "tag:\n"
        "  name: kind\n"
        "  options:\n"
        "    file:\n"
        "      path: {type: string}\n"
        "    disabled:\n"
    )

    assert from_data == from_yaml


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({}, "Missing required 'type' string field"),
        ({"type": 3}, "'type' must be a string"),
        ({"type": "missing"}, "Unknown type string 'missing'"),
        ({"type": "list"}, "'list' requires a 'value' schema"),
        ({"type": "map"}, "'map' requires a 'value' schema"),
        (
            {"type": "object", "merge": "invalid"},
            "'merge' must be one of",
        ),
        ({"type": "object", "id": ""}, "'id' must not be empty"),
        (
            {"type": "union", "value": [{"type": "string"}]},
            "requires at least two branches",
        ),
        ({"type": "tagged_union"}, "requires a 'tag' mapping"),
        (
            {"type": "object", "keys": {"child": None}},
            "Schema node must be a mapping",
        ),
    ],
)
def test_schema_from_data_rejects_invalid_nodes(
    config: Mapping[str, Any],
    message: str,
) -> None:
    with pytest.raises(SchemaError, match=message):
        Schema.from_data(config, source="decoded schema")


def test_schema_from_data_rejects_non_mapping_root() -> None:
    decoded = yaml.safe_load("[]\n")

    with pytest.raises(SchemaError, match="Schema data must be a mapping"):
        Schema.from_data(decoded)


def test_schema_error_uses_yaml_field_location() -> None:
    with pytest.raises(SchemaError) as error:
        Schema.from_yaml(
            "type: object\nkeys:\n  count:\n    type: unknown\n",
            source="base.yaml",
        )

    assert str(error.value).startswith("base.yaml:4:")
    assert "Unknown type string 'unknown'" in str(error.value)


def test_schema_from_yaml_rejects_empty_and_malformed_documents() -> None:
    with pytest.raises(SchemaError, match="Schema document is empty") as empty:
        Schema.from_yaml("", source="empty.yaml")
    with pytest.raises(SchemaError, match="Could not parse schema YAML") as malformed:
        Schema.from_yaml("type: [unterminated\n", source="malformed.yaml")

    assert str(empty.value).startswith("empty.yaml:1:")
    assert str(malformed.value).startswith("malformed.yaml:")


def test_tagged_union_rejects_branch_key_also_declared_as_common() -> None:
    config = {
        "type": "tagged_union",
        "keys": {"label": {"type": "string"}},
        "tag": {
            "name": "kind",
            "options": {"file": {"label": {"type": "string"}}},
        },
    }

    with pytest.raises(SchemaError, match="also present in common_keys"):
        Schema.from_data(config)
