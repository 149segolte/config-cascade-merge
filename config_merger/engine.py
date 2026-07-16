"""Deterministic merge engine for config-merger.

Walks the normalised schema tree and merges an ordered sequence of input dicts
left-to-right.  The caller-facing entry point is `merge()`.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

from .errors import (
    AmbiguousUnionError,
    MergeConflictError,
    MergeError,
    MissingRequiredIdError,
    TypeMismatchError,
    UnknownUnionTagError,
)
from .schema import (
    ListNode,
    MapNode,
    ObjectNode,
    PrimitiveNode,
    SchemaNode,
    TaggedUnionNode,
    UnionNode,
    parse_schema,
)

# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def merge(config: dict, iter: Iterable[dict]) -> dict:
    """Merge an ordered iterable of dicts according to the schema *config*.

    Args:
        config: Raw YAML schema dict (same format as ``example_config.yaml``).
        iter:   Ordered iterable of data dicts to merge left-to-right.

    Returns:
        The merged result dict.  Returns ``{}`` when *iter* is empty.

    Raises:
        SchemaValidationError: The config schema is structurally invalid.
        MergeError:            A merge rule is violated during execution.
    """
    schema = parse_schema(config)
    items = list(iter)  # materialise once; never re-iterate

    if not items:
        return {}

    acc: Any = None
    for item in items:
        acc = merge_node(schema, acc, item, path="")

    return acc if acc is not None else {}


# ---------------------------------------------------------------------------
# Core recursive dispatcher
# ---------------------------------------------------------------------------


def merge_node(schema: SchemaNode, acc: Any, incoming: Any, path: str) -> Any:
    """Recursively merge *incoming* into *acc* according to *schema*.

    ``None`` in *incoming* is treated as absent – the accumulator is returned
    unchanged.  ``None`` in *acc* means no prior value exists for this node.

    Args:
        schema:   Normalised schema node governing this merge step.
        acc:      Current accumulated value (``None`` if no prior value).
        incoming: New value to merge in.
        path:     Dot-path context string used in error messages.

    Returns:
        The merged value.
    """
    if incoming is None:
        return acc

    if isinstance(schema, PrimitiveNode):
        return _merge_primitive(schema, acc, incoming, path)
    if isinstance(schema, ObjectNode):
        return _merge_object(schema, acc, incoming, path)
    if isinstance(schema, MapNode):
        return _merge_map(schema, acc, incoming, path)
    if isinstance(schema, ListNode):
        return _merge_list(schema, acc, incoming, path)
    if isinstance(schema, UnionNode):
        return _merge_union(schema, acc, incoming, path)
    if isinstance(schema, TaggedUnionNode):
        return _merge_tagged_union(schema, acc, incoming, path)

    raise MergeError(  # pragma: no cover
        f"Unknown schema node type: {type(schema).__name__!r}", path=path
    )


# ---------------------------------------------------------------------------
# Per-type merge implementations
# ---------------------------------------------------------------------------


def _merge_primitive(schema: PrimitiveNode, acc: Any, incoming: Any, path: str) -> Any:
    """Primitives always override: the newest non-None value wins."""
    _validate_primitive(schema.type, incoming, path)
    # Deep-copy 'any' values to avoid sharing mutable structures.
    return copy.deepcopy(incoming) if schema.type == "any" else incoming


def _validate_primitive(ptype: str, value: Any, path: str) -> None:
    if ptype == "any":
        return
    if ptype == "string":
        if not isinstance(value, str):
            raise TypeMismatchError("string", type(value), path=path)
    elif ptype == "integer":
        # bool is a subclass of int in Python – exclude it explicitly.
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeMismatchError("integer", type(value), path=path)
    elif ptype == "float":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeMismatchError("float", type(value), path=path)
    elif ptype == "boolean":
        if not isinstance(value, bool):
            raise TypeMismatchError("boolean", type(value), path=path)


def _merge_object(schema: ObjectNode, acc: Any, incoming: Any, path: str) -> dict:
    if not isinstance(incoming, dict):
        raise TypeMismatchError("object (dict)", type(incoming), path=path)

    if acc is None:
        acc = {}
    elif not isinstance(acc, dict):
        raise TypeMismatchError("object (dict)", type(acc), path=f"{path}[acc]")

    # Identity guard: if both sides declare the id field, they must agree.
    if schema.id is not None:
        acc_id = acc.get(schema.id)
        inc_id = incoming.get(schema.id)
        if acc_id is not None and inc_id is not None and acc_id != inc_id:
            raise MergeConflictError(schema.id, acc_id, inc_id, path=path)

    if schema.merge_policy == "override":
        result: dict[str, Any] = {}
        for key, key_schema in schema.keys.items():
            if key in incoming:
                child_path = f"{path}.{key}" if path else key
                merged = merge_node(key_schema, None, incoming[key], child_path)
                if merged is not None:
                    result[key] = merged
        return result

    # ---- append policy ----
    result = dict(acc)

    for key, key_schema in schema.keys.items():
        drop_key = schema.drop_prefix + key
        if drop_key in incoming:
            # Presence of the drop key (any value, even None) removes the field.
            result.pop(key, None)
        elif key in incoming:
            child_path = f"{path}.{key}" if path else key
            merged = merge_node(key_schema, result.get(key), incoming[key], child_path)
            if merged is not None:
                result[key] = merged
            elif key in result:
                # If the merged result is None but the key existed in acc, keep it.
                pass  # result[key] already holds the acc value

    return result


def _merge_map(schema: MapNode, acc: Any, incoming: Any, path: str) -> dict:
    if not isinstance(incoming, dict):
        raise TypeMismatchError("map (dict)", type(incoming), path=path)

    if acc is None:
        acc = {}
    elif not isinstance(acc, dict):
        raise TypeMismatchError("map (dict)", type(acc), path=f"{path}[acc]")

    if schema.merge_policy == "override":
        result: dict[str, Any] = {}
        for key, value in incoming.items():
            if value is not None:
                child_path = f"{path}.{key}" if path else key
                result[key] = merge_node(schema.value, None, value, child_path)
        return result

    # ---- append policy ----
    result = dict(acc)

    for key, value in incoming.items():
        if value is None:
            continue  # None == absent
        child_path = f"{path}.{key}" if path else key
        if key.startswith(schema.drop_prefix) and len(key) > len(schema.drop_prefix):
            actual_key = key[len(schema.drop_prefix) :]
            result.pop(actual_key, None)
        else:
            result[key] = merge_node(schema.value, result.get(key), value, child_path)

    return result


def _merge_list(schema: ListNode, acc: Any, incoming: Any, path: str) -> list:
    if not isinstance(incoming, list):
        raise TypeMismatchError("list", type(incoming), path=path)

    if acc is None:
        acc = []
    elif not isinstance(acc, list):
        raise TypeMismatchError("list", type(acc), path=f"{path}[acc]")

    if schema.merge_policy == "override":
        result: list[Any] = []
        for i, item in enumerate(incoming):
            if item is not None:
                result.append(merge_node(schema.value, None, item, f"{path}[{i}]"))
        return result

    # ---- append policy ----
    result = list(acc)

    if schema.id is not None:
        id_field = schema.id
        # Build index: id_value -> position in result list.
        index: dict[Any, int] = _build_list_index(result, id_field, path)

        for j, item in enumerate(incoming):
            if item is None:
                continue
            if not isinstance(item, dict):
                raise TypeMismatchError(
                    "dict (list item)", type(item), path=f"{path}[{j}]"
                )
            if id_field not in item:
                raise MissingRequiredIdError(id_field, path=f"{path}[{j}]")

            id_value = item[id_field]

            # Check for drop prefix on the id value.
            if (
                isinstance(id_value, str)
                and id_value.startswith(schema.drop_prefix)
                and len(id_value) > len(schema.drop_prefix)
            ):
                actual_id = id_value[len(schema.drop_prefix) :]
                if actual_id in index:
                    result.pop(index[actual_id])
                    # Rebuild index after in-place removal.
                    index = _build_list_index(result, id_field, path)
                # The removal entry itself is not added to the list.
            elif id_value in index:
                # Merge into the matching existing item.
                pos = index[id_value]
                item_path = f"{path}[{id_field}={id_value!r}]"
                result[pos] = merge_node(schema.value, result[pos], item, item_path)
            else:
                # New identity – validate and append.
                item_path = f"{path}[{id_field}={id_value!r}]"
                validated = merge_node(schema.value, None, item, item_path)
                index[id_value] = len(result)
                result.append(validated)
    else:
        # No id: all incoming items are appended as distinct entries.
        for j, item in enumerate(incoming):
            if item is not None:
                item_path = f"{path}[{len(result)}]"
                result.append(merge_node(schema.value, None, item, item_path))

    return result


def _build_list_index(items: list[Any], id_field: str, path: str) -> dict[Any, int]:
    """Build a {id_value: position} mapping for identity-based list merging."""
    index: dict[Any, int] = {}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise TypeMismatchError("dict (list item)", type(item), path=f"{path}[{i}]")
        if id_field not in item:
            raise MissingRequiredIdError(id_field, path=f"{path}[{i}]")
        index[item[id_field]] = i
    return index


def _merge_union(schema: UnionNode, acc: Any, incoming: Any, path: str) -> Any:
    """Select exactly one union branch; union is always override."""
    matching = [b for b in schema.branches if _can_match(b, incoming)]

    if not matching:
        raise MergeError(
            f"No union branch matches value of type {type(incoming).__name__!r}",
            path=path,
        )
    if len(matching) > 1:
        raise AmbiguousUnionError(len(matching), path=path)

    # Override: validate against the matched branch, ignore acc.
    return merge_node(matching[0], None, incoming, path)


def _merge_tagged_union(
    schema: TaggedUnionNode, acc: Any, incoming: Any, path: str
) -> dict:
    """Dispatch on tag field; tagged_union is always override."""
    if not isinstance(incoming, dict):
        raise TypeMismatchError("tagged_union (dict)", type(incoming), path=path)

    if schema.tag_field not in incoming:
        raise UnknownUnionTagError(
            schema.tag_field, None, list(schema.options.keys()), path=path
        )

    tag_value = incoming[schema.tag_field]
    if tag_value not in schema.options:
        raise UnknownUnionTagError(
            schema.tag_field, tag_value, list(schema.options.keys()), path=path
        )

    branch = schema.options[tag_value]

    # Override: build a fresh result from the incoming value only.
    result: dict[str, Any] = {schema.tag_field: tag_value}

    for key, key_schema in schema.common_keys.items():
        if key in incoming:
            child_path = f"{path}.{key}" if path else key
            merged = merge_node(key_schema, None, incoming[key], child_path)
            if merged is not None:
                result[key] = merged

    for key, key_schema in branch.extra_keys.items():
        if key in incoming:
            child_path = f"{path}.{key}" if path else key
            merged = merge_node(key_schema, None, incoming[key], child_path)
            if merged is not None:
                result[key] = merged

    return result


# ---------------------------------------------------------------------------
# Union branch matching helpers
# ---------------------------------------------------------------------------


def _can_match(schema: SchemaNode, value: Any) -> bool:
    """Return True if *value* structurally matches the schema node."""
    if isinstance(schema, PrimitiveNode):
        return _matches_primitive(schema.type, value)
    if isinstance(schema, (ObjectNode, MapNode)):
        return isinstance(value, dict)
    if isinstance(schema, ListNode):
        return isinstance(value, list)
    if isinstance(schema, UnionNode):
        # A union matches if exactly one of its branches matches.
        return sum(_can_match(b, value) for b in schema.branches) == 1
    if isinstance(schema, TaggedUnionNode):
        return isinstance(value, dict) and schema.tag_field in value
    return False  # pragma: no cover


def _matches_primitive(ptype: str, value: Any) -> bool:
    if ptype == "any":
        return True
    if ptype == "string":
        return isinstance(value, str)
    if ptype == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if ptype == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if ptype == "boolean":
        return isinstance(value, bool)
    return False
