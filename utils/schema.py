"""Schema normalization for config-merger.

Converts a raw YAML config dict into a tree of typed SchemaNode objects.
All merge policies, drop prefixes, id fields, and branch structures are
resolved here so the engine receives a fully normalized representation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, cast, get_args

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
_dispatch: dict[COMPOUND_TYPES, Callable[[Any, str], SchemaNode]] = {}


def parse_schema(config: Any, path: str = "") -> SchemaNode:
    """Parse and normalise a raw config dict into a SchemaNode tree.

    Args:
        config: Raw dict loaded from YAML (or a sub-section thereof).
        path:   Dot-separated path string used in error messages.

    Returns:
        A fully normalised SchemaNode.

    Raises:
        TypeError:        Input data does not match the any expected type.
        ValueError:       Input data does not match the expected schema for this type.
    """
    if not isinstance(config, dict):
        raise TypeError(
            f"Schema node must be a mapping, got {type(config).__name__!r} at `{path or '.'}`"
        )

    node_type = config.get("type")
    if node_type is None:
        raise TypeError(f"Missing required 'type' string field at `{path or '.'}`")
    if not isinstance(node_type, str):
        raise TypeError(
            f"'type' must be a string, got {type(node_type).__name__!r} at `{path}.type`"
        )
    if node_type not in _VALID_TYPES:
        raise ValueError(
            f"Unknown type string {node_type!r} at `{path}.type`; valid types: {_VALID_TYPES}"
        )

    if node_type in _VALID_PRIMITIVE_TYPES:
        return PrimitiveNode(type=cast(PRIMITIVE_TYPES, node_type))

    return _dispatch[cast(COMPOUND_TYPES, node_type)](config, path)


# ---------------------------------------------------------------------------
# Shared helper parsers
# ---------------------------------------------------------------------------


def _parse_merge_policy(
    config: dict, path: str, default: MERGE_POLICIES = "append"
) -> MERGE_POLICIES:
    policy = config.get("merge")
    if policy is None:
        return default

    if not isinstance(policy, str):
        raise TypeError(
            f"'merge' must be a string, got {type(policy).__name__!r} at `{path}.merge`"
        )
    if policy not in _VALID_MERGE_POLICIES:
        raise ValueError(
            f"'merge' must be one of {_VALID_MERGE_POLICIES}, got {policy!r} at `{path}.merge`"
        )
    return cast(MERGE_POLICIES, policy)


def _parse_id(config: dict, path: str) -> str | None:
    id_field = config.get("id")
    if id_field is None:
        return None

    if not isinstance(id_field, str):
        raise TypeError(
            f"'id' must be a string, got {type(id_field).__name__!r} at `{path}.id`"
        )
    if id_field == "":
        raise ValueError(
            f"if provided 'id' must not be empty, got {id_field!r} at `{path}.id`"
        )
    return id_field


def _parse_keys(config: dict, parent_path: str) -> dict[str, SchemaNode]:
    raw_keys = config.get("keys")
    if raw_keys is None:
        return {}

    if not isinstance(raw_keys, dict):
        raise TypeError(
            f"'keys' must be a mapping, got {type(raw_keys).__name__!r} at `{parent_path}.keys`"
        )
    return {
        name: parse_schema(sub, path=f"{parent_path}.keys.{name}")
        for name, sub in raw_keys.items()
    }


# ---------------------------------------------------------------------------
# Per-type parsers
# ---------------------------------------------------------------------------


def _parse_object(config: dict, path: str) -> ObjectNode:
    merge_policy = _parse_merge_policy(config, path)
    id_field = _parse_id(config, path)
    keys = _parse_keys(config, path)
    return ObjectNode(
        keys=keys,
        merge_policy=merge_policy,
        id=id_field,
    )


def _parse_map(config: dict, path: str) -> MapNode:
    merge_policy = _parse_merge_policy(config, path)
    id_field = _parse_id(config, path)

    raw_value = config.get("value")
    if raw_value is None:
        raise TypeError(f"'map' requires a 'value' schema at `{path or '.'}`")
    value = parse_schema(raw_value, path=f"{path}.value")

    return MapNode(
        value=value,
        merge_policy=merge_policy,
        id=id_field,
    )


def _parse_list(config: dict, path: str) -> ListNode:
    merge_policy = _parse_merge_policy(config, path)
    id_field = _parse_id(config, path)

    raw_value = config.get("value")
    if raw_value is None:
        raise TypeError(f"'list' requires a 'value' schema at `{path or '.'}`")
    value = parse_schema(raw_value, path=f"{path}.value")

    return ListNode(
        value=value,
        merge_policy=merge_policy,
        id=id_field,
    )


def _parse_union(config: dict, path: str) -> UnionNode:
    raw_value = config.get("value")
    if raw_value is None:
        raise TypeError(
            f"'union' requires a 'value' to be a list of branch schemas at `{path or '.'}`"
        )

    if not isinstance(raw_value, list):
        raise TypeError(
            f"'union' requires a 'value' to be a list of branch schemas, got {type(raw_value).__name__!r} at `{path}.value`"
        )
    if len(raw_value) < 2:
        raise ValueError(
            f"'union' requires at least two branches, got {len(raw_value)} at: {path}"
        )

    branches = [
        parse_schema(branch_cfg, path=f"{path}.value[{i}]")
        for i, branch_cfg in enumerate(raw_value)
    ]
    return UnionNode(branches=branches)


def _parse_tagged_union(config: dict, path: str) -> TaggedUnionNode:
    tag_config = config.get("tag")
    if tag_config is None:
        raise TypeError(f"tagged_union requires a 'tag' mapping at `{path or '.'}`")

    if not isinstance(tag_config, dict):
        raise TypeError(
            f"tagged_union requires a 'tag' mapping with 'name', 'options', and optional 'keys' at `{path}.tag`"
        )

    # tag.name ---------------------------------------------------------------
    tag_name = tag_config.get("name")
    if not isinstance(tag_name, str):
        raise TypeError(
            f"'name' must be a string, got {type(tag_name).__name__!r} at `{path}.tag.name`"
        )

    # tag.keys (common fields shared by every variant) -----------------------
    raw_keys = tag_config.get("keys") or {}
    if not isinstance(raw_keys, dict):
        raise TypeError(
            f"'keys' must be a mapping, got {type(raw_keys).__name__!r} at `{path}.tag.keys`"
        )
    common_keys = {
        name: parse_schema(type, path=f"{path}.tag.keys.{name}")
        for name, type in raw_keys.items()
    }

    # tag.options ------------------------------------------------------------
    raw_options = tag_config.get("options") or {}
    if not isinstance(raw_options, dict):
        raise TypeError(
            f"'options' must be a mapping, got {type(raw_options).__name__!r} at `{path}.tag.options`"
        )

    options: dict[str, TaggedUnionBranch] = {}
    for tag_value, option_config in raw_options.items():
        opt_path = f"{path}.tag.options.{tag_value}"
        if option_config is None:
            # Null option: this tag is valid but has no extra fields.
            options[tag_value] = TaggedUnionBranch(extra_keys={})
        elif isinstance(option_config, dict):
            extra_keys = {
                name: parse_schema(type, path=f"{opt_path}.{name}")
                for name, type in option_config.items()
            }
            for keys in extra_keys.keys():
                if keys in common_keys:
                    raise ValueError(
                        f"Extra key {keys!r} is also present in common_keys at `{opt_path}`"
                    )
            options[tag_value] = TaggedUnionBranch(extra_keys=extra_keys)
        else:
            raise TypeError(
                f"Option {tag_value!r} must be null or a mapping of extra field schemas; got {type(option_config).__name__!r} at `{opt_path}`"
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
