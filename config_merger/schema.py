"""Schema normalization for config-merger.

Converts a raw YAML config dict into a tree of typed SchemaNode objects.
All merge policies, drop prefixes, id fields, and branch structures are
resolved here so the engine receives a fully normalized representation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import (
    InvalidTaggedUnionConfigError,
    SchemaValidationError,
    UnsupportedPolicyError,
)

# ---------------------------------------------------------------------------
# Type constants
# ---------------------------------------------------------------------------

PRIMITIVE_TYPES: frozenset[str] = frozenset(
    {"string", "integer", "float", "boolean", "any"}
)
COMPOUND_TYPES: frozenset[str] = frozenset(
    {"object", "map", "list", "union", "tagged_union"}
)
ALL_TYPES: frozenset[str] = PRIMITIVE_TYPES | COMPOUND_TYPES

# ---------------------------------------------------------------------------
# Schema node dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PrimitiveNode:
    """A leaf node: string, integer, float, boolean, or any.

    Primitives always behave as override regardless of any declared policy.
    """

    type: str  # one of PRIMITIVE_TYPES


@dataclass
class ObjectNode:
    """A fixed-key mapping node.

    `keys` preserves declaration order from the config.
    `id`, when present, is the field name used for identity matching.
    """

    keys: dict[str, SchemaNode]
    merge_policy: str = "append"  # "append" | "override"
    id: str | None = None
    drop_prefix: str = "-"


@dataclass
class MapNode:
    """An arbitrary-key mapping node with a uniform value schema."""

    value: SchemaNode
    merge_policy: str = "append"
    id: str | None = None
    drop_prefix: str = "-"


@dataclass
class ListNode:
    """An ordered list node with a uniform item schema.

    `id`, when present, is the field name in each item used for identity-based
    matching across merge inputs.
    """

    value: SchemaNode
    merge_policy: str = "append"
    id: str | None = None
    drop_prefix: str = "-"


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


def parse_schema(config: Any, path: str = "") -> SchemaNode:
    """Parse and normalise a raw config dict into a SchemaNode tree.

    Args:
        config: Raw dict loaded from YAML (or a sub-section thereof).
        path:   Dot-separated path string used in error messages.

    Returns:
        A fully normalised SchemaNode.

    Raises:
        SchemaValidationError:        Config is structurally invalid.
        UnsupportedPolicyError:       A merge policy is invalid for the type.
        InvalidTaggedUnionConfigError: tagged_union section is malformed.
    """
    if not isinstance(config, dict):
        raise SchemaValidationError(
            f"Schema node must be a mapping, got {type(config).__name__!r}",
            path=path,
        )

    node_type = config.get("type")
    if node_type is None:
        raise SchemaValidationError("Missing required 'type' field", path=path)
    if not isinstance(node_type, str):
        raise SchemaValidationError(
            f"'type' must be a string, got {type(node_type).__name__!r}",
            path=path,
        )
    if node_type not in ALL_TYPES:
        raise SchemaValidationError(
            f"Unknown type {node_type!r}; valid types: {sorted(ALL_TYPES)}",
            path=path,
        )

    if node_type in PRIMITIVE_TYPES:
        return PrimitiveNode(type=node_type)

    dispatch = {
        "object": _parse_object,
        "map": _parse_map,
        "list": _parse_list,
        "union": _parse_union,
        "tagged_union": _parse_tagged_union,
    }
    return dispatch[node_type](config, path)


# ---------------------------------------------------------------------------
# Shared helper parsers
# ---------------------------------------------------------------------------


def _parse_merge_policy(config: dict, path: str, default: str = "append") -> str:
    policy = config.get("merge", default)
    if not isinstance(policy, str):
        raise SchemaValidationError(
            f"'merge' must be a string, got {type(policy).__name__!r}",
            path=path,
        )
    if policy not in ("append", "override"):
        raise SchemaValidationError(
            f"'merge' must be 'append' or 'override', got {policy!r}",
            path=path,
        )
    return policy


def _parse_drop_prefix(config: dict, path: str) -> str:
    prefix = config.get("drop_prefix", "-")
    if not isinstance(prefix, str):
        raise SchemaValidationError(
            f"'drop_prefix' must be a string, got {type(prefix).__name__!r}",
            path=path,
        )
    if not prefix:
        raise SchemaValidationError("'drop_prefix' must not be empty", path=path)
    return prefix


def _parse_id(config: dict, path: str) -> str | None:
    id_field = config.get("id")
    if id_field is None:
        return None
    if not isinstance(id_field, str):
        raise SchemaValidationError(
            f"'id' must be a string, got {type(id_field).__name__!r}",
            path=path,
        )
    return id_field


def _parse_keys(raw_keys: Any, parent_path: str) -> dict[str, SchemaNode]:
    if not isinstance(raw_keys, dict):
        raise SchemaValidationError(
            f"'keys' must be a mapping, got {type(raw_keys).__name__!r}",
            path=parent_path,
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
    drop_prefix = _parse_drop_prefix(config, path)
    keys = _parse_keys(config.get("keys", {}), path)
    return ObjectNode(
        keys=keys,
        merge_policy=merge_policy,
        id=id_field,
        drop_prefix=drop_prefix,
    )


def _parse_map(config: dict, path: str) -> MapNode:
    merge_policy = _parse_merge_policy(config, path)
    id_field = _parse_id(config, path)
    drop_prefix = _parse_drop_prefix(config, path)

    raw_value = config.get("value")
    if raw_value is None:
        raise SchemaValidationError("'map' requires a 'value' schema", path=path)
    value = parse_schema(raw_value, path=f"{path}.value")

    return MapNode(
        value=value,
        merge_policy=merge_policy,
        id=id_field,
        drop_prefix=drop_prefix,
    )


def _parse_list(config: dict, path: str) -> ListNode:
    merge_policy = _parse_merge_policy(config, path)
    id_field = _parse_id(config, path)
    drop_prefix = _parse_drop_prefix(config, path)

    raw_value = config.get("value")
    if raw_value is None:
        raise SchemaValidationError("'list' requires a 'value' schema", path=path)
    value = parse_schema(raw_value, path=f"{path}.value")

    return ListNode(
        value=value,
        merge_policy=merge_policy,
        id=id_field,
        drop_prefix=drop_prefix,
    )


def _parse_union(config: dict, path: str) -> UnionNode:
    merge_policy = _parse_merge_policy(config, path)
    if merge_policy != "override":
        raise UnsupportedPolicyError(merge_policy, "union", path=path)

    raw_value = config.get("value")
    if not isinstance(raw_value, list):
        raise SchemaValidationError(
            f"'union' requires 'value' to be a list of branch schemas, "
            f"got {type(raw_value).__name__!r}",
            path=path,
        )
    if len(raw_value) < 2:
        raise SchemaValidationError(
            f"'union' requires at least two branches, got {len(raw_value)}",
            path=path,
        )

    branches = [
        parse_schema(branch_cfg, path=f"{path}.value[{i}]")
        for i, branch_cfg in enumerate(raw_value)
    ]
    return UnionNode(branches=branches)


def _parse_tagged_union(config: dict, path: str) -> TaggedUnionNode:
    merge_policy = _parse_merge_policy(config, path)
    if merge_policy != "override":
        raise UnsupportedPolicyError(merge_policy, "tagged_union", path=path)

    tag_config = config.get("tag")
    if not isinstance(tag_config, dict):
        raise InvalidTaggedUnionConfigError(
            "tagged_union requires a 'tag' mapping with 'name', 'options', and optional 'keys'",
            path=path,
        )

    # tag.name ---------------------------------------------------------------
    tag_name = tag_config.get("name")
    if not isinstance(tag_name, str):
        raise InvalidTaggedUnionConfigError(
            f"'tag.name' must be a string, got {type(tag_name).__name__!r}",
            path=f"{path}.tag",
        )

    # tag.options ------------------------------------------------------------
    raw_options = tag_config.get("options") or {}
    if not isinstance(raw_options, dict):
        raise InvalidTaggedUnionConfigError(
            f"'tag.options' must be a mapping, got {type(raw_options).__name__!r}",
            path=f"{path}.tag",
        )

    options: dict[str, TaggedUnionBranch] = {}
    for tag_value, option_config in raw_options.items():
        opt_path = f"{path}.tag.options.{tag_value}"
        if option_config is None:
            # Null option: this tag is valid but has no extra fields.
            options[tag_value] = TaggedUnionBranch(extra_keys={})
        elif isinstance(option_config, dict):
            extra_keys = {
                fname: parse_schema(fcfg, path=f"{opt_path}.{fname}")
                for fname, fcfg in option_config.items()
            }
            options[tag_value] = TaggedUnionBranch(extra_keys=extra_keys)
        else:
            raise InvalidTaggedUnionConfigError(
                f"Option {tag_value!r} must be null or a mapping of extra field schemas; "
                f"got {type(option_config).__name__!r}",
                path=opt_path,
            )

    # tag.keys (common fields shared by every variant) -----------------------
    raw_keys = tag_config.get("keys") or {}
    if not isinstance(raw_keys, dict):
        raise InvalidTaggedUnionConfigError(
            f"'tag.keys' must be a mapping, got {type(raw_keys).__name__!r}",
            path=f"{path}.tag",
        )
    common_keys = {
        fname: parse_schema(fcfg, path=f"{path}.tag.keys.{fname}")
        for fname, fcfg in raw_keys.items()
    }

    return TaggedUnionNode(
        tag_field=tag_name,
        common_keys=common_keys,
        options=options,
    )
