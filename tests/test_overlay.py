from pathlib import Path

import pytest

from utils import (
    ClearOperation,
    MergeOperation,
    OverlayError,
    RemoveOperation,
    SetOperation,
    load_overlays,
    load_yaml,
    parse_overlay,
    parse_schema,
)
from utils import (
    TestOperation as OverlayTestOperation,
)
from utils.schema import SchemaNode


@pytest.fixture
def schema() -> SchemaNode:
    return parse_schema(
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


def make_overlay(*operations: dict, name: str = "example") -> dict:
    return {"name": name, "operations": list(operations)}


def test_parse_overlay_normalizes_all_operation_types(schema: SchemaNode) -> None:
    operations = parse_overlay(
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
    )

    assert operations == [
        SetOperation("set", ".profile", {"name": "Ada", "active": True}, "example"),
        RemoveOperation("remove", ".profile.name", "null", "example"),
        RemoveOperation("remove", ".registry.old", "delete", "example"),
        MergeOperation(
            "merge",
            ".packages",
            [{"name": "ruff", "version": 1}],
            "example",
        ),
        OverlayTestOperation(
            "test",
            ".profile.name",
            "Ada",
            "warn",
            "example",
            "unexpected profile",
        ),
        ClearOperation("clear", ".registry", "example"),
    ]


def test_test_operation_defaults_to_error_and_accepts_null(schema: SchemaNode) -> None:
    [operation] = parse_overlay(
        make_overlay({"action": "test", "path": ".profile.name", "data": None}),
        schema,
    )

    assert operation == OverlayTestOperation(
        "test", ".profile.name", None, "error", "example"
    )


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
def test_parse_overlay_rejects_invalid_operations(
    schema: SchemaNode, operation: dict, message: str
) -> None:
    with pytest.raises(OverlayError, match=message):
        parse_overlay(make_overlay(operation), schema)


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
    schema: SchemaNode, operation: dict, message: str
) -> None:
    with pytest.raises(OverlayError, match=message):
        parse_overlay(make_overlay(operation), schema)


def test_set_accepts_union_and_tagged_union_values(schema: SchemaNode) -> None:
    operations = parse_overlay(
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

    assert [operation.action for operation in operations] == ["set", "set"]


def test_merge_allows_partial_append_object(schema: SchemaNode) -> None:
    [operation] = parse_overlay(
        make_overlay(
            {"action": "merge", "path": ".profile", "data": {"name": "Grace"}}
        ),
        schema,
    )

    assert operation.action == "merge"


def test_merge_requires_complete_override_object(schema: SchemaNode) -> None:
    with pytest.raises(OverlayError, match="Missing key.*active"):
        parse_overlay(
            make_overlay(
                {
                    "action": "merge",
                    "path": ".strict",
                    "data": {"name": "Grace"},
                }
            ),
            schema,
        )


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ([], "Overlay document must be a mapping"),
        ({"operations": []}, "requires a non-empty 'name' string"),
        ({"name": "example", "operations": {}}, "'operations' must be a list"),
        (
            {"name": "example", "operations": ["set"]},
            "Each operation must be a mapping",
        ),
    ],
)
def test_parse_overlay_rejects_invalid_document_shape(
    schema: SchemaNode, document: object, message: str
) -> None:
    with pytest.raises(OverlayError, match=message):
        parse_overlay(document, schema)


def test_overlay_error_reports_yaml_operation_line(schema: SchemaNode) -> None:
    document = load_yaml(
        "name: example\noperations:\n  - action: set\n    path: .count\n    data: wrong\n",
        "overlay.yaml",
    )

    with pytest.raises(OverlayError) as error:
        parse_overlay(document, schema)

    assert str(error.value).startswith("overlay.yaml:5:")


def test_load_overlays_uses_lexical_order_and_ignores_other_files(
    tmp_path: Path, schema: SchemaNode
) -> None:
    (tmp_path / "20-second.yml").write_text(
        "name: second\noperations:\n  - action: set\n    path: .count\n    data: 2\n"
    )
    (tmp_path / "10-first.yaml").write_text(
        "name: first\noperations:\n  - action: set\n    path: .count\n    data: 1\n"
    )
    (tmp_path / "notes.txt").write_text("not: an overlay\n")

    operations = load_overlays(tmp_path, schema)

    assert [operation.overlay for operation in operations] == ["first", "second"]
    assert [
        operation.data for operation in operations if operation.action == "set"
    ] == [
        1,
        2,
    ]
    assert [operation.source for operation in operations] == [
        str(tmp_path / "10-first.yaml"),
        str(tmp_path / "20-second.yml"),
    ]


def test_load_overlays_rejects_missing_directory(
    tmp_path: Path, schema: SchemaNode
) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(OverlayError, match="Overlay directory does not exist"):
        load_overlays(missing, schema)


@pytest.mark.parametrize("content", ["", "name: [unterminated"])
def test_load_overlays_rejects_empty_or_malformed_yaml(
    tmp_path: Path, schema: SchemaNode, content: str
) -> None:
    (tmp_path / "bad.yaml").write_text(content)

    with pytest.raises(OverlayError):
        load_overlays(tmp_path, schema)
