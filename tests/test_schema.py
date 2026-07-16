"""Tests for config_merger.schema – Phase 1: schema normalization."""

from __future__ import annotations

import pytest

from config_merger.errors import (
    InvalidTaggedUnionConfigError,
    SchemaValidationError,
    UnsupportedPolicyError,
)
from config_merger.schema import (
    ListNode,
    MapNode,
    ObjectNode,
    PrimitiveNode,
    TaggedUnionBranch,
    TaggedUnionNode,
    UnionNode,
    parse_schema,
)

# ---------------------------------------------------------------------------
# Primitive types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ptype", ["string", "integer", "float", "boolean", "any"])
def test_parse_primitive(ptype):
    node = parse_schema({"type": ptype})
    assert isinstance(node, PrimitiveNode)
    assert node.type == ptype


# ---------------------------------------------------------------------------
# Object
# ---------------------------------------------------------------------------


def test_parse_object_basic():
    node = parse_schema(
        {
            "type": "object",
            "merge": "append",
            "keys": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
        }
    )
    assert isinstance(node, ObjectNode)
    assert node.merge_policy == "append"
    assert node.id is None
    assert node.drop_prefix == "-"
    assert set(node.keys) == {"name", "age"}
    assert isinstance(node.keys["name"], PrimitiveNode)
    assert node.keys["name"].type == "string"


def test_parse_object_with_id_and_drop_prefix():
    node = parse_schema(
        {
            "type": "object",
            "id": "name",
            "drop_prefix": "~",
            "keys": {"name": {"type": "string"}},
        }
    )
    assert isinstance(node, ObjectNode)
    assert node.id == "name"
    assert node.drop_prefix == "~"


def test_parse_object_override_policy():
    node = parse_schema({"type": "object", "merge": "override", "keys": {}})
    assert isinstance(node, ObjectNode)
    assert node.merge_policy == "override"


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------


def test_parse_map():
    node = parse_schema(
        {
            "type": "map",
            "merge": "append",
            "value": {"type": "string"},
        }
    )
    assert isinstance(node, MapNode)
    assert node.merge_policy == "append"
    assert isinstance(node.value, PrimitiveNode)
    assert node.value.type == "string"


def test_parse_map_requires_value():
    with pytest.raises(SchemaValidationError, match="requires a 'value' schema"):
        parse_schema({"type": "map"})


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_parse_list():
    node = parse_schema(
        {
            "type": "list",
            "merge": "append",
            "id": "name",
            "value": {"type": "string"},
        }
    )
    assert isinstance(node, ListNode)
    assert node.id == "name"
    assert isinstance(node.value, PrimitiveNode)


def test_parse_list_requires_value():
    with pytest.raises(SchemaValidationError, match="requires a 'value' schema"):
        parse_schema({"type": "list"})


# ---------------------------------------------------------------------------
# Union
# ---------------------------------------------------------------------------


def test_parse_union():
    node = parse_schema(
        {
            "type": "union",
            "merge": "override",
            "value": [
                {"type": "string"},
                {"type": "integer"},
            ],
        }
    )
    assert isinstance(node, UnionNode)
    assert len(node.branches) == 2
    assert isinstance(node.branches[0], PrimitiveNode)
    assert node.branches[0].type == "string"


def test_parse_union_requires_override():
    with pytest.raises(UnsupportedPolicyError):
        parse_schema(
            {
                "type": "union",
                "merge": "append",
                "value": [{"type": "string"}, {"type": "integer"}],
            }
        )


def test_parse_union_requires_multiple_branches():
    with pytest.raises(SchemaValidationError, match="at least two branches"):
        parse_schema(
            {
                "type": "union",
                "merge": "override",
                "value": [{"type": "string"}],
            }
        )


def test_parse_union_value_must_be_list():
    with pytest.raises(SchemaValidationError, match="list of branch schemas"):
        parse_schema(
            {
                "type": "union",
                "merge": "override",
                "value": {"type": "string"},
            }
        )


# ---------------------------------------------------------------------------
# Tagged union
# ---------------------------------------------------------------------------


def test_parse_tagged_union_basic():
    node = parse_schema(
        {
            "type": "tagged_union",
            "merge": "override",
            "tag": {
                "name": "kind",
                "options": {
                    "foo": None,
                    "bar": {"extra": {"type": "string"}},
                },
                "keys": {
                    "name": {"type": "string"},
                },
            },
        }
    )
    assert isinstance(node, TaggedUnionNode)
    assert node.tag_field == "kind"
    assert "foo" in node.options
    assert "bar" in node.options
    assert node.options["foo"].extra_keys == {}
    assert "extra" in node.options["bar"].extra_keys
    assert "name" in node.common_keys


def test_parse_tagged_union_requires_override():
    with pytest.raises(UnsupportedPolicyError):
        parse_schema(
            {
                "type": "tagged_union",
                "merge": "append",
                "tag": {"name": "kind", "options": {}},
            }
        )


def test_parse_tagged_union_requires_tag_mapping():
    with pytest.raises(InvalidTaggedUnionConfigError):
        parse_schema(
            {
                "type": "tagged_union",
                "merge": "override",
                "tag": "not-a-dict",
            }
        )


def test_parse_tagged_union_bad_option_type():
    with pytest.raises(InvalidTaggedUnionConfigError, match="null or a mapping"):
        parse_schema(
            {
                "type": "tagged_union",
                "merge": "override",
                "tag": {
                    "name": "kind",
                    "options": {"foo": 42},  # not null or dict
                },
            }
        )


# ---------------------------------------------------------------------------
# General validation errors
# ---------------------------------------------------------------------------


def test_missing_type():
    with pytest.raises(SchemaValidationError, match="Missing required 'type'"):
        parse_schema({"merge": "append"})


def test_unknown_type():
    with pytest.raises(SchemaValidationError, match="Unknown type"):
        parse_schema({"type": "nonsense"})


def test_non_dict_node():
    with pytest.raises(SchemaValidationError, match="must be a mapping"):
        parse_schema("string")  # type: ignore[arg-type]


def test_invalid_merge_policy():
    with pytest.raises(SchemaValidationError, match="'merge' must be"):
        parse_schema({"type": "object", "merge": "merge_and_then_some", "keys": {}})


def test_empty_drop_prefix():
    with pytest.raises(SchemaValidationError, match="must not be empty"):
        parse_schema({"type": "object", "drop_prefix": "", "keys": {}})


# ---------------------------------------------------------------------------
# Acceptance: example_config.yaml parses without error
# ---------------------------------------------------------------------------


def test_parse_example_config(example_config):
    node = parse_schema(example_config)
    assert isinstance(node, ObjectNode)
    assert "data" in node.keys
    assert "environment" in node.keys
    assert "modules" in node.keys

    # Verify packages list
    env_node = node.keys["environment"]
    assert isinstance(env_node, ObjectNode)
    pkgs_node = env_node.keys["packages"]
    assert isinstance(pkgs_node, ListNode)
    assert pkgs_node.id == "name"

    # Verify tagged_union inside packages
    assert isinstance(pkgs_node.value, TaggedUnionNode)
    tu = pkgs_node.value
    assert tu.tag_field == "kind"
    assert set(tu.options.keys()) == {"brew", "cask", "custom", "mise"}
    # brew and cask have no extra fields
    assert tu.options["brew"].extra_keys == {}
    assert tu.options["cask"].extra_keys == {}
    # custom has 'files'
    assert "files" in tu.options["custom"].extra_keys
    # mise has 'version' (a union)
    assert "version" in tu.options["mise"].extra_keys
    assert isinstance(tu.options["mise"].extra_keys["version"], UnionNode)
