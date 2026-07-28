# SPDX-License-Identifier: MPL-2.0

import logging
from collections.abc import Mapping
from typing import Any

import pytest

from config_cascade_merge import MergeError, MergePlan, Overlay, Schema


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


def make_overlay(
    schema: Schema,
    *operations: Mapping[str, Any],
    name: str = "example",
    source: str | None = None,
) -> Overlay:
    return Overlay.from_data(
        {"name": name, "operations": list(operations)},
        schema,
        source=source,
    )


def complete_initial() -> dict[str, Any]:
    return {
        "profile": {"name": "Grace", "active": False},
        "labels": {"existing": "yes"},
        "packages": [{"name": "ruff", "version": 1}],
        "modules": {"work": {"theme": "light", "enabled": True}},
        "count": 1,
    }


def test_validation_can_be_disabled_for_schema_shaped_object(schema: Schema) -> None:
    plan = MergePlan(schema)

    assert plan.create_object(validate=False) == {
        "profile": {"name": None, "active": None},
        "labels": {},
        "packages": [],
        "modules": {},
        "count": None,
    }


def test_create_object_validates_final_configuration_by_default(
    schema: Schema,
) -> None:
    with pytest.raises(
        MergeError,
        match=r"Invalid final configuration: .*'.profile.name'.*NoneType",
    ):
        MergePlan(schema).create_object()


def test_create_object_validates_after_overlays(schema: Schema) -> None:
    overlay = make_overlay(
        schema,
        {"action": "set", "path": ".profile.name", "data": "Ada"},
        {"action": "set", "path": ".profile.active", "data": True},
        {"action": "set", "path": ".count", "data": 1},
    )

    assert MergePlan(schema, [overlay]).create_object() == {
        "profile": {"name": "Ada", "active": True},
        "labels": {},
        "packages": [],
        "modules": {},
        "count": 1,
    }


def test_create_object_rejects_overlay_that_uninitializes_required_field() -> None:
    schema = Schema.from_data(
        {
            "type": "object",
            "keys": {"required": {"type": "string"}},
        }
    )
    overlay = make_overlay(
        schema,
        {"action": "remove", "path": ".required"},
    )

    with pytest.raises(
        MergeError,
        match=r"Invalid final configuration: .*'.required'.*NoneType",
    ):
        MergePlan(schema, [overlay]).create_object(
            initial={"required": "Ada"},
        )


def test_optional_fields_are_omitted_and_can_be_materialized() -> None:
    schema = Schema.from_data(
        {
            "type": "object",
            "keys": {
                "required": {"type": "string"},
                "profile": {
                    "type": "object",
                    "optional": True,
                    "keys": {
                        "name": {"type": "string"},
                        "active": {"type": "boolean", "optional": True},
                    },
                },
            },
        }
    )
    empty = MergePlan(schema).create_object(validate=False)
    overlay = make_overlay(
        schema,
        {"action": "set", "path": ".profile.name", "data": "Ada"},
    )

    assert empty == {"required": None}
    assert MergePlan(schema, [overlay]).create_object(validate=False) == {
        "required": None,
        "profile": {"name": "Ada"},
    }


def test_remove_deletes_optional_fields_but_nulls_required_fields() -> None:
    schema = Schema.from_data(
        {
            "type": "object",
            "keys": {
                "required": {"type": "string"},
                "nickname": {"type": "string", "optional": True},
            },
        }
    )
    overlay = make_overlay(
        schema,
        {"action": "remove", "path": ".nickname"},
        {"action": "remove", "path": ".required"},
    )

    assert MergePlan(schema, [overlay]).create_object(
        initial={"required": "Ada", "nickname": "A"},
        validate=False,
    ) == {"required": None}


