# SPDX-License-Identifier: MPL-2.0

"""Schema normalization for config-merger.

Converts a raw YAML config dict into a tree of typed SchemaNode objects.
All merge policies, drop prefixes, id fields, and branch structures are
resolved here so the engine receives a fully normalized representation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, cast, get_args

from .logging import SchemaError
from .yaml_loader import SourceLocation, field_location, item_location, node_location

# ---------------------------------------------------------------------------
# Type constants
# ---------------------------------------------------------------------------

PRIMITIVE_TYPES = Literal["string", "integer", "float", "boolean", "any"]
COMPOUND_TYPES = Literal["object", "map", "list", "union", "tagged_union"]
ALL_TYPES = PRIMITIVE_TYPES | COMPOUND_TYPES

MERGE_POLICIES = Literal["append", "override"]

_VALID_PRIMITIVE_TYPES = get_args(PRIMITIVE_TYPES)
_VALID_COMPOUND_TYPES = get_args(COMPOUND_TYPES)
_VALID_TYPES = _VALID_PRIMITIVE_TYPES + _VALID_COMPOUND_TYPES

_VALID_MERGE_POLICIES = get_args(MERGE_POLICIES)


# ---------------------------------------------------------------------------
# Schema node dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PrimitiveNode:
    """A leaf node: string, integer, float, boolean, or any.

    Primitives always behave as override merge policy.
    """

    type: PRIMITIVE_TYPES


@dataclass
class ObjectNode:
    """A fixed-key mapping node.

    `keys` preserves declaration order from the config.
    `id`, when present, is the field name used for identity matching.
    """

    keys: dict[str, SchemaNode]
    id: str | None = None
    merge_policy: MERGE_POLICIES = "append"


@dataclass
class MapNode:
    """An arbitrary-key mapping node with a uniform value schema."""

    value: SchemaNode
    id: str | None = None
    merge_policy: MERGE_POLICIES = "append"


@dataclass
class ListNode:
    """An ordered list node with a uniform item schema.

    `id`, when present, is the field name in each item used for identity-based
    matching across merge inputs.
    """

    value: SchemaNode
    id: str | None = None
    merge_policy: MERGE_POLICIES = "append"


@dataclass
class UnionNode:
    """A node that selects exactly one schema from a list of branches.

    merge_policy is implicitly always "override".
    """

    branches: list[SchemaNode]


@dataclass
class TaggedUnionBranch:
    """Extra fields specific to one tag variant of a TaggedUnionNode."""

    extra_keys: dict[str, SchemaNode]


@dataclass
class TaggedUnionNode:
    """A node that dispatches on a tag field to select a schema branch.

    merge_policy is implicitly always "override".
    """

    tag_field: str
    common_keys: dict[str, SchemaNode]  # shared by every variant
    options: dict[str, TaggedUnionBranch]  # tag value -> branch


# ---------------------------------------------------------------------------
# Recursive type alias  (resolved at runtime via forward references)
# ---------------------------------------------------------------------------

SchemaNode = (
    PrimitiveNode | ObjectNode | MapNode | ListNode | UnionNode | TaggedUnionNode
)

# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

# Registry of dispatch functions for compound node types (verified after handler declarations)
_dispatch: dict[
    COMPOUND_TYPES, Callable[[dict, SourceLocation | None], SchemaNode]
] = {}


def parse_schema(
    config: Any,
    path: str = "",
    location: SourceLocation | None = None,
) -> SchemaNode:
    """Parse and normalise a raw config dict into a SchemaNode tree.

    Args:
        config: Raw dict loaded from YAML (or a sub-section thereof).
        path: Deprecated. Kept for compatibility; error messages use source
            locations instead of schema paths.
        location: Source location to use when `config` has no YAML metadata.

    Returns:
        A fully normalised SchemaNode.

    Raises:
        SchemaError: Input data is not a valid schema.
    """
    del path

    node_loc = node_location(config, location)
    if not isinstance(config, dict):
        raise SchemaError(
            f"Schema node must be a mapping, got {type(config).__name__!r}",
            node_loc,
        )

    node_type = config.get("type")
    if node_type is None:
        raise SchemaError(
            "Missing required 'type' string field",
            field_location(config, "type", node_loc),
        )
    if not isinstance(node_type, str):
        raise SchemaError(
            f"'type' must be a string, got {type(node_type).__name__!r}",
            field_location(config, "type", node_loc),
        )
    if node_type not in _VALID_TYPES:
        raise SchemaError(
            f"Unknown type string {node_type!r}; valid types: {_VALID_TYPES}",
            field_location(config, "type", node_loc),
        )

    if node_type in _VALID_PRIMITIVE_TYPES:
        return PrimitiveNode(type=cast(PRIMITIVE_TYPES, node_type))

    return _dispatch[cast(COMPOUND_TYPES, node_type)](config, node_loc)


# ---------------------------------------------------------------------------
# Shared helper parsers
# ---------------------------------------------------------------------------


def _parse_merge_policy(
    config: dict,
    location: SourceLocation | None,
    default: MERGE_POLICIES = "append",
) -> MERGE_POLICIES:
    policy = config.get("merge")
    if policy is None:
        return default

    policy_location = field_location(config, "merge", location)
    if not isinstance(policy, str):
        raise SchemaError(
            f"'merge' must be a string, got {type(policy).__name__!r}",
            policy_location,
        )
    if policy not in _VALID_MERGE_POLICIES:
        raise SchemaError(
            f"'merge' must be one of {_VALID_MERGE_POLICIES}, got {policy!r}",
            policy_location,
        )
    return cast(MERGE_POLICIES, policy)


def _parse_id(config: dict, location: SourceLocation | None) -> str | None:
    id_field = config.get("id")
    if id_field is None:
        return None

    id_location = field_location(config, "id", location)
    if not isinstance(id_field, str):
        raise SchemaError(
            f"'id' must be a string, got {type(id_field).__name__!r}",
            id_location,
        )
    if id_field == "":
        raise SchemaError(
            f"if provided 'id' must not be empty, got {id_field!r}",
            id_location,
        )
    return id_field


def _parse_keys(config: dict, location: SourceLocation | None) -> dict[str, SchemaNode]:
    raw_keys = config.get("keys")
    if raw_keys is None:
        return {}

    keys_location = field_location(config, "keys", location)
    if not isinstance(raw_keys, dict):
        raise SchemaError(
            f"'keys' must be a mapping, got {type(raw_keys).__name__!r}",
            keys_location,
        )
    return {
        name: parse_schema(
            sub,
            location=field_location(raw_keys, name, keys_location),
        )
        for name, sub in raw_keys.items()
    }


# ---------------------------------------------------------------------------
# Per-type parsers
# ---------------------------------------------------------------------------


def _parse_object(config: dict, location: SourceLocation | None) -> ObjectNode:
    merge_policy = _parse_merge_policy(config, location)
    id_field = _parse_id(config, location)
    keys = _parse_keys(config, location)
    return ObjectNode(
        keys=keys,
        merge_policy=merge_policy,
        id=id_field,
    )


def _parse_map(config: dict, location: SourceLocation | None) -> MapNode:
    merge_policy = _parse_merge_policy(config, location)
    id_field = _parse_id(config, location)

    raw_value = config.get("value")
    value_location = field_location(config, "value", location)
    if raw_value is None:
        raise SchemaError("'map' requires a 'value' schema", value_location)
    value = parse_schema(raw_value, location=value_location)

    return MapNode(
        value=value,
        merge_policy=merge_policy,
        id=id_field,
    )


def _parse_list(config: dict, location: SourceLocation | None) -> ListNode:
    merge_policy = _parse_merge_policy(config, location)
    id_field = _parse_id(config, location)

    raw_value = config.get("value")
    value_location = field_location(config, "value", location)
    if raw_value is None:
        raise SchemaError("'list' requires a 'value' schema", value_location)
    value = parse_schema(raw_value, location=value_location)

    return ListNode(
        value=value,
        merge_policy=merge_policy,
        id=id_field,
    )


def _parse_union(config: dict, location: SourceLocation | None) -> UnionNode:
    raw_value = config.get("value")
    value_location = field_location(config, "value", location)
    if raw_value is None:
        raise SchemaError(
            "'union' requires a 'value' to be a list of branch schemas",
            value_location,
        )

    if not isinstance(raw_value, list):
        raise SchemaError(
            f"'union' requires a 'value' to be a list of branch schemas, got {type(raw_value).__name__!r}",
            value_location,
        )
    if len(raw_value) < 2:
        raise SchemaError(
            f"'union' requires at least two branches, got {len(raw_value)}",
            value_location,
        )

    branches = [
        parse_schema(
            branch_cfg,
            location=item_location(raw_value, i, value_location),
        )
        for i, branch_cfg in enumerate(raw_value)
    ]
    return UnionNode(branches=branches)


def _parse_tagged_union(
    config: dict, location: SourceLocation | None
) -> TaggedUnionNode:
    tag_config = config.get("tag")
    tag_location = field_location(config, "tag", location)
    if tag_config is None:
        raise SchemaError("tagged_union requires a 'tag' mapping", tag_location)

    if not isinstance(tag_config, dict):
        raise SchemaError(
            "tagged_union requires a 'tag' mapping with 'name' and 'options'",
            tag_location,
        )

    # tag.name ---------------------------------------------------------------
    tag_name = tag_config.get("name")
    name_location = field_location(tag_config, "name", tag_location)
    if not isinstance(tag_name, str):
        raise SchemaError(
            f"'name' must be a string, got {type(tag_name).__name__!r}",
            name_location,
        )

    # keys (common fields shared by every variant) ---------------------------
    raw_keys = config.get("keys") or {}
    keys_location = field_location(config, "keys", location)
    if not isinstance(raw_keys, dict):
        raise SchemaError(
            f"'keys' must be a mapping, got {type(raw_keys).__name__!r}",
            keys_location,
        )
    common_keys = {
        name: parse_schema(
            type_config,
            location=field_location(raw_keys, name, keys_location),
        )
        for name, type_config in raw_keys.items()
    }

    # tag.options ------------------------------------------------------------
    raw_options = tag_config.get("options") or {}
    options_location = field_location(tag_config, "options", tag_location)
    if not isinstance(raw_options, dict):
        raise SchemaError(
            f"'options' must be a mapping, got {type(raw_options).__name__!r}",
            options_location,
        )

    options: dict[str, TaggedUnionBranch] = {}
    for tag_value, option_config in raw_options.items():
        option_location = field_location(raw_options, tag_value, options_location)
        if option_config is None:
            # Null option: this tag is valid but has no extra fields.
            options[tag_value] = TaggedUnionBranch(extra_keys={})
        elif isinstance(option_config, dict):
            extra_keys = {
                name: parse_schema(
                    type_config,
                    location=field_location(option_config, name, option_location),
                )
                for name, type_config in option_config.items()
            }
            for key in extra_keys.keys():
                if key in common_keys:
                    raise SchemaError(
                        f"Extra key {key!r} is also present in common_keys",
                        field_location(option_config, key, option_location),
                    )
            options[tag_value] = TaggedUnionBranch(extra_keys=extra_keys)
        else:
            raise SchemaError(
                f"Option {tag_value!r} must be null or a mapping of extra field schemas; got {type(option_config).__name__!r}",
                option_location,
            )

    return TaggedUnionNode(
        tag_field=tag_name,
        common_keys=common_keys,
        options=options,
    )


_dispatch = {
    "object": _parse_object,
    "map": _parse_map,
    "list": _parse_list,
    "union": _parse_union,
    "tagged_union": _parse_tagged_union,
}

# Check that all dispatch functions are registered
for node_type in _VALID_COMPOUND_TYPES:
    if node_type not in _dispatch:
        raise AssertionError(
            f"No dispatch function registered for node type {node_type!r}"
        )
