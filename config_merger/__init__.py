"""config_merger – deterministic recursive dict merging via a YAML schema."""

from __future__ import annotations

from .engine import merge
from .errors import (
    AmbiguousUnionError,
    ConfigError,
    InvalidTaggedUnionConfigError,
    MergeConflictError,
    MergeError,
    MissingRequiredIdError,
    SchemaValidationError,
    TypeMismatchError,
    UnknownUnionTagError,
    UnsupportedPolicyError,
)

__all__ = [
    "merge",
    # errors
    "ConfigError",
    "SchemaValidationError",
    "MergeError",
    "TypeMismatchError",
    "MissingRequiredIdError",
    "UnsupportedPolicyError",
    "AmbiguousUnionError",
    "UnknownUnionTagError",
    "InvalidTaggedUnionConfigError",
    "MergeConflictError",
]
