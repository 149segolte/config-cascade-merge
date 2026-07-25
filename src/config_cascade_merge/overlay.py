# SPDX-License-Identifier: MPL-2.0

"""Load and validate overlay operations against a normalized schema.

Overlay validation is intentionally concerned with whether each operation can
be applied to the schema, not whether operations touch the same path. Overlay
operations are ordered, so later operations may legitimately replace or amend
values written by earlier operations.

Example::

    name: workstation
    operations:
      - action: merge
        path: .environment.packages
        data:
          - {kind: brew, name: ripgrep, shell: rg}
      - action: test
        path: .data.user.name
        data: alice
        on_fail: warn
        message: unexpected user
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeAlias, cast

import yaml

from .logging import OverlayError, logger
from .schema import (
    ListNode,
    MapNode,
    ObjectNode,
    PrimitiveNode,
    SchemaNode,
    TaggedUnionNode,
    UnionNode,
)
from .yaml_loader import (
    SourceLocation,
    field_location,
    item_location,
    load_yaml,
    node_location,
)

Action = Literal["set", "remove", "merge", "test", "clear"]
TestFailureAction = Literal["drop", "skip", "warn", "error"]
RemoveMode = Literal["null", "delete"]

_VALID_ACTIONS = ("set", "remove", "merge", "test", "clear")
_VALID_TEST_FAILURE_ACTIONS = ("drop", "skip", "warn", "error")
_MISSING = object()


@dataclass(frozen=True)
class SetOperation:
    """Create or replace the value at ``path``."""

    action: Literal["set"]
    path: str
    data: Any
    overlay: str
    source: str | None = None


@dataclass(frozen=True)
class RemoveOperation:
    """Remove a map entry or null a fixed object field.

    ``mode`` is normalized from the parent schema so the execution engine does
    not need to resolve the schema again. ``null`` applies to fixed object
    fields and ``delete`` applies to arbitrary map entries.
    """

    action: Literal["remove"]
    path: str
    mode: RemoveMode
    overlay: str
    source: str | None = None


@dataclass(frozen=True)
class MergeOperation:
    """Recursively merge data according to the target schema's policies."""

    action: Literal["merge"]
    path: str
    data: Any
    overlay: str
    source: str | None = None


@dataclass(frozen=True)
class TestOperation:
    """Test that the value at ``path`` equals ``data`` before proceeding.

    On failure, ``drop`` discards every operation from this overlay, ``skip``
    keeps prior operations but skips the rest, ``warn`` reports ``message`` and
    continues, and ``error`` stops execution.
    """

    action: Literal["test"]
    path: str
    data: Any
    on_fail: TestFailureAction
    overlay: str
    message: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class ClearOperation:
    """Remove every entry from a map or list."""

    action: Literal["clear"]
    path: str
    overlay: str
    source: str | None = None


Operation: TypeAlias = (
    SetOperation | RemoveOperation | MergeOperation | TestOperation | ClearOperation
)


def parse_overlay(
    document: Any,
    schema: SchemaNode,
    *,
    file_name: str | Path | None = None,
) -> list[Operation]:
    """Validate one loaded overlay document and return ordered operations."""
    fallback = SourceLocation(str(file_name), 1) if file_name is not None else None
    location = node_location(document, fallback)
    if not isinstance(document, dict):
        raise OverlayError("Overlay document must be a mapping", location)

    name = document.get("name")
    if not isinstance(name, str) or not name.strip():
        raise OverlayError(
            "Overlay requires a non-empty 'name' string",
            field_location(document, "name", location),
        )

    raw_operations = document.get("operations")
    operations_location = field_location(document, "operations", location)
    if not isinstance(raw_operations, list):
        raise OverlayError("'operations' must be a list", operations_location)

    source = str(file_name) if file_name is not None else None
    operations: list[Operation] = []
    last_set_by_path: dict[str, SetOperation] = {}
    for index, raw_operation in enumerate(raw_operations):
        operation = _parse_operation(
            raw_operation,
            schema,
            name,
            source,
            item_location(raw_operations, index, operations_location),
        )
        if isinstance(operation, SetOperation):
            previous = last_set_by_path.get(operation.path)
            if previous is not None:
                logger.debug(
                    "Overlay %r replaces an earlier set value at %s",
                    name,
                    operation.path,
                )
            last_set_by_path[operation.path] = operation
        operations.append(operation)

    return operations


