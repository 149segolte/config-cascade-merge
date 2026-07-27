# SPDX-License-Identifier: MPL-2.0

"""Public API for config-cascade-merge."""

from .api import MergePlan, Overlay, Schema
from .logging import ConfigError, MergeError, OverlayError, SchemaError

__all__ = [
    "ConfigError",
    "MergeError",
    "MergePlan",
    "Overlay",
    "OverlayError",
    "Schema",
    "SchemaError",
]