def test_complete_values_may_omit_optional_fields() -> None:
    schema = Schema.from_data(
        {
            "type": "object",
            "merge": "override",
            "keys": {
                "required": {"type": "string"},
                "nickname": {"type": "string", "optional": True},
                "choice": {
                    "type": "tagged_union",
                    "optional": True,
                    "keys": {"label": {"type": "string", "optional": True}},
                    "tag": {
                        "name": "kind",
                        "options": {
                            "file": {
                                "path": {"type": "string"},
                                "mode": {"type": "string", "optional": True},
                            }
                        },
                    },
                },
            },
        }
    )
    initial = {"required": "Ada"}
    overlay = make_overlay(
        schema,
        {
            "action": "set",
            "path": ".choice",
            "data": {"kind": "file", "path": "/tmp/example"},
        },
    )

    assert MergePlan(schema).create_object(initial=initial) == initial
    assert MergePlan(schema, [overlay]).create_object(initial=initial) == {
        "required": "Ada",
        "choice": {"kind": "file", "path": "/tmp/example"},
    }


def test_optional_does_not_make_null_valid() -> None:
    schema = Schema.from_data(
        {
            "type": "object",
            "keys": {"nickname": {"type": "string", "optional": True}},
        }
    )

    with pytest.raises(MergeError, match="must be string"):
        MergePlan(schema).create_object(
            initial={"nickname": None},
            validate=False,
        )


def test_create_object_applies_all_mutating_operations(schema: Schema) -> None:
    overlay = make_overlay(
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
    )

    assert MergePlan(schema, [overlay]).create_object(validate=False) == {
        "profile": {"name": "Ada", "active": None},
        "labels": {"team": "core"},
        "packages": [
            {"name": "ruff", "version": 2},
            {"name": "uv", "version": 1},
        ],
        "modules": {},
        "count": None,
    }


def test_set_materializes_missing_dynamic_object_parent(schema: Schema) -> None:
    overlay = make_overlay(
        schema,
        {"action": "set", "path": ".modules.work.theme", "data": "dark"},
    )

    result = MergePlan(schema, [overlay]).create_object(validate=False)

    assert result["modules"] == {"work": {"theme": "dark", "enabled": None}}


def test_clear_uses_the_target_container_type(schema: Schema) -> None:
    overlay = make_overlay(
        schema,
        {"action": "merge", "path": ".labels", "data": {"team": "core"}},
        {
            "action": "merge",
            "path": ".packages",
            "data": [{"name": "ruff", "version": 1}],
        },
        {"action": "clear", "path": ".labels"},
        {"action": "clear", "path": ".packages"},
    )

    result = MergePlan(schema, [overlay]).create_object(validate=False)

    assert result["labels"] == {}
    assert result["packages"] == []


def test_override_policy_replaces_instead_of_appending() -> None:
    schema = Schema.from_data(
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
    overlay = make_overlay(
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
    )

    result = MergePlan(schema, [overlay]).create_object()

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
    schema: Schema,
    on_fail: str,
    expected: int | None,
) -> None:
    overlay = make_overlay(
        schema,
        {"action": "set", "path": ".count", "data": 1},
        {
            "action": "test",
            "path": ".count",
            "data": 99,
            "on_fail": on_fail,
        },
        {"action": "set", "path": ".count", "data": 2},
    )

    assert (
        MergePlan(schema, [overlay]).create_object(validate=False)["count"]
        == expected
    )


def test_duplicate_overlay_names_remain_separate_drop_boundaries(
    schema: Schema,
) -> None:
    first = make_overlay(
        schema,
        {"action": "set", "path": ".count", "data": 1},
        name="duplicate",
    )
    second = make_overlay(
        schema,
        {"action": "set", "path": ".count", "data": 2},
        {
            "action": "test",
            "path": ".count",
            "data": 99,
            "on_fail": "drop",
        },
        name="duplicate",
    )

    assert (
        MergePlan(schema, [first, second]).create_object(validate=False)["count"]
        == 1
    )


def test_warn_logs_and_continues(
    schema: Schema,
    caplog: pytest.LogCaptureFixture,
) -> None:
    overlay = make_overlay(
        schema,
        {
            "action": "test",
            "path": ".count",
            "data": 1,
            "on_fail": "warn",
            "message": "count was not initialized",
        },
        {"action": "set", "path": ".count", "data": 2},
    )

    with caplog.at_level(logging.WARNING, logger="config-cascade-merge"):
        result = MergePlan(schema, [overlay]).create_object(validate=False)

    assert result["count"] == 2
    assert "count was not initialized" in caplog.text


