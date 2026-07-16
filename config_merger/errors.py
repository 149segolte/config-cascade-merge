"""Error types for config-merger.

Every error includes a `path` attribute (dot-separated schema/data path) so
callers can pinpoint which node caused the failure.
"""

from __future__ import annotations


class ConfigError(Exception):
    """Base class for all config-merger errors."""

    def __init__(self, message: str, path: str = "") -> None:
        self.path = path
        super().__init__(f"[{path}] {message}" if path else message)


# ---------------------------------------------------------------------------
# Schema-level errors  (raised while parsing / normalising the config)
# ---------------------------------------------------------------------------


class SchemaValidationError(ConfigError):
    """Raised when the schema config is structurally invalid."""


class UnsupportedPolicyError(SchemaValidationError):
    """Raised when a merge policy is not supported for the given schema type."""

    def __init__(self, policy: str, node_type: str, path: str = "") -> None:
        self.policy = policy
        self.node_type = node_type
        super().__init__(
            f"Merge policy {policy!r} is not supported for type {node_type!r}; "
            "only 'override' is allowed",
            path=path,
        )


class InvalidTaggedUnionConfigError(SchemaValidationError):
    """Raised when a tagged_union schema section is malformed."""


# ---------------------------------------------------------------------------
# Merge-time errors  (raised while executing the merge)
# ---------------------------------------------------------------------------


class MergeError(ConfigError):
    """Raised during merge execution due to data-level problems."""


class TypeMismatchError(MergeError):
    """Raised when a data value's type does not match the schema type."""

    def __init__(self, expected: str, actual: type, path: str = "") -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Expected type {expected!r}, got {actual.__name__!r}",
            path=path,
        )


class MissingRequiredIdError(MergeError):
    """Raised when the id field declared in the schema is absent from data."""

    def __init__(self, id_field: str, path: str = "") -> None:
        self.id_field = id_field
        super().__init__(f"Missing required id field {id_field!r}", path=path)


class AmbiguousUnionError(MergeError):
    """Raised when more than one union branch matches the incoming value."""

    def __init__(self, match_count: int, path: str = "") -> None:
        self.match_count = match_count
        super().__init__(
            f"Ambiguous union: {match_count} branches match the incoming value",
            path=path,
        )


class UnknownUnionTagError(MergeError):
    """Raised when the tag value in a tagged_union is missing or unknown."""

    def __init__(
        self,
        tag_field: str,
        tag_value: object,
        known_tags: list[str],
        path: str = "",
    ) -> None:
        self.tag_field = tag_field
        self.tag_value = tag_value
        self.known_tags = known_tags
        super().__init__(
            f"Unknown or missing tag value {tag_value!r} for field {tag_field!r}; "
            f"known tags: {known_tags}",
            path=path,
        )


class MergeConflictError(MergeError):
    """Raised when two objects share an id field but have conflicting id values."""

    def __init__(
        self,
        field: str,
        value_a: object,
        value_b: object,
        path: str = "",
    ) -> None:
        self.field = field
        self.value_a = value_a
        self.value_b = value_b
        super().__init__(
            f"Merge conflict on id field {field!r}: "
            f"cannot merge {value_a!r} with {value_b!r}",
            path=path,
        )
