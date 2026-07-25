# SPDX-License-Identifier: MPL-2.0

"""High-level library API for loading a validated merge plan."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .logging import SchemaError
from .overlay import Operation, load_overlays
from .schema import SchemaNode, parse_schema
from .yaml_loader import SourceLocation, load_yaml


@dataclass(frozen=True)
class MergePlan:
    """A normalized schema and its ordered, validated overlay operations."""

    schema: SchemaNode
    operations: tuple[Operation, ...]


def load_merge_plan(
    base_config: str | Path,
    overlays_dir: str | Path,
) -> MergePlan | None:
    """Load and validate a schema and all overlay files.

    Args:
        base_config: Path to the YAML schema file.
        overlays_dir: Directory containing ordered YAML overlay files.

    Returns:
        A merge plan containing the normalized schema and operations. An empty
        schema file returns ``None``.

    Raises:
        SchemaError: The schema cannot be read, parsed, or normalized.
        OverlayError: The overlay directory or one of its files is invalid.

    This function is safe to call from another application: it does not
    configure logging or terminate the process.
    """
    base_path = Path(base_config)
    location = SourceLocation(str(base_path))

    try:
        source = base_path.read_text(encoding="utf-8")
        document = load_yaml(source, file_name=base_path)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise SchemaError(f"Could not read schema: {error}", location) from error

    if document is None:
        return None

    schema = parse_schema(document, location=location)
    operations = load_overlays(overlays_dir, schema)
    return MergePlan(schema=schema, operations=tuple(operations))
