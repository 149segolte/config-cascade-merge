# SPDX-License-Identifier: MPL-2.0

"""Composable public API for schema-driven configuration merging."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import InitVar, dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

from .logging import ConfigError, OverlayError, SchemaError
from .overlay import Operation as _Operation
from .overlay import parse_overlay as _parse_overlay
from .schema import SchemaNode as _SchemaNode
from .schema import parse_schema as _parse_schema
from .yaml_loader import SourceLocation, load_yaml

__all__ = ["MergePlan", "Overlay", "Schema"]

_UNSET = object()


class _FactoryToken:
    """Capability required to construct factory-only public values."""


_FACTORY_TOKEN = _FactoryToken()


def _source_name(source: str | Path | None) -> str | None:
    return str(source) if source is not None else None


def _plain_data(value: Any) -> Any:
    """Copy decoded data into isolated built-in containers."""
    if isinstance(value, Mapping):
        return {_plain_data(key): _plain_data(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain_data(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True, eq=False)
class Schema:
    """An immutable, normalized configuration schema."""

    _root: _SchemaNode = field(repr=False)
    source: str | None = None
    _factory_token: InitVar[_FactoryToken | None] = None

    def __post_init__(self, factory_token: _FactoryToken | None) -> None:
        if factory_token is not _FACTORY_TOKEN:
            raise TypeError("Schema objects must be created with a Schema factory")

    @classmethod
    def _create(cls, root: _SchemaNode, source: str | None) -> Schema:
        return cls(root, source, _FACTORY_TOKEN)

    @classmethod
    def from_file(cls, path: str | Path) -> Schema:
        """Load and normalize a schema from a UTF-8 YAML file."""
        schema_path = Path(path)
        source = str(schema_path)
        try:
            text = schema_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise SchemaError(
                f"Could not read schema: {error}", SourceLocation(source)
            ) from error
        return cls.from_yaml(text, source=source)

    @classmethod
    def from_yaml(
        cls,
        text: str,
        source: str | Path | None = None,
    ) -> Schema:
        """Load and normalize a schema from YAML text."""
        source_name = _source_name(source)
        try:
            document = load_yaml(text, file_name=source_name)
        except yaml.YAMLError as error:
            raise SchemaError(
                f"Could not parse schema YAML: {error}",
                SourceLocation(source_name),
            ) from error
        if document is None:
            raise SchemaError(
                "Schema document is empty",
                SourceLocation(source_name, 1),
            )
        root = _parse_schema(
            document,
            location=SourceLocation(source_name, 1),
        )
        return cls._create(root, source_name)

    @classmethod
    def from_data(
        cls,
        mapping: Mapping[str, Any],
        source: str | Path | None = None,
    ) -> Schema:
        """Normalize an already-decoded schema mapping."""
        source_name = _source_name(source)
        if not isinstance(mapping, Mapping):
            raise SchemaError(
                f"Schema data must be a mapping, got {type(mapping).__name__!r}",
                SourceLocation(source_name),
            )
        root = _parse_schema(
            _plain_data(mapping),
            location=SourceLocation(source_name),
        )
        return cls._create(root, source_name)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Schema):
            return NotImplemented
        return self._root == other._root

    def __repr__(self) -> str:
        if self.source is None:
            return "Schema()"
        return f"Schema(source={self.source!r})"


@dataclass(frozen=True, eq=False)
class Overlay:
    """An immutable, reusable group of validated overlay operations."""

    _schema: Schema = field(repr=False)
    name: str
    source: str | None
    _operations: tuple[_Operation, ...] = field(repr=False)
    _factory_token: InitVar[_FactoryToken | None] = None

    def __post_init__(self, factory_token: _FactoryToken | None) -> None:
        if factory_token is not _FACTORY_TOKEN:
            raise TypeError("Overlay objects must be created with an Overlay factory")

    @classmethod
    def _from_document(
        cls,
        document: Any,
        schema: Schema,
        source: str | None,
    ) -> Overlay:
        if not isinstance(schema, Schema):
            raise ConfigError("Overlay factories require a Schema instance")
        operations = tuple(
            _parse_overlay(document, schema._root, file_name=source)
        )
        # Empty operation lists still have a required, validated overlay name.
        name = document["name"]
        return cls(schema, name, source, operations, _FACTORY_TOKEN)

    @classmethod
    def from_file(cls, path: str | Path, schema: Schema) -> Overlay:
        """Load and validate an overlay from a UTF-8 YAML file."""
        overlay_path = Path(path)
        source = str(overlay_path)
        try:
            text = overlay_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise OverlayError(
                f"Could not read overlay: {error}", SourceLocation(source)
            ) from error
        return cls.from_yaml(text, schema, source=source)

    @classmethod
    def from_yaml(
        cls,
        text: str,
        schema: Schema,
        source: str | Path | None = None,
    ) -> Overlay:
        """Load and validate an overlay from YAML text."""
        if not isinstance(schema, Schema):
            raise ConfigError("Overlay factories require a Schema instance")
        source_name = _source_name(source)
        try:
            document = load_yaml(text, file_name=source_name)
        except yaml.YAMLError as error:
            raise OverlayError(
                f"Could not parse overlay YAML: {error}",
                SourceLocation(source_name),
            ) from error
        if document is None:
            raise OverlayError(
                "Overlay document is empty",
                SourceLocation(source_name, 1),
            )
        return cls._from_document(document, schema, source_name)

    @classmethod
    def from_data(
        cls,
        mapping: Mapping[str, Any],
        schema: Schema,
        source: str | Path | None = None,
    ) -> Overlay:
        """Validate an already-decoded overlay mapping."""
        if not isinstance(schema, Schema):
            raise ConfigError("Overlay factories require a Schema instance")
        source_name = _source_name(source)
        if not isinstance(mapping, Mapping):
            raise OverlayError(
                f"Overlay data must be a mapping, got {type(mapping).__name__!r}",
                SourceLocation(source_name),
            )
        return cls._from_document(_plain_data(mapping), schema, source_name)

    @property
    def operations(self) -> tuple[_Operation, ...]:
        """Defensively copied operations in document order."""
        return deepcopy(self._operations)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Overlay):
            return NotImplemented
        if self._schema != other._schema or self.name != other.name:
            return False
        if len(self._operations) != len(other._operations):
            return False
        return all(
            _operations_equal(left, right)
            for left, right in zip(self._operations, other._operations)
        )

    def __repr__(self) -> str:
        details = f"name={self.name!r}"
        if self.source is not None:
            details += f", source={self.source!r}"
        return f"Overlay({details})"


@dataclass(frozen=True, init=False)
class MergePlan:
    """An immutable schema plus an ordered chain of validated overlays."""

    schema: Schema
    overlays: tuple[Overlay, ...]

    def __init__(
        self,
        schema: Schema,
        overlays: Iterable[Overlay] = (),
    ) -> None:
        if not isinstance(schema, Schema):
            raise ConfigError("MergePlan requires a Schema instance")
        object.__setattr__(self, "schema", schema)
        object.__setattr__(self, "overlays", self._validated(overlays))

    def with_overlay(self, overlay: Overlay) -> MergePlan:
        """Return a new plan with one overlay appended."""
        return MergePlan(self.schema, (*self.overlays, overlay))

    def with_overlays(self, overlays: Iterable[Overlay]) -> MergePlan:
        """Return a new plan with overlays appended in iterable order."""
        try:
            additions = tuple(overlays)
        except TypeError as error:
            raise ConfigError(
                "with_overlays requires an iterable of Overlay objects"
            ) from error
        return MergePlan(self.schema, (*self.overlays, *additions))

    def create_object(
        self,
        *,
        initial: Any = _UNSET,
        validate: bool = True,
    ) -> Any:
        """Create a configuration from this plan.

        ``initial`` may be a partial value. By default, the result is fully
        validated after all overlays run; pass ``validate=False`` to allow
        structural ``None`` placeholders in the returned value.
        """
        from .engine import create_object

        operation_groups = tuple(overlay._operations for overlay in self.overlays)
        if initial is _UNSET:
            return create_object(
                self.schema._root,
                operation_groups,
                validate=validate,
            )
        return create_object(
            self.schema._root,
            operation_groups,
            initial=initial,
            validate=validate,
        )

    def _validated(self, overlays: Iterable[Overlay]) -> tuple[Overlay, ...]:
        try:
            candidates = tuple(overlays)
        except TypeError as error:
            raise ConfigError(
                "MergePlan overlays must be an iterable of Overlay objects"
            ) from error

        for index, overlay in enumerate(candidates):
            if not isinstance(overlay, Overlay):
                raise ConfigError(
                    f"MergePlan overlay at index {index} must be an Overlay, "
                    f"got {type(overlay).__name__}"
                )
            if overlay._schema != self.schema:
                raise ConfigError(
                    f"Overlay {overlay.name!r} was created for a different schema; "
                    "re-create it from its raw input for this schema"
                )
        return candidates

    def __repr__(self) -> str:
        return f"MergePlan(schema={self.schema!r}, overlays={self.overlays!r})"


def _operations_equal(left: _Operation, right: _Operation) -> bool:
    """Compare operation behavior while ignoring non-semantic source metadata."""
    if type(left) is not type(right):
        return False
    return all(
        field.name == "source"
        or getattr(left, field.name) == getattr(right, field.name)
        for field in fields(left)
    )