def load_overlays(
    overlays: str | Path | Sequence[str | Path],
    schema: SchemaNode,
) -> list[Operation]:
    """Load overlay files into one ordered operation list.

    A directory is scanned for ``.yaml``/``.yml`` files in lexical filename
    order. When a sequence of paths is provided, only those files are loaded
    and their given order is preserved. Operations are never deduplicated:
    ordering is meaningful and later operations may overwrite earlier ones.
    """
    if isinstance(overlays, (str, Path)):
        directory = Path(overlays)
        if not directory.is_dir():
            raise OverlayError(f"Overlay directory does not exist: {directory}")

        files = sorted(
            (
                path
                for path in directory.iterdir()
                if path.suffix.lower() in {".yaml", ".yml"}
            ),
            key=lambda path: path.name,
        )
    else:
        files = [Path(path) for path in overlays]

    result: list[Operation] = []
    last_set_by_path: dict[str, SetOperation] = {}

    for path in files:
        try:
            document = load_yaml(path.read_text(encoding="utf-8"), file_name=path)
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            raise OverlayError(
                f"Could not read overlay: {error}", SourceLocation(str(path))
            ) from error
        if document is None:
            raise OverlayError(
                "Overlay document is empty", SourceLocation(str(path), 1)
            )

        operations = parse_overlay(document, schema, file_name=path)
        for operation in operations:
            if isinstance(operation, SetOperation):
                previous = last_set_by_path.get(operation.path)
                if previous is not None and previous.overlay != operation.overlay:
                    logger.debug(
                        "Overlay %r replaces a set value at %s from overlay %r",
                        operation.overlay,
                        operation.path,
                        previous.overlay,
                    )
                last_set_by_path[operation.path] = operation
        result.extend(operations)

    return result


def _parse_operation(
    raw: Any,
    schema: SchemaNode,
    overlay_name: str,
    source: str | None,
    location: SourceLocation | None,
) -> Operation:
    if not isinstance(raw, dict):
        raise OverlayError(
            "Each operation must be a mapping", node_location(raw, location)
        )

    action = raw.get("action")
    action_location = field_location(raw, "action", location)
    if action not in _VALID_ACTIONS:
        raise OverlayError(
            f"'action' must be one of {_VALID_ACTIONS}, got {action!r}",
            action_location,
        )

    path = raw.get("path")
    path_location = field_location(raw, "path", location)
    if not isinstance(path, str):
        raise OverlayError(
            "'path' must be a dot path such as '.environment.packages'",
            path_location,
        )
    parts = _parse_path(path, path_location)
    target = _resolve_path(schema, parts, path, path_location)

    if action == "set":
        _check_fields(raw, {"action", "path", "data"}, location)
        data = _required_data(raw, location)
        _validate_value(
            target, data, path, field_location(raw, "data", location), complete=True
        )
        return SetOperation("set", path, data, overlay_name, source)

    if action == "remove":
        _check_fields(raw, {"action", "path"}, location)
        if not parts:
            raise OverlayError(
                "'remove' requires a full key path; the root cannot be removed",
                path_location,
            )
        parent = _resolve_path(schema, parts[:-1], path, path_location)
        if isinstance(parent, ObjectNode):
            mode: RemoveMode = "null"
        elif isinstance(parent, MapNode):
            mode = "delete"
        else:
            raise OverlayError(
                "'remove' path must identify a fixed object field or dynamic map entry",
                path_location,
            )
        return RemoveOperation("remove", path, mode, overlay_name, source)

    if action == "merge":
        _check_fields(raw, {"action", "path", "data"}, location)
        if not isinstance(target, ObjectNode | MapNode | ListNode):
            raise OverlayError(
                "'merge' can only target an object, map, or list", path_location
            )
        data = _required_data(raw, location)
        _validate_merge_value(target, data, path, field_location(raw, "data", location))
        return MergeOperation("merge", path, data, overlay_name, source)

    if action == "test":
        _check_fields(raw, {"action", "path", "data", "on_fail", "message"}, location)
        data = _required_data(raw, location)
        # Null is a valid observable state after removing a fixed object field.
        if data is not None:
            _validate_value(
                target, data, path, field_location(raw, "data", location), complete=True
            )
        on_fail = raw.get("on_fail", "error")
        if on_fail not in _VALID_TEST_FAILURE_ACTIONS:
            raise OverlayError(
                f"'on_fail' must be one of {_VALID_TEST_FAILURE_ACTIONS}, got {on_fail!r}",
                field_location(raw, "on_fail", location),
            )
        message = raw.get("message")
        if message is not None and not isinstance(message, str):
            raise OverlayError(
                "'message' must be a string", field_location(raw, "message", location)
            )
        return TestOperation(
            "test",
            path,
            data,
            cast(TestFailureAction, on_fail),
            overlay_name,
            message,
            source,
        )

    if action == "clear":
        _check_fields(raw, {"action", "path"}, location)
        if not isinstance(target, MapNode | ListNode):
            raise OverlayError("'clear' can only target a map or list", path_location)
        return ClearOperation("clear", path, overlay_name, source)

    raise AssertionError(f"Unhandled action: {action}")


