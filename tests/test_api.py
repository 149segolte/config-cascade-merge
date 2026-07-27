# SPDX-License-Identifier: MPL-2.0

from pathlib import Path

import pytest
import yaml

import config_cascade_merge
from config_cascade_merge import (
    ConfigError,
    MergePlan,
    Overlay,
    OverlayError,
    Schema,
    SchemaError,
)

SCHEMA_DATA = {
    "type": "object",
    "keys": {
        "count": {"type": "integer"},
        "labels": {"type": "map", "value": {"type": "string"}},
    },
}
SCHEMA_YAML = (
    "type: object\n"
    "keys:\n"
    "  count: {type: integer}\n"
    "  labels:\n"
    "    type: map\n"
    "    value: {type: string}\n"
)
OVERLAY_DATA = {
    "name": "local",
    "operations": [
        {"action": "set", "path": ".count", "data": 2},
        {"action": "merge", "path": ".labels", "data": {"team": "core"}},
    ],
}
OVERLAY_YAML = (
    "name: local\n"
    "operations:\n"
    "  - action: set\n"
    "    path: .count\n"
    "    data: 2\n"
    "  - action: merge\n"
    "    path: .labels\n"
    "    data:\n"
    "      team: core\n"
)


def test_schema_factories_are_equivalent_and_preserve_sources(
    tmp_path: Path,
) -> None:
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(SCHEMA_YAML, encoding="utf-8")

    from_file = Schema.from_file(schema_path)
    from_yaml = Schema.from_yaml(SCHEMA_YAML, source="inline-schema.yaml")
    from_data = Schema.from_data(SCHEMA_DATA, source="decoded schema")

    assert from_file == from_yaml == from_data
    assert from_file.source == str(schema_path)
    assert from_yaml.source == "inline-schema.yaml"
    assert from_data.source == "decoded schema"


def test_overlay_factories_are_equivalent_and_preserve_metadata(
    tmp_path: Path,
) -> None:
    schema = Schema.from_data(SCHEMA_DATA)
    overlay_path = tmp_path / "local.yaml"
    overlay_path.write_text(OVERLAY_YAML, encoding="utf-8")

    from_file = Overlay.from_file(overlay_path, schema)
    from_yaml = Overlay.from_yaml(
        OVERLAY_YAML,
        schema,
        source="inline-overlay.yaml",
    )
    from_data = Overlay.from_data(
        OVERLAY_DATA,
        schema,
        source="decoded overlay",
    )

    assert from_file == from_yaml == from_data
    assert from_file.name == "local"
    assert from_file.source == str(overlay_path)
    assert from_yaml.source == "inline-overlay.yaml"
    assert from_data.source == "decoded overlay"
    assert [operation.action for operation in from_file.operations] == [
        "set",
        "merge",
    ]
    assert all(
        operation.source == str(overlay_path)
        for operation in from_file.operations
    )


def test_plan_composition_preserves_order_and_prior_plans() -> None:
    schema = Schema.from_data(SCHEMA_DATA)
    common = Overlay.from_data(
        {
            "name": "common",
            "operations": [
                {"action": "set", "path": ".count", "data": 1},
            ],
        },
        schema,
    )
    labels = Overlay.from_data(
        {
            "name": "labels",
            "operations": [
                {
                    "action": "merge",
                    "path": ".labels",
                    "data": {"team": "core"},
                },
            ],
        },
        schema,
    )
    local = Overlay.from_data(OVERLAY_DATA, schema)

    base_plan = MergePlan(schema)
    common_plan = base_plan.with_overlay(common)
    local_plan = common_plan.with_overlays(
        overlay for overlay in (labels, local)
    )

    assert base_plan.schema is schema
    assert base_plan.overlays == ()
    assert common_plan.overlays == (common,)
    assert local_plan.overlays == (common, labels, local)
    assert common_plan.create_object() == {"count": 1, "labels": {}}
    assert local_plan.create_object() == {
        "count": 2,
        "labels": {"team": "core"},
    }


