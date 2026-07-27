# SPDX-License-Identifier: MPL-2.0

"""Execute normalized overlay operations and construct configuration objects."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Sequence, cast

from .logging import MergeError, OverlayError, logger
from .overlay import (
    ClearOperation,
    MergeOperation,
    Operation,
    RemoveOperation,
    SetOperation,
    TestOperation,
    _validate_value,
)
from .schema import (
    ListNode,
    MapNode,
    ObjectNode,
    PrimitiveNode,
    SchemaNode,
    TaggedUnionNode,
    UnionNode,
)

_MISSING = object()


def create_object(
    schema: SchemaNode,
    operation_groups: Sequence[Sequence[Operation]],
    *,
    initial: Any = _MISSING,
) -> Any:
    """Create a complete object by applying validated overlay groups in order.

    Fixed object fields are present from the start. Fields without a value use
    ``None``; maps and lists start empty. This means an operation can address a
    nested fixed field without first creating each of its parents.

    A supplied initial value is copied and fully validated before any operation
    executes.

    Test operations are handled per overlay. A failed ``drop`` test rolls back
    that overlay, ``skip`` keeps work already performed by it, ``warn`` logs and
    continues, and ``error`` raises :class:`MergeError`.
    """
    if initial is _MISSING:
        result = _empty_value(schema)
    else:
        result = _copy_value(initial)
        try:
            _validate_value(schema, result, ".", None, complete=True)
        except OverlayError as error:
            raise MergeError(
                f"Invalid initial configuration: {error.message}",
                error.location,
            ) from error

    for operations in operation_groups:
        before_overlay = deepcopy(result)
        for operation in operations:
            if isinstance(operation, TestOperation):
                actual = _read_path(result, operation.path)
                if actual is not _MISSING and actual == operation.data:
                    continue

                message = operation.message or _test_failure_message(operation, actual)
                if operation.on_fail == "warn":
                    logger.warning(message)
                    continue
                if operation.on_fail == "skip":
                    break
                if operation.on_fail == "drop":
                    result = before_overlay
                    break
                raise MergeError(message)

            result = _apply_operation(schema, result, operation)

    return result


def _empty_value(node: SchemaNode) -> Any:
    if isinstance(node, ObjectNode):
        return {key: _empty_value(child) for key, child in node.keys.items()}
    if isinstance(node, MapNode):
        return {}
    if isinstance(node, ListNode):
        return []
    if isinstance(node, PrimitiveNode | UnionNode | TaggedUnionNode):
        return None
    raise AssertionError(f"Unhandled schema node: {type(node).__name__}")


def _apply_operation(schema: SchemaNode, root: Any, operation: Operation) -> Any:
    if isinstance(operation, SetOperation):
        return _write_path(schema, root, operation.path, _copy_value(operation.data))
    if isinstance(operation, MergeOperation):
        return _update_path(
            schema,
            root,
            operation.path,
            lambda node, current: _merge_value(node, current, operation.data),
        )
    if isinstance(operation, RemoveOperation):
        return _remove_path(schema, root, operation)
    if isinstance(operation, ClearOperation):
        return _update_path(
            schema,
            root,
            operation.path,
            lambda node, _current: [] if isinstance(node, ListNode) else {},
        )
    raise AssertionError(f"Unhandled operation: {type(operation).__name__}")


def _path_parts(path: str) -> tuple[str, ...]:
    return () if path == "." else tuple(path[1:].split("."))


def _read_path(root: Any, path: str) -> Any:
    current = root
    for part in _path_parts(path):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _write_path(schema: SchemaNode, root: Any, path: str, value: Any) -> Any:
    return _update_path(schema, root, path, lambda _node, _current: value)


def _update_path(
    schema: SchemaNode,
    root: Any,
    path: str,
    update: Callable[[SchemaNode, Any], Any],
) -> Any:
    parts = _path_parts(path)
    if not parts:
        return update(schema, root)

    if root is None:
        root = _empty_value(schema)
    if not isinstance(root, dict):
        raise MergeError(f"Cannot traverse non-mapping value at {path!r}")

    result = dict(root)
    current = result
    node = schema
    traversed: list[str] = []

    for part in parts[:-1]:
        traversed.append(part)
        child_schema = _child_schema(node, part)
        child = current.get(part, _MISSING)
        if child is _MISSING or child is None:
            child = _empty_value(child_schema)
        elif not isinstance(child, dict):
            parent_path = "." + ".".join(traversed)
            raise MergeError(f"Cannot traverse non-mapping value at {parent_path!r}")
        else:
            child = dict(child)
        current[part] = child
        current = child
        node = child_schema

    leaf = parts[-1]
    leaf_schema = _child_schema(node, leaf)
    current[leaf] = update(leaf_schema, current.get(leaf, _MISSING))
    return result


def _remove_path(
    schema: SchemaNode,
    root: Any,
    operation: RemoveOperation,
) -> Any:
    parts = _path_parts(operation.path)
    if not parts:
        raise MergeError("The root object cannot be removed")

    if not isinstance(root, dict):
        return root

    result = dict(root)
    current = result
    node = schema
    for part in parts[:-1]:
        child = current.get(part, _MISSING)
        if child is _MISSING or not isinstance(child, dict):
            return result
        child = dict(child)
        current[part] = child
        current = child
        node = _child_schema(node, part)

    key = parts[-1]
    if operation.mode == "delete":
        current.pop(key, None)
    else:
        current[key] = None
    return result


def _child_schema(node: SchemaNode, key: str) -> SchemaNode:
    if isinstance(node, ObjectNode):
        try:
            return node.keys[key]
        except KeyError as error:  # MergePlan can be instantiated directly.
            raise MergeError(f"Unknown object field {key!r}") from error
    if isinstance(node, MapNode):
        return node.value
    raise MergeError(f"Cannot traverse schema node {type(node).__name__}")


def _merge_value(node: SchemaNode, current: Any, incoming: Any) -> Any:
    if isinstance(node, ObjectNode):
        return _merge_object(node, current, incoming)
    if isinstance(node, MapNode):
        return _merge_map(node, current, incoming)
    if isinstance(node, ListNode):
        return _merge_list(node, current, incoming)

    # Overlay validation only permits merge on compound nodes. Keeping this
    # fallback makes direct MergePlan construction deterministic as well.
    return deepcopy(incoming)


def _merge_object(node: ObjectNode, current: Any, incoming: Any) -> dict[str, Any]:
    if not isinstance(incoming, dict):
        raise MergeError("Object merge data must be a mapping")

    if node.merge_policy == "override":
        return _copy_value(incoming)

    if current is _MISSING or current is None:
        result = _empty_value(node)
    elif isinstance(current, dict):
        result = dict(current)
    else:
        raise MergeError("Cannot merge an object into a non-mapping value")

    if node.id is not None:
        old_id = result.get(node.id)
        new_id = incoming.get(node.id)
        if old_id is not None and new_id is not None and old_id != new_id:
            raise MergeError(
                f"Cannot merge objects with conflicting {node.id!r} identities: "
                f"{old_id!r} and {new_id!r}"
            )

    for key, value in incoming.items():
        child = node.keys.get(key)
        if child is None:
            raise MergeError(f"Unknown object field {key!r}")
        result[key] = _merge_value(child, result.get(key, _MISSING), value)
    return result


def _merge_map(node: MapNode, current: Any, incoming: Any) -> dict[str, Any]:
    if not isinstance(incoming, dict):
        raise MergeError("Map merge data must be a mapping")

    if node.merge_policy == "override":
        return _copy_value(incoming)

    if current is _MISSING or current is None:
        result: dict[str, Any] = {}
    elif isinstance(current, dict):
        result = dict(current)
    else:
        raise MergeError("Cannot merge a map into a non-mapping value")

    for key, value in incoming.items():
        result[key] = _merge_value(node.value, result.get(key, _MISSING), value)
    return result


def _merge_list(node: ListNode, current: Any, incoming: Any) -> list[Any]:
    if not isinstance(incoming, list):
        raise MergeError("List merge data must be a list")

    if node.merge_policy == "override":
        return _copy_value(incoming)

    if current is _MISSING or current is None:
        result: list[Any] = []
    elif isinstance(current, list):
        result = list(current)
    else:
        raise MergeError("Cannot merge a list into a non-list value")

    id_field = node.id
    if id_field is None:
        result.extend(_copy_value(incoming))
        return result

    for item in incoming:
        if not isinstance(item, dict) or id_field not in item:
            raise MergeError(f"List item is missing identity field {id_field!r}")
        identity = item[id_field]
        match = next(
            (
                position
                for position, existing in enumerate(result)
                if _has_identity(existing, id_field, identity)
            ),
            None,
        )
        if match is None:
            result.append(_copy_value(item))
        else:
            result[match] = _merge_value(node.value, result[match], item)
    return result


def _has_identity(value: Any, id_field: str, identity: Any) -> bool:
    if not isinstance(value, dict):
        return False
    item = cast(dict[str, Any], value)
    return id_field in item and item[id_field] == identity


def _copy_value(value: Any) -> Any:
    """Copy YAML data while stripping source-location container subclasses."""
    if isinstance(value, dict):
        return {_copy_value(key): _copy_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    return deepcopy(value)


def _test_failure_message(operation: TestOperation, actual: Any) -> str:
    rendered_actual = "<missing>" if actual is _MISSING else repr(actual)
    return (
        f"Test failed at {operation.path!r} in overlay {operation.overlay!r}: "
        f"expected {operation.data!r}, got {rendered_actual}"
    )