def _check_fields(
    raw: dict, allowed: set[str], location: SourceLocation | None
) -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise OverlayError(
            f"Unknown field(s) for action {raw.get('action')!r}: "
            f"{', '.join(sorted(map(str, unknown)))}",
            location,
        )


def _required_data(raw: dict, location: SourceLocation | None) -> Any:
    data = raw.get("data", _MISSING)
    if data is _MISSING:
        raise OverlayError(
            f"Action {raw.get('action')!r} requires a 'data' field",
            field_location(raw, "data", location),
        )
    return data


def _parse_path(path: str, location: SourceLocation | None) -> tuple[str, ...]:
    if not path.startswith("."):
        raise OverlayError(
            "'path' must be a dot path such as '.environment.packages'", location
        )
    if path == ".":
        return ()
    parts = path[1:].split(".")
    if any(not part for part in parts):
        raise OverlayError(
            f"Invalid path {path!r}: path segments may not be empty", location
        )
    return tuple(parts)


def _resolve_path(
    schema: SchemaNode,
    parts: tuple[str, ...],
    original_path: str,
    location: SourceLocation | None,
) -> SchemaNode:
    node = schema
    traversed: list[str] = []
    for part in parts:
        traversed.append(part)
        if isinstance(node, ObjectNode):
            if part not in node.keys:
                raise OverlayError(
                    f"Unknown config path {original_path!r}; "
                    f"{'.' + '.'.join(traversed)!r} is not declared",
                    location,
                )
            node = node.keys[part]
        elif isinstance(node, MapNode):
            node = node.value
        else:
            parent_path = "." if len(traversed) == 1 else "." + ".".join(traversed[:-1])
            raise OverlayError(
                f"Cannot traverse through {type(node).__name__} at {parent_path!r}",
                location,
            )
    return node


def _validate_merge_value(
    node: SchemaNode,
    value: Any,
    path: str,
    location: SourceLocation | None,
) -> None:
    """Validate a recursive merge payload according to node merge policies."""
    if isinstance(node, ObjectNode):
        _validate_object(
            node,
            value,
            path,
            location,
            complete=node.merge_policy == "override",
            merge=True,
        )
        return
    if isinstance(node, MapNode):
        _validate_map(node, value, path, location, merge=True)
        return
    if isinstance(node, ListNode):
        if not isinstance(value, list):
            raise OverlayError(f"Merge data at {path!r} must be a list", location)
        for index, item in enumerate(value):
            # Each incoming list member must itself be a valid value. Whether it
            # appends or identity-merges is decided by the list policy and id.
            _validate_value(
                node.value, item, f"{path}[{index}]", location, complete=True
            )
        return
    _validate_value(node, value, path, location, complete=True)


