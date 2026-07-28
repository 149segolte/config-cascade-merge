# SPDX-License-Identifier: MPL-2.0

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from config_cascade_merge import Overlay, OverlayError, Schema


@pytest.fixture
def schema() -> Schema:
    return Schema.from_data(
        {
            "type": "object",
            "keys": {
                "profile": {
                    "type": "object",
                    "keys": {
                        "name": {"type": "string"},
                        "active": {"type": "boolean"},
                    },
                },
                "strict": {
                    "type": "object",
                    "merge": "override",
                    "keys": {
                        "name": {"type": "string"},
                        "active": {"type": "boolean"},
                    },
                },
                "registry": {"type": "map", "value": {"type": "integer"}},
                "packages": {
                    "type": "list",
                    "id": "name",
                    "value": {
                        "type": "object",
                        "keys": {
                            "name": {"type": "string"},
                            "version": {"type": "integer"},
                        },
                    },
                },
                "count": {"type": "integer"},
                "ratio": {"type": "float"},
                "choice": {
                    "type": "union",
                    "value": [{"type": "string"}, {"type": "integer"}],
                },
                "resource": {
                    "type": "tagged_union",
                    "keys": {"label": {"type": "string"}},
                    "tag": {
                        "name": "kind",
                        "options": {
                            "file": {"path": {"type": "string"}},
                            "service": {"port": {"type": "integer"}},
                        },
                    },
                },
            },
        }
    )


def make_overlay(*operations: Mapping[str, Any], name: str = "example") -> dict:
    return {"name": name, "operations": list(operations)}


def test_overlay_factory_normalizes_all_operation_types(schema: Schema) -> None:
    overlay = Overlay.from_data(
        make_overlay(
            {
                "action": "set",
                "path": ".profile",
                "data": {"name": "Ada", "active": True},
            },
            {"action": "remove", "path": ".profile.name"},
            {"action": "remove", "path": ".registry.old"},
            {
                "action": "merge",
                "path": ".packages",
                "data": [{"name": "ruff", "version": 1}],
            },
            {
                "action": "test",
                "path": ".profile.name",
                "data": "Ada",
                "on_fail": "warn",
                "message": "unexpected profile",
            },
            {"action": "clear", "path": ".registry"},
        ),
        schema,
        source="decoded overlay",
    )

    operations = overlay.operations
    assert overlay.name == "example"
    assert overlay.source == "decoded overlay"
    assert [operation.action for operation in operations] == [
        "set",
        "remove",
        "remove",
        "merge",
        "test",
        "clear",
    ]
    fixed_remove = operations[1]
    map_remove = operations[2]
    test_operation = operations[4]
    assert fixed_remove.action == "remove"
    assert map_remove.action == "remove"
    assert test_operation.action == "test"
    assert fixed_remove.mode == "null"
    assert map_remove.mode == "delete"
    assert test_operation.on_fail == "warn"
    assert test_operation.message == "unexpected profile"
    assert all(operation.overlay == "example" for operation in operations)
    assert all(operation.source == "decoded overlay" for operation in operations)


def test_test_operation_defaults_to_error_and_accepts_null(
    schema: Schema,
) -> None:
    overlay = Overlay.from_data(
        make_overlay(
            {"action": "test", "path": ".profile.name", "data": None},
        ),
        schema,
    )

    [operation] = overlay.operations
    assert operation.action == "test"
    assert operation.data is None
    assert operation.on_fail == "error"


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        ({"action": "unknown", "path": ".count"}, "'action' must be one of"),
        ({"action": "set", "path": "count", "data": 1}, "must be a dot path"),
        (
            {"action": "set", "path": ".missing", "data": 1},
            "Unknown config path",
        ),
        (
            {"action": "set", "path": ".count.value", "data": 1},
            "Cannot traverse through PrimitiveNode",
        ),
        (
            {"action": "set", "path": ".count"},
            "requires a 'data' field",
        ),
        (
            {"action": "set", "path": ".count", "data": 1, "extra": True},
            "Unknown field",
        ),
        (
            {"action": "merge", "path": ".count", "data": 1},
            "can only target an object, map, or list",
        ),
        (
            {"action": "clear", "path": ".profile"},
            "can only target a map or list",
        ),
        (
            {"action": "remove", "path": "."},
            "root cannot be removed",
        ),
        (
            {
                "action": "test",
                "path": ".count",
                "data": 1,
                "on_fail": "ignore",
            },
            "'on_fail' must be one of",
        ),
    ],
)
def test_overlay_factory_rejects_invalid_operations(
    schema: Schema,
    operation: Mapping[str, Any],
    message: str,
) -> None:
    with pytest.raises(OverlayError, match=message):
        Overlay.from_data(make_overlay(operation), schema)


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (
            {"action": "set", "path": ".count", "data": True},
            "must be integer",
        ),
        (
            {"action": "set", "path": ".profile", "data": {"name": "Ada"}},
            "Missing key.*active",
        ),
        (
            {"action": "set", "path": ".choice", "data": False},
            "does not match any union branch",
        ),
        (
            {
                "action": "set",
                "path": ".resource",
                "data": {"kind": "file", "label": "config"},
            },
            "Missing key.*path",
        ),
        (
            {
                "action": "set",
                "path": ".resource",
                "data": {"kind": "database", "label": "db"},
            },
            "requires tag 'kind'",
        ),
    ],
)
def test_set_validates_data_against_target_schema(
    schema: Schema,
    operation: Mapping[str, Any],
    message: str,
) -> None:
    with pytest.raises(OverlayError, match=message):
        Overlay.from_data(make_overlay(operation), schema)


