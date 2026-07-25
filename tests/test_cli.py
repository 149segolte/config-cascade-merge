# SPDX-License-Identifier: MPL-2.0

import sys

import pytest

from config_merger.cli import main


def test_cli_help(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["config-merger", "--help"])

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 0
    assert "Validate YAML overlay operations" in capsys.readouterr().out
