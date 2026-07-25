# SPDX-License-Identifier: MPL-2.0

import pytest

from config_merger import SchemaError, load_yaml, parse_schema
from config_merger.schema import (
    PRIMITIVE_TYPES,
    ListNode,
    MapNode,
    ObjectNode,
    PrimitiveNode,
    TaggedUnionNode,
    UnionNode,
)


@pytest.mark.parametrize(
    "primitive_type", ["string", "integer", "float", "boolean", "any"]
)
def test_parse_schema_normalizes_primitive_types(
    primitive_type: PRIMITIVE_TYPES,
) -> None:
    assert parse_schema({"type": primitive_type}) == PrimitiveNode(primitive_type)


def test_parse_schema_normalizes_nested_compound_types() -> None:
    schema = parse_schema(
        {
            "type": "object",
            "id": "name",
            "merge": "override",
            "keys": {
                "labels": {
                    "type": "map",
                    "merge": "override",
                    "value": {"type": "string"},
                },
                "members": {
                    "type": "list",
                    "id": "name",
                    "value": {"type": "integer"},
                },
            },
        }
    )

    assert isinstance(schema, ObjectNode)
    assert schema.id == "name"
    assert schema.merge_policy == "override"
    assert schema.keys["labels"] == MapNode(
        value=PrimitiveNode("string"), merge_policy="override"
    )
    assert schema.keys["members"] == ListNode(value=PrimitiveNode("integer"), id="name")


def test_parse_schema_normalizes_union_branches() -> None:
    schema = parse_schema(
        {
            "type": "union",
            "value": [{"type": "string"}, {"type": "integer"}],
        }
    )

    assert schema == UnionNode(
        branches=[PrimitiveNode("string"), PrimitiveNode("integer")]
    )


def test_parse_schema_normalizes_tagged_union() -> None:
    schema = parse_schema(
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

    assert isinstance(schema, TaggedUnionNode)
    assert schema.tag_field == "kind"
    assert schema.common_keys == {"label": PrimitiveNode("string")}
    assert schema.options["file"].extra_keys == {"path": PrimitiveNode("string")}
    assert schema.options["disabled"].extra_keys == {}


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (None, "Schema node must be a mapping"),
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
    ],
)
def test_parse_schema_rejects_invalid_nodes(config: object, message: str) -> None:
    with pytest.raises(SchemaError, match=message):
        parse_schema(config)


def test_schema_error_uses_yaml_field_location() -> None:
    document = load_yaml(
        "type: object\nkeys:\n  count:\n    type: unknown\n", "base.yaml"
    )

    with pytest.raises(SchemaError) as error:
        parse_schema(document)

    assert str(error.value).startswith("base.yaml:4:")
    assert "Unknown type string 'unknown'" in str(error.value)


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
        parse_schema(config)
