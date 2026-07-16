"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture(scope="session")
def example_config() -> dict:
    """Return the raw example_config.yaml dict."""
    path = Path(__file__).parent.parent / "example_config.yaml"
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="session")
def example_schema(example_config):
    """Return the parsed schema for example_config.yaml."""
    from config_merger.schema import parse_schema

    return parse_schema(example_config)
