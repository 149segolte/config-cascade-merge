# SPDX-License-Identifier: MPL-2.0

import sys
from pathlib import Path

import pytest
import yaml

from config_cascade_merge import MergePlan, Schema
from config_cascade_merge.cli import main, run


def test_cli_help(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["config-cascade-merge", "--help"])

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 0
    assert "Create a merged YAML object" in capsys.readouterr().out


def test_run_emits_completed_object_as_yaml(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    schema = tmp_path / "schema.yaml"
    schema.write_text(
        "type: object\n"
        "keys:\n"
        "  profile:\n"
        "    type: object\n"
        "    keys:\n"
        "      name: {type: string}\n"
        "      active: {type: boolean}\n"
        "  labels:\n"
        "    type: map\n"
        "    value: {type: string}\n",
        encoding="utf-8",
    )
    overlays = tmp_path / "overlays"
    overlays.mkdir()
    (overlays / "05-common.yml").write_text(
        "name: common\n"
        "operations:\n"
        "  - action: set\n"
        "    path: .profile.active\n"
        "    data: true\n",
        encoding="utf-8",
    )
    (overlays / "10-local.yaml").write_text(
        "name: local\n"
        "operations:\n"
        "  - action: set\n"
        "    path: .profile.name\n"
        "    data: Ada\n"
        "  - action: merge\n"
        "    path: .labels\n"
        "    data:\n"
        "      team: core\n",
        encoding="utf-8",
    )
    (overlays / "notes.txt").write_text("not: an overlay\n", encoding="utf-8")

    plan = run(schema, overlays)

    assert isinstance(plan, MergePlan)
    assert isinstance(plan.schema, Schema)
    assert [overlay.name for overlay in plan.overlays] == ["common", "local"]
    assert [overlay.source for overlay in plan.overlays] == [
        str(overlays / "05-common.yml"),
        str(overlays / "10-local.yaml"),
    ]
    assert yaml.safe_load(capsys.readouterr().out) == {
        "profile": {"name": "Ada", "active": True},
        "labels": {"team": "core"},
    }


def test_run_exits_when_plan_execution_fails(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    schema = tmp_path / "schema.yaml"
    schema.write_text(
        "type: object\nkeys:\n  count: {type: integer}\n",
        encoding="utf-8",
    )
    overlays = tmp_path / "overlays"
    overlays.mkdir()
    (overlays / "10-local.yaml").write_text(
        "name: local\n"
        "operations:\n"
        "  - action: test\n"
        "    path: .count\n"
        "    data: 1\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as error:
        run(schema, overlays)

    assert error.value.code == 1
    assert "Test failed at '.count'" in caplog.text


def test_cli_accepts_ordered_overlay_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    schema = tmp_path / "schema.yaml"
    schema.write_text(
        "type: object\nkeys:\n  count: {type: integer}\n", encoding="utf-8"
    )
    first = tmp_path / "20-first.yaml"
    first.write_text(
        "name: first\noperations:\n  - action: set\n    path: .count\n    data: 1\n",
        encoding="utf-8",
    )
    last = tmp_path / "10-last.yaml"
    last.write_text(
        "name: last\noperations:\n  - action: set\n    path: .count\n    data: 2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "config-cascade-merge",
            "--base_config",
            str(schema),
            "--overlays",
            str(first),
            str(last),
        ],
    )

    main()

    assert yaml.safe_load(capsys.readouterr().out) == {"count": 2}


def test_run_exits_for_empty_schema(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    schema = tmp_path / "schema.yaml"
    schema.write_text("", encoding="utf-8")
    overlays = tmp_path / "overlays"
    overlays.mkdir()

    with pytest.raises(SystemExit) as error:
        run(schema, overlays)

    assert error.value.code == 1
    assert "Schema document is empty" in caplog.text


def test_run_uses_overlay_factory_validation(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    schema = tmp_path / "schema.yaml"
    schema.write_text("type: integer\n", encoding="utf-8")
    overlay = tmp_path / "bad.yaml"
    overlay.write_text(
        "name: bad\n"
        "operations:\n"
        "  - action: set\n"
        "    path: .\n"
        "    data: wrong\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as error:
        run(schema, [overlay])

    assert error.value.code == 1
    assert "must be integer" in caplog.text
    assert f"{overlay}:5:" in caplog.text