def test_error_test_failure_raises_merge_error(schema: Schema) -> None:
    overlay = make_overlay(
        schema,
        {"action": "test", "path": ".count", "data": 1},
    )

    with pytest.raises(MergeError, match=r"Test failed at '.count'"):
        MergePlan(schema, [overlay]).create_object()


def test_repeated_execution_does_not_mutate_overlay_data(schema: Schema) -> None:
    overlay = make_overlay(
        schema,
        {
            "action": "merge",
            "path": ".packages",
            "data": [{"name": "ruff", "version": 1}],
        },
    )
    plan = MergePlan(schema, [overlay])

    first = plan.create_object(validate=False)
    first["packages"][0]["version"] = 99

    assert plan.create_object(validate=False)["packages"][0]["version"] == 1


def test_valid_initial_object_is_copied_and_merged(schema: Schema) -> None:
    initial = complete_initial()
    original = complete_initial()
    overlay = make_overlay(
        schema,
        {"action": "set", "path": ".profile.active", "data": True},
        {"action": "merge", "path": ".labels", "data": {"team": "core"}},
        {
            "action": "merge",
            "path": ".packages",
            "data": [
                {"name": "ruff", "version": 2},
                {"name": "uv", "version": 1},
            ],
        },
    )

    result = MergePlan(schema, [overlay]).create_object(initial=initial)

    assert result == {
        "profile": {"name": "Grace", "active": True},
        "labels": {"existing": "yes", "team": "core"},
        "packages": [
            {"name": "ruff", "version": 2},
            {"name": "uv", "version": 1},
        ],
        "modules": {"work": {"theme": "light", "enabled": True}},
        "count": 1,
    }
    assert initial == original
    assert result is not initial
    assert result["profile"] is not initial["profile"]
    assert result["modules"]["work"] is not initial["modules"]["work"]


def test_result_mutation_never_reaches_initial_object(schema: Schema) -> None:
    initial = complete_initial()

    result = MergePlan(schema).create_object(initial=initial)
    result["profile"]["name"] = "Changed"
    result["packages"][0]["version"] = 99

    assert initial == complete_initial()


def test_partial_initial_materializes_missing_fields(schema: Schema) -> None:
    initial = {
        "profile": {"name": "Grace"},
        "packages": [{"name": "ruff"}],
        "modules": {"work": {"theme": "light"}},
    }

    assert MergePlan(schema).create_object(initial=initial, validate=False) == {
        "profile": {"name": "Grace", "active": None},
        "labels": {},
        "packages": [{"name": "ruff", "version": None}],
        "modules": {"work": {"theme": "light", "enabled": None}},
        "count": None,
    }


def test_partial_initial_materializes_missing_identity_field(schema: Schema) -> None:
    assert MergePlan(schema).create_object(
        initial={"packages": [{"version": 1}]},
        validate=False,
    )["packages"] == [{"name": None, "version": 1}]


def test_partial_initial_ignores_override_policy_and_omits_optional_fields() -> None:
    schema = Schema.from_data(
        {
            "type": "object",
            "keys": {
                "profile": {
                    "type": "object",
                    "merge": "override",
                    "keys": {
                        "name": {"type": "string"},
                        "active": {"type": "boolean"},
                        "nickname": {"type": "string", "optional": True},
                    },
                }
            },
        }
    )

    assert MergePlan(schema).create_object(
        initial={"profile": {"name": "Ada"}},
        validate=False,
    ) == {"profile": {"name": "Ada", "active": None}}


def test_partial_initial_materializes_tagged_union_fields() -> None:
    schema = Schema.from_data(
        {
            "type": "object",
            "keys": {
                "resource": {
                    "type": "tagged_union",
                    "keys": {
                        "label": {"type": "string"},
                        "note": {"type": "string", "optional": True},
                    },
                    "tag": {
                        "name": "kind",
                        "options": {
                            "file": {
                                "path": {"type": "string"},
                                "mode": {"type": "string", "optional": True},
                            },
                            "service": {"port": {"type": "integer"}},
                        },
                    },
                }
            },
        }
    )

    assert MergePlan(schema).create_object(
        initial={"resource": {"kind": "file", "path": "/tmp/config"}},
        validate=False,
    ) == {
        "resource": {
            "kind": "file",
            "label": None,
            "path": "/tmp/config",
        }
    }