def test_plan_overlays_transfer_to_structurally_equal_schema() -> None:
    first_schema = Schema.from_data(SCHEMA_DATA, source="first")
    second_schema = Schema.from_yaml(SCHEMA_YAML, source="second")
    overlay = Overlay.from_data(OVERLAY_DATA, first_schema)

    transferred = MergePlan(second_schema, MergePlan(first_schema, [overlay]).overlays)

    assert transferred.schema is second_schema
    assert transferred.overlays == (overlay,)
    assert transferred.create_object() == {
        "count": 2,
        "labels": {"team": "core"},
    }


def test_plan_rejects_overlay_for_different_schema() -> None:
    schema = Schema.from_data(SCHEMA_DATA)
    other_schema = Schema.from_data({"type": "string"})
    overlay = Overlay.from_data(OVERLAY_DATA, schema)

    with pytest.raises(ConfigError, match="created for a different schema"):
        MergePlan(other_schema, [overlay])


def test_plan_rejects_raw_overlay_inputs() -> None:
    schema = Schema.from_data(SCHEMA_DATA)
    raw_path = yaml.safe_load("overlay.yaml\n")
    raw_overlays = yaml.safe_load("- name: raw\n")
    plan = MergePlan(schema)

    with pytest.raises(ConfigError, match="must be an Overlay"):
        plan.with_overlay(raw_path)
    with pytest.raises(ConfigError, match="must be an Overlay"):
        plan.with_overlays(raw_overlays)
    with pytest.raises(ConfigError, match="must be an Overlay"):
        MergePlan(schema, raw_overlays)


def test_public_objects_are_read_only() -> None:
    schema = Schema.from_data(SCHEMA_DATA)
    overlay = Overlay.from_data(OVERLAY_DATA, schema)
    plan = MergePlan(schema, [overlay])

    with pytest.raises(AttributeError):
        setattr(schema, "source", "changed")
    with pytest.raises(AttributeError):
        setattr(overlay, "name", "changed")
    with pytest.raises(AttributeError):
        setattr(overlay, "operations", ())
    with pytest.raises(AttributeError):
        setattr(plan, "overlays", ())


def test_factories_defensively_isolate_mutable_input_and_inspection() -> None:
    raw_schema = {
        "type": "object",
        "keys": {"items": {"type": "list", "value": {"type": "integer"}}},
    }
    raw_overlay = {
        "name": "items",
        "operations": [
            {"action": "set", "path": ".items", "data": [1, 2]},
        ],
    }
    schema = Schema.from_data(raw_schema)
    overlay = Overlay.from_data(raw_overlay, schema)

    raw_schema["keys"]["items"]["value"]["type"] = "string"
    raw_overlay["operations"][0]["data"].append(3)
    exposed_operations = overlay.operations
    exposed_set = exposed_operations[0]
    assert exposed_set.action == "set"
    exposed_set.data.append(4)

    assert MergePlan(schema, [overlay]).create_object() == {"items": [1, 2]}


@pytest.mark.parametrize(
    ("factory", "error_type", "message"),
    [
        (
            lambda path: Schema.from_file(path),
            SchemaError,
            "Could not read schema",
        ),
        (
            lambda path: Overlay.from_file(
                path,
                Schema.from_data(SCHEMA_DATA),
            ),
            OverlayError,
            "Could not read overlay",
        ),
    ],
)
def test_file_factories_report_missing_paths(
    tmp_path: Path,
    factory,
    error_type,
    message: str,
) -> None:
    missing = tmp_path / "missing.yaml"

    with pytest.raises(error_type, match=message) as error:
        factory(missing)

    assert str(missing) in str(error.value)


def test_direct_construction_and_v09_surface_are_removed() -> None:
    public_namespace = vars(config_cascade_merge)
    with pytest.raises(TypeError):
        public_namespace["Schema"]()
    with pytest.raises(TypeError):
        public_namespace["Overlay"]()

    for name in (
        "create_object",
        "load_merge_plan",
        "parse_schema",
        "parse_overlay",
        "SchemaNode",
        "Operation",
    ):
        assert not hasattr(config_cascade_merge, name)
