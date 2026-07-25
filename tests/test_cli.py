# SPDX-License-Identifier: MPL-2.0

import sys
from pathlib import Path

import pytest
import yaml

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

    plan = run(schema, overlays)

    assert plan is not None
    assert yaml.safe_load(capsys.readouterr().out) == {
        "profile": {"name": "Ada", "active": None},
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
