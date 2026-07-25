# SPDX-License-Identifier: MPL-2.0

"""Public API for config-cascade-merge."""

from .api import MergePlan, create_object, load_merge_plan
from .logging import (
    ConfigError,
    MergeError,
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
from .schema import (
    ListNode,
    MapNode,
    ObjectNode,
    PrimitiveNode,
    SchemaNode,
    TaggedUnionBranch,
    TaggedUnionNode,
    UnionNode,
    parse_schema,
)
from .yaml_loader import SourceLocation, YamlLoader, load_yaml

__all__ = [
    "ClearOperation",
    "ConfigError",
    "ListNode",
    "MergeOperation",
    "MergePlan",
    "MergeError",
    "MapNode",
    "ObjectNode",
    "Operation",
    "OverlayError",
    "PrimitiveNode",
    "RemoveOperation",
    "SchemaNode",
    "SchemaError",
    "SetOperation",
    "SourceLocation",
    "TaggedUnionBranch",
    "TaggedUnionNode",
    "TestOperation",
    "UnionNode",
    "YamlLoader",
    "configure_logging",
    "create_object",
    "load_merge_plan",
    "load_overlays",
    "load_yaml",
    "logger",
    "parse_overlay",
    "parse_schema",
]
