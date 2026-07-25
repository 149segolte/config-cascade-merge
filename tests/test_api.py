# SPDX-License-Identifier: MPL-2.0

from pathlib import Path

import pytest

from config_cascade_merge import (
    MergePlan,
    ObjectNode,
    PrimitiveNode,
    SchemaError,
    load_merge_plan,
)


def test_load_merge_plan_returns_public_library_result(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    base_path.write_text(
        "type: object\n"
        "keys:\n"
        "  count:\n"
        "    type: integer\n",
        encoding="utf-8",
    )
    overlays_dir = tmp_path / "overlays"
    overlays_dir.mkdir()
    overlay_path = overlays_dir / "10-local.yaml"
    overlay_path.write_text(
        "name: local\n"
        "operations:\n"
        "  - action: set\n"
        "    path: .count\n"
        "    data: 2\n",
        encoding="utf-8",
    )

    plan = load_merge_plan(base_path, overlays_dir)

    assert isinstance(plan, MergePlan)
    assert isinstance(plan.schema, ObjectNode)
    count_schema = plan.schema.keys["count"]
    assert isinstance(count_schema, PrimitiveNode)
    assert count_schema.type == "integer"
    assert len(plan.operations) == 1
    assert plan.operations[0].action == "set"
    assert plan.operations[0].source == str(overlay_path)
    assert plan.create_object() == {"count": 2}


def test_load_merge_plan_accepts_string_paths(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    base_path.write_text("type: string\n", encoding="utf-8")
    overlays_dir = tmp_path / "overlays"
    overlays_dir.mkdir()

    plan = load_merge_plan(str(base_path), str(overlays_dir))

    assert isinstance(plan, MergePlan)
    assert plan.operations == ()


def test_load_merge_plan_returns_none_for_empty_schema(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    base_path.write_text("", encoding="utf-8")
    overlays_dir = tmp_path / "overlays"
    overlays_dir.mkdir()

    assert load_merge_plan(base_path, overlays_dir) is None


@pytest.mark.parametrize("schema_name", ["missing.yaml", "malformed.yaml"])
def test_load_merge_plan_raises_library_error_for_unreadable_schema(
    tmp_path: Path, schema_name: str
) -> None:
    base_path = tmp_path / schema_name
    if schema_name == "malformed.yaml":
        base_path.write_text("type: [unterminated\n", encoding="utf-8")
    overlays_dir = tmp_path / "overlays"
    overlays_dir.mkdir()

    with pytest.raises(SchemaError, match="Could not read schema") as error:
        load_merge_plan(base_path, overlays_dir)

    assert str(base_path) in str(error.value)
