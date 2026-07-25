# SPDX-License-Identifier: MPL-2.0

"""Public API for config-merger."""

from .logging import (
    ConfigError,
    OverlayError,
    SchemaError,
    configure_logging,
    logger,
)
from .overlay import (
    ClearOperation,
    MergeOperation,
    Operation,
    RemoveOperation,
    SetOperation,
    TestOperation,
    load_overlays,
    parse_overlay,
)
from .schema import parse_schema
from .yaml_loader import SourceLocation, YamlLoader, load_yaml

__all__ = [
    "ClearOperation",
    "ConfigError",
    "MergeOperation",
    "Operation",
    "OverlayError",
    "RemoveOperation",
    "SchemaError",
    "SetOperation",
    "SourceLocation",
    "TestOperation",
    "YamlLoader",
    "configure_logging",
    "load_overlays",
    "load_yaml",
    "logger",
    "parse_overlay",
    "parse_schema",
]