def _validate_value(
    node: SchemaNode,
    value: Any,
    path: str,
    location: SourceLocation | None,
    *,
    complete: bool,
) -> None:
    if isinstance(node, PrimitiveNode):
        valid = {
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: (
                isinstance(item, int) and not isinstance(item, bool)
            ),
            "float": lambda item: (
                isinstance(item, int | float) and not isinstance(item, bool)
            ),
            "boolean": lambda item: isinstance(item, bool),
            "any": lambda item: True,
        }[node.type](value)
        if not valid:
            raise OverlayError(
                f"Data at {path!r} must be {node.type}, got {type(value).__name__}",
                location,
            )
        return
    if isinstance(node, ObjectNode):
        _validate_object(node, value, path, location, complete=complete, merge=False)
        return
    if isinstance(node, MapNode):
        _validate_map(node, value, path, location, merge=False)
        return
    if isinstance(node, ListNode):
        if not isinstance(value, list):
            raise OverlayError(f"Data at {path!r} must be a list", location)
        for index, item in enumerate(value):
            _validate_value(
                node.value, item, f"{path}[{index}]", location, complete=True
            )
        return
    if isinstance(node, TaggedUnionNode):
        _validate_tagged_union(node, value, path, location)
        return
    if isinstance(node, UnionNode):
        for branch in node.branches:
            try:
                _validate_value(branch, value, path, location, complete=True)
                return
            except OverlayError:
                pass
        raise OverlayError(
            f"Data at {path!r} does not match any union branch", location
        )
    raise AssertionError(f"Unhandled schema node: {type(node).__name__}")


def _validate_object(
    node: ObjectNode,
    value: Any,
    path: str,
    location: SourceLocation | None,
    *,
    complete: bool,
    merge: bool,
) -> None:
    if not isinstance(value, dict):
        raise OverlayError(f"Data at {path!r} must be a mapping", location)
    unknown = set(value) - set(node.keys)
    if unknown:
        raise OverlayError(
            f"Unknown key(s) at {path!r}: {', '.join(sorted(map(str, unknown)))}",
            location,
        )
    if complete:
        missing = set(node.keys) - set(value)
        if missing:
            raise OverlayError(
                f"Missing key(s) at {path!r}: {', '.join(sorted(missing))}",
                location,
            )
    for key, item in value.items():
        child_path = f"{path}.{key}" if path != "." else f".{key}"
        if merge:
            _validate_merge_value(node.keys[key], item, child_path, location)
        else:
            _validate_value(
                node.keys[key], item, child_path, location, complete=complete
            )


def _validate_map(
    node: MapNode,
    value: Any,
    path: str,
    location: SourceLocation | None,
    *,
    merge: bool,
) -> None:
    if not isinstance(value, dict):
        raise OverlayError(f"Data at {path!r} must be a mapping", location)
    for key, item in value.items():
        if not isinstance(key, str):
            raise OverlayError(f"Map keys at {path!r} must be strings", location)
        child_path = f"{path}.{key}" if path != "." else f".{key}"
        if merge:
            _validate_merge_value(node.value, item, child_path, location)
        else:
            _validate_value(node.value, item, child_path, location, complete=True)


def _validate_tagged_union(
    node: TaggedUnionNode,
    value: Any,
    path: str,
    location: SourceLocation | None,
) -> None:
    if not isinstance(value, dict):
        raise OverlayError(f"Data at {path!r} must be a mapping", location)
    tag = value.get(node.tag_field)
    if not isinstance(tag, str) or tag not in node.options:
        raise OverlayError(
            f"{path!r} requires tag {node.tag_field!r} with one of {tuple(node.options)}",
            location,
        )
    fields: dict[str, SchemaNode] = {
        node.tag_field: PrimitiveNode("string"),
        **node.common_keys,
        **node.options[tag].extra_keys,
    }
    _validate_object(
        ObjectNode(fields), value, path, location, complete=True, merge=False
    )
