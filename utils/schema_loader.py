"""YAML loading helpers for schema files.

The schema parser needs source locations for friendly validation errors. This
module wraps PyYAML's safe loader so mappings and sequences retain their
originating file name and line numbers.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode, SequenceNode


@dataclass(frozen=True)
class SchemaLocation:
    file_name: str | None = None
    line_number: int | None = None


class _MarkedDict(dict):
    """A YAML mapping with source-line metadata attached by SchemaLoader."""

    yaml_file_name: str | None
    yaml_line_number: int
    yaml_key_line_numbers: dict[Any, int]
    yaml_value_line_numbers: dict[Any, int]


class _MarkedList(list):
    """A YAML sequence with source-line metadata attached by SchemaLoader."""

    yaml_file_name: str | None
    yaml_line_number: int
    yaml_item_line_numbers: dict[int, int]


class SchemaLoader(yaml.SafeLoader):
    """YAML loader that preserves mapping and sequence line numbers."""

    def __init__(self, stream: Any, file_name: str | Path | None = None) -> None:
        super().__init__(stream)
        self.schema_file_name = str(file_name) if file_name is not None else None


def _construct_mapping(loader: SchemaLoader, node: MappingNode) -> _MarkedDict:
    loader.flatten_mapping(node)
    mapping = _MarkedDict()
    mapping.yaml_file_name = loader.schema_file_name
    mapping.yaml_line_number = node.start_mark.line + 1
    mapping.yaml_key_line_numbers = {}
    mapping.yaml_value_line_numbers = {}

    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, Hashable):
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found unhashable key",
                key_node.start_mark,
            )

        value = loader.construct_object(value_node)
        mapping[key] = value
        mapping.yaml_key_line_numbers[key] = key_node.start_mark.line + 1
        mapping.yaml_value_line_numbers[key] = value_node.start_mark.line + 1

    return mapping


def _construct_sequence(loader: SchemaLoader, node: SequenceNode) -> _MarkedList:
    sequence = _MarkedList()
    sequence.yaml_file_name = loader.schema_file_name
    sequence.yaml_line_number = node.start_mark.line + 1
    sequence.yaml_item_line_numbers = {}

    for index, child in enumerate(node.value):
        sequence.append(loader.construct_object(child))
        sequence.yaml_item_line_numbers[index] = child.start_mark.line + 1

    return sequence


SchemaLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)
SchemaLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_SEQUENCE_TAG,
    _construct_sequence,
)


def load_schema_yaml(source: str, file_name: str | Path | None = None) -> Any:
    """Load a schema YAML document while preserving source-line metadata."""

    loader = SchemaLoader(source, file_name)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def node_location(
    value: Any, fallback: SchemaLocation | None = None
) -> SchemaLocation | None:
    if isinstance(value, _MarkedDict | _MarkedList):
        return SchemaLocation(value.yaml_file_name, value.yaml_line_number)
    return fallback


def field_location(
    config: dict,
    field_name: str,
    fallback: SchemaLocation | None = None,
) -> SchemaLocation | None:
    if isinstance(config, _MarkedDict):
        line_number = config.yaml_value_line_numbers.get(field_name)
        if line_number is None:
            line_number = config.yaml_key_line_numbers.get(field_name)
        if line_number is not None:
            return SchemaLocation(config.yaml_file_name, line_number)

    return fallback if fallback is not None else node_location(config)


def item_location(
    sequence: list,
    index: int,
    fallback: SchemaLocation | None = None,
) -> SchemaLocation | None:
    if isinstance(sequence, _MarkedList):
        line_number = sequence.yaml_item_line_numbers.get(index)
        if line_number is not None:
            return SchemaLocation(sequence.yaml_file_name, line_number)

    return fallback if fallback is not None else node_location(sequence)