@pytest.mark.parametrize(
    ("resource", "message"),
    [
        ({"path": "/tmp/config"}, "requires tag 'kind'"),
        ({"kind": "database"}, "requires tag 'kind'"),
        ({"kind": "file", "unknown": True}, "Unknown key.*unknown"),
    ],
)
def test_partial_initial_rejects_invalid_tagged_unions(
    resource: dict[str, Any],
    message: str,
) -> None:
    schema = Schema.from_data(
        {
            "type": "tagged_union",
            "tag": {
                "name": "kind",
                "options": {"file": {"path": {"type": "string"}}},
            },
        }
    )

    with pytest.raises(MergeError, match=message):
        MergePlan(schema).create_object(initial=resource)


def test_partial_initial_selects_unique_union_object_branch() -> None:
    schema = Schema.from_data(
        {
            "type": "union",
            "value": [
                {
                    "type": "object",
                    "keys": {
                        "name": {"type": "string"},
                        "active": {"type": "boolean"},
                    },
                },
                {
                    "type": "object",
                    "keys": {
                        "port": {"type": "integer"},
                        "secure": {"type": "boolean"},
                    },
                },
            ],
        }
    )

    assert MergePlan(schema).create_object(
        initial={"name": "api"},
        validate=False,
    ) == {
        "name": "api",
        "active": None,
    }


@pytest.mark.parametrize(
    ("initial", "message"),
    [
        ({"unknown": True}, "does not match any union branch"),
        ({}, "ambiguously matches multiple union branches"),
    ],
)
def test_partial_initial_rejects_unmatched_or_ambiguous_union_objects(
    initial: dict[str, Any],
    message: str,
) -> None:
    schema = Schema.from_data(
        {
            "type": "union",
            "value": [
                {
                    "type": "object",
                    "keys": {"name": {"type": "string"}},
                },
                {
                    "type": "object",
                    "keys": {"port": {"type": "integer"}},
                },
            ],
        }
    )

    with pytest.raises(MergeError, match=message):
        MergePlan(schema).create_object(initial=initial)


@pytest.mark.parametrize(
    ("initial", "message"),
    [
        ({**complete_initial(), "count": "one"}, "must be integer"),
        ({**complete_initial(), "count": None}, "must be integer"),
        ({**complete_initial(), "unknown": True}, "Unknown key.*unknown"),
    ],
)
def test_invalid_initial_object_fails_validation(
    schema: Schema,
    initial: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(
        MergeError,
        match=f"Invalid initial configuration: .*{message}",
    ):
        MergePlan(schema).create_object(initial=initial)


def test_invalid_initial_fails_before_overlay_execution(
    schema: Schema,
    caplog: pytest.LogCaptureFixture,
) -> None:
    overlay = make_overlay(
        schema,
        {
            "action": "test",
            "path": ".count",
            "data": 99,
            "on_fail": "warn",
            "message": "overlay executed",
        },
    )
    invalid = {"count": "one"}

    with caplog.at_level(logging.WARNING, logger="config-cascade-merge"):
        with pytest.raises(MergeError, match="Invalid initial configuration"):
            MergePlan(schema, [overlay]).create_object(initial=invalid)

    assert "overlay executed" not in caplog.text


def test_initial_object_is_unchanged_when_overlay_execution_fails(
    schema: Schema,
) -> None:
    initial = complete_initial()
    overlay = make_overlay(
        schema,
        {"action": "set", "path": ".count", "data": 2},
        {"action": "test", "path": ".count", "data": 99},
    )

    with pytest.raises(MergeError, match=r"Test failed at '.count'"):
        MergePlan(schema, [overlay]).create_object(initial=initial)

    assert initial == complete_initial()