def test_set_accepts_union_and_tagged_union_values(schema: Schema) -> None:
    overlay = Overlay.from_data(
        make_overlay(
            {"action": "set", "path": ".choice", "data": 7},
            {
                "action": "set",
                "path": ".resource",
                "data": {"kind": "file", "label": "config", "path": "/tmp/a"},
            },
        ),
        schema,
    )

    assert [operation.action for operation in overlay.operations] == ["set", "set"]


def test_merge_allows_partial_append_object(schema: Schema) -> None:
    overlay = Overlay.from_data(
        make_overlay(
            {"action": "merge", "path": ".profile", "data": {"name": "Grace"}},
        ),
        schema,
    )

    assert overlay.operations[0].action == "merge"


def test_merge_requires_complete_override_object(schema: Schema) -> None:
    with pytest.raises(OverlayError, match="Missing key.*active"):
        Overlay.from_data(
            make_overlay(
                {
                    "action": "merge",
                    "path": ".strict",
                    "data": {"name": "Grace"},
                },
            ),
            schema,
        )


def test_override_merge_allows_missing_optional_fields() -> None:
    schema = Schema.from_data(
        {
            "type": "object",
            "keys": {
                "profile": {
                    "type": "object",
                    "merge": "override",
                    "keys": {
                        "name": {"type": "string"},
                        "active": {"type": "boolean", "optional": True},
                    },
                }
            },
        }
    )

    overlay = Overlay.from_data(
        make_overlay(
            {"action": "merge", "path": ".profile", "data": {"name": "Grace"}},
        ),
        schema,
    )

    assert overlay.operations[0].action == "merge"


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"operations": []}, "requires a non-empty 'name' string"),
        ({"name": "example", "operations": {}}, "'operations' must be a list"),
        (
            {"name": "example", "operations": ["set"]},
            "Each operation must be a mapping",
        ),
    ],
)
def test_overlay_from_data_rejects_invalid_document_shape(
    schema: Schema,
    document: Mapping[str, Any],
    message: str,
) -> None:
    with pytest.raises(OverlayError, match=message):
        Overlay.from_data(document, schema)


def test_overlay_from_yaml_rejects_non_mapping_document(schema: Schema) -> None:
    with pytest.raises(OverlayError, match="Overlay document must be a mapping"):
        Overlay.from_yaml("[]\n", schema)


def test_overlay_error_reports_yaml_operation_line(schema: Schema) -> None:
    with pytest.raises(OverlayError) as error:
        Overlay.from_yaml(
            "name: example\n"
            "operations:\n"
            "  - action: set\n"
            "    path: .count\n"
            "    data: wrong\n",
            schema,
            source="overlay.yaml",
        )

    assert str(error.value).startswith("overlay.yaml:5:")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "Overlay document is empty"),
        ("name: [unterminated", "Could not parse overlay YAML"),
    ],
)
def test_overlay_from_file_rejects_empty_or_malformed_yaml(
    tmp_path: Path,
    schema: Schema,
    content: str,
    message: str,
) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(OverlayError, match=message) as error:
        Overlay.from_file(path, schema)

    assert str(path) in str(error.value)
