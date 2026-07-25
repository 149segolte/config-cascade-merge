# SPDX-License-Identifier: MPL-2.0

import logging

import pytest

from config_cascade_merge import (
    MergeError,
    MergePlan,
    create_object,
    parse_overlay,
    parse_schema,
)
from config_cascade_merge.schema import SchemaNode


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
                "labels": {"type": "map", "value": {"type": "string"}},
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
                "modules": {
                    "type": "map",
                    "value": {
                        "type": "object",
                        "keys": {
                            "theme": {"type": "string"},
                            "enabled": {"type": "boolean"},
                        },
                    },
                },
                "count": {"type": "integer"},
            },
        }
    )


def operations(schema: SchemaNode, *items: dict, name: str = "example"):
    return tuple(
        parse_overlay({"name": name, "operations": list(items)}, schema)
    )


def test_empty_plan_creates_complete_schema_shaped_object(
    schema: SchemaNode,
) -> None:
    plan = MergePlan(schema, ())

    assert plan.create_object() == {
        "profile": {"name": None, "active": None},
        "labels": {},
        "packages": [],
        "modules": {},
        "count": None,
    }


def test_create_object_applies_all_mutating_operations(schema: SchemaNode) -> None:
    plan = MergePlan(
        schema,
        operations(
            schema,
            {"action": "set", "path": ".profile.name", "data": "Ada"},
            {"action": "set", "path": ".profile.active", "data": True},
            {
                "action": "merge",
                "path": ".labels",
                "data": {"team": "core", "legacy": "yes"},
            },
            {
                "action": "merge",
                "path": ".packages",
                "data": [{"name": "ruff", "version": 1}],
            },
            {
                "action": "merge",
                "path": ".packages",
                "data": [
                    {"name": "ruff", "version": 2},
                    {"name": "uv", "version": 1},
                ],
            },
            {"action": "remove", "path": ".profile.active"},
            {"action": "remove", "path": ".labels.legacy"},
        ),
    )

    assert create_object(plan) == {
        "profile": {"name": "Ada", "active": None},
        "labels": {"team": "core"},
        "packages": [
            {"name": "ruff", "version": 2},
            {"name": "uv", "version": 1},
        ],
        "modules": {},
        "count": None,
    }


def test_set_materializes_missing_dynamic_object_parent(
    schema: SchemaNode,
) -> None:
    plan = MergePlan(
        schema,
        operations(
            schema,
            {"action": "set", "path": ".modules.work.theme", "data": "dark"},
        ),
    )

    assert plan.create_object()["modules"] == {
        "work": {"theme": "dark", "enabled": None}
    }


def test_clear_uses_the_target_container_type(schema: SchemaNode) -> None:
    plan = MergePlan(
        schema,
        operations(
            schema,
            {"action": "merge", "path": ".labels", "data": {"team": "core"}},
            {
                "action": "merge",
                "path": ".packages",
                "data": [{"name": "ruff", "version": 1}],
            },
            {"action": "clear", "path": ".labels"},
            {"action": "clear", "path": ".packages"},
        ),
    )

    result = plan.create_object()

    assert result["labels"] == {}
    assert result["packages"] == []


def test_override_policy_replaces_instead_of_appending() -> None:
    schema = parse_schema(
        {
            "type": "object",
            "keys": {
                "settings": {
                    "type": "object",
                    "merge": "override",
                    "keys": {
                        "name": {"type": "string"},
                        "enabled": {"type": "boolean"},
                    },
                },
                "labels": {
                    "type": "map",
                    "merge": "override",
                    "value": {"type": "string"},
                },
                "items": {
                    "type": "list",
                    "merge": "override",
                    "value": {"type": "integer"},
                },
            },
        }
    )
    plan = MergePlan(
        schema,
        operations(
            schema,
            {
                "action": "set",
                "path": ".settings",
                "data": {"name": "old", "enabled": False},
            },
            {
                "action": "merge",
                "path": ".settings",
                "data": {"name": "new", "enabled": True},
            },
            {"action": "merge", "path": ".labels", "data": {"old": "value"}},
            {"action": "merge", "path": ".labels", "data": {"new": "value"}},
            {"action": "merge", "path": ".items", "data": [1, 2]},
            {"action": "merge", "path": ".items", "data": [3]},
        ),
    )

    result = plan.create_object()

    assert result["settings"] == {"name": "new", "enabled": True}
    assert result["labels"] == {"new": "value"}
    assert result["items"] == [3]


@pytest.mark.parametrize(
    ("on_fail", "expected"),
    [
        ("drop", None),
        ("skip", 1),
    ],
)
def test_failed_test_controls_remaining_overlay_operations(
    schema: SchemaNode,
    on_fail: str,
    expected: int | None,
) -> None:
    plan = MergePlan(
        schema,
        operations(
            schema,
            {"action": "set", "path": ".count", "data": 1},
            {
                "action": "test",
                "path": ".count",
                "data": 99,
                "on_fail": on_fail,
            },
            {"action": "set", "path": ".count", "data": 2},
        ),
    )

    assert plan.create_object()["count"] == expected


def test_drop_only_rolls_back_the_failing_overlay(schema: SchemaNode) -> None:
    first = operations(
        schema,
        {"action": "set", "path": ".count", "data": 1},
        name="base",
    )
    second = operations(
        schema,
        {"action": "set", "path": ".count", "data": 2},
        {
            "action": "test",
            "path": ".count",
            "data": 99,
            "on_fail": "drop",
        },
        name="optional",
    )

    assert MergePlan(schema, first + second).create_object()["count"] == 1


def test_warn_logs_and_continues(
    schema: SchemaNode,
    caplog: pytest.LogCaptureFixture,
) -> None:
    plan = MergePlan(
        schema,
        operations(
            schema,
            {
                "action": "test",
                "path": ".count",
                "data": 1,
                "on_fail": "warn",
                "message": "count was not initialized",
            },
            {"action": "set", "path": ".count", "data": 2},
        ),
    )

    with caplog.at_level(logging.WARNING, logger="config-cascade-merge"):
        result = plan.create_object()

    assert result["count"] == 2
    assert "count was not initialized" in caplog.text


def test_error_test_failure_raises_merge_error(schema: SchemaNode) -> None:
    plan = MergePlan(
        schema,
        operations(
            schema,
            {"action": "test", "path": ".count", "data": 1},
        ),
    )

    with pytest.raises(MergeError, match=r"Test failed at '.count'"):
        plan.create_object()


def test_create_object_does_not_mutate_operation_data(schema: SchemaNode) -> None:
    plan = MergePlan(
        schema,
        operations(
            schema,
            {
                "action": "merge",
                "path": ".packages",
                "data": [{"name": "ruff", "version": 1}],
            },
        ),
    )

    first = plan.create_object()
    first["packages"][0]["version"] = 99

    assert plan.create_object()["packages"][0]["version"] == 1
