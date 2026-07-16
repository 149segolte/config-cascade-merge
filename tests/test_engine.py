"""Tests for config_merger.engine – Phases 2–5: merge execution."""

from __future__ import annotations

import pytest

from config_merger import merge
from config_merger.errors import (
    AmbiguousUnionError,
    MergeConflictError,
    MergeError,
    MissingRequiredIdError,
    TypeMismatchError,
    UnknownUnionTagError,
)

# ---------------------------------------------------------------------------
# Helpers: small inline schemas
# ---------------------------------------------------------------------------

STR_OBJ = {"type": "object", "keys": {"x": {"type": "string"}}}
TWO_KEY_OBJ = {
    "type": "object",
    "keys": {"x": {"type": "string"}, "y": {"type": "string"}},
}
INT_OBJ = {"type": "object", "keys": {"n": {"type": "integer"}}}
BOOL_OBJ = {"type": "object", "keys": {"flag": {"type": "boolean"}}}
FLOAT_OBJ = {"type": "object", "keys": {"v": {"type": "float"}}}

STRING_MAP = {
    "type": "map",
    "merge": "append",
    "value": {"type": "string"},
}

STRING_LIST = {
    "type": "list",
    "merge": "append",
    "value": {"type": "string"},
}

NAMED_ITEM_LIST = {
    "type": "list",
    "merge": "append",
    "id": "name",
    "value": {
        "type": "object",
        "keys": {
            "name": {"type": "string"},
            "value": {"type": "string"},
        },
    },
}

STR_INT_UNION = {
    "type": "union",
    "merge": "override",
    "value": [{"type": "string"}, {"type": "integer"}],
}

SIMPLE_TAGGED_UNION = {
    "type": "tagged_union",
    "merge": "override",
    "tag": {
        "name": "kind",
        "options": {
            "alpha": None,
            "beta": {"extra": {"type": "string"}},
        },
        "keys": {"name": {"type": "string"}},
    },
}

# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_empty_iterable_returns_empty_dict():
    assert merge(STR_OBJ, []) == {}


# ---------------------------------------------------------------------------
# Primitive override semantics
# ---------------------------------------------------------------------------


def test_single_item_string():
    assert merge(STR_OBJ, [{"x": "hello"}]) == {"x": "hello"}


def test_primitive_string_override():
    assert merge(STR_OBJ, [{"x": "first"}, {"x": "second"}]) == {"x": "second"}


def test_primitive_integer():
    assert merge(INT_OBJ, [{"n": 1}, {"n": 2}]) == {"n": 2}


def test_primitive_float():
    assert merge(FLOAT_OBJ, [{"v": 1.5}, {"v": 3.14}]) == {"v": 3.14}


def test_primitive_boolean():
    assert merge(BOOL_OBJ, [{"flag": False}, {"flag": True}]) == {"flag": True}


def test_none_incoming_keeps_acc():
    """None in incoming data is treated as absent – accumulator wins."""
    assert merge(STR_OBJ, [{"x": "keep"}, {"x": None}]) == {"x": "keep"}


# ---------------------------------------------------------------------------
# Object – append policy
# ---------------------------------------------------------------------------


def test_object_append_disjoint_keys():
    """Keys from different inputs should accumulate."""
    assert merge(TWO_KEY_OBJ, [{"x": "a"}, {"y": "b"}]) == {"x": "a", "y": "b"}


def test_object_append_shared_key_overrides():
    """For a shared key, the nested schema decides (strings override)."""
    assert merge(TWO_KEY_OBJ, [{"x": "a", "y": "1"}, {"x": "b"}]) == {
        "x": "b",
        "y": "1",
    }


def test_object_override_policy():
    cfg = {
        "type": "object",
        "merge": "override",
        "keys": {"x": {"type": "string"}, "y": {"type": "string"}},
    }
    result = merge(cfg, [{"x": "a", "y": "1"}, {"x": "b"}])
    # override: second input entirely replaces; 'y' is not in second input
    assert result == {"x": "b"}


# ---------------------------------------------------------------------------
# Object – drop prefix
# ---------------------------------------------------------------------------


def test_object_drop_prefix_removes_key():
    result = merge(TWO_KEY_OBJ, [{"x": "hello", "y": "world"}, {"-x": True}])
    assert "x" not in result
    assert result["y"] == "world"


def test_object_drop_prefix_with_custom_prefix():
    cfg = {
        "type": "object",
        "drop_prefix": "~",
        "keys": {"x": {"type": "string"}, "y": {"type": "string"}},
    }
    result = merge(cfg, [{"x": "a", "y": "b"}, {"~x": True}])
    assert "x" not in result
    assert result["y"] == "b"


def test_object_drop_prefix_nonexistent_key_is_noop():
    """Dropping a key that doesn't exist in the accumulator is silently ignored."""
    result = merge(TWO_KEY_OBJ, [{"y": "b"}, {"-x": True}])
    assert result == {"y": "b"}


# ---------------------------------------------------------------------------
# Object – id guard
# ---------------------------------------------------------------------------


def test_object_id_guard_same_id_ok():
    cfg = {
        "type": "object",
        "id": "name",
        "keys": {"name": {"type": "string"}, "email": {"type": "string"}},
    }
    result = merge(
        cfg,
        [
            {"name": "Alice", "email": "a@x.com"},
            {"name": "Alice", "email": "a@y.com"},
        ],
    )
    assert result == {"name": "Alice", "email": "a@y.com"}


def test_object_id_guard_conflict_raises():
    cfg = {
        "type": "object",
        "id": "name",
        "keys": {"name": {"type": "string"}, "email": {"type": "string"}},
    }
    with pytest.raises(MergeConflictError):
        merge(
            cfg,
            [
                {"name": "Alice", "email": "a@x.com"},
                {"name": "Bob", "email": "b@y.com"},
            ],
        )


# ---------------------------------------------------------------------------
# Map – append policy
# ---------------------------------------------------------------------------


def test_map_append_accumulates_keys():
    cfg = {"type": "object", "keys": {"m": STRING_MAP}}
    result = merge(
        cfg,
        [
            {"m": {"a": "1", "b": "2"}},
            {"m": {"b": "3", "c": "4"}},
        ],
    )
    assert result["m"] == {"a": "1", "b": "3", "c": "4"}


def test_map_override_replaces_completely():
    cfg = {
        "type": "object",
        "keys": {
            "m": {"type": "map", "merge": "override", "value": {"type": "string"}},
        },
    }
    result = merge(
        cfg,
        [
            {"m": {"a": "1", "b": "2"}},
            {"m": {"c": "3"}},
        ],
    )
    assert result["m"] == {"c": "3"}


# ---------------------------------------------------------------------------
# Map – drop prefix
# ---------------------------------------------------------------------------


def test_map_drop_prefix_removes_key():
    cfg = {"type": "object", "keys": {"m": STRING_MAP}}
    result = merge(
        cfg,
        [
            {"m": {"a": "keep", "b": "remove"}},
            {"m": {"-b": "anything"}},
        ],
    )
    assert result["m"] == {"a": "keep"}


def test_map_drop_prefix_nonexistent_is_noop():
    cfg = {"type": "object", "keys": {"m": STRING_MAP}}
    result = merge(
        cfg,
        [
            {"m": {"a": "keep"}},
            {"m": {"-z": "anything"}},
        ],
    )
    assert result["m"] == {"a": "keep"}


# ---------------------------------------------------------------------------
# List – no id (plain append)
# ---------------------------------------------------------------------------


def test_list_no_id_appends_all():
    cfg = {"type": "object", "keys": {"items": STRING_LIST}}
    result = merge(
        cfg,
        [
            {"items": ["a", "b"]},
            {"items": ["c"]},
        ],
    )
    assert result["items"] == ["a", "b", "c"]


def test_list_no_id_three_inputs():
    cfg = {"type": "object", "keys": {"items": STRING_LIST}}
    result = merge(
        cfg,
        [
            {"items": ["a"]},
            {"items": ["b"]},
            {"items": ["c"]},
        ],
    )
    assert result["items"] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# List – with id (identity-based merge)
# ---------------------------------------------------------------------------


def test_list_with_id_merges_existing_item():
    result = merge(
        {"type": "object", "keys": {"items": NAMED_ITEM_LIST}},
        [
            {"items": [{"name": "a", "value": "1"}]},
            {"items": [{"name": "a", "value": "2"}]},
        ],
    )
    assert result["items"] == [{"name": "a", "value": "2"}]


def test_list_with_id_appends_new_item():
    result = merge(
        {"type": "object", "keys": {"items": NAMED_ITEM_LIST}},
        [
            {"items": [{"name": "a", "value": "1"}]},
            {"items": [{"name": "b", "value": "2"}]},
        ],
    )
    assert [i["name"] for i in result["items"]] == ["a", "b"]


def test_list_with_id_preserves_input_order():
    result = merge(
        {"type": "object", "keys": {"items": NAMED_ITEM_LIST}},
        [
            {"items": [{"name": "z", "value": "z"}, {"name": "a", "value": "a"}]},
            {"items": [{"name": "m", "value": "m"}]},
        ],
    )
    assert [i["name"] for i in result["items"]] == ["z", "a", "m"]


# ---------------------------------------------------------------------------
# List – drop prefix
# ---------------------------------------------------------------------------


def test_list_drop_prefix_removes_existing_item():
    result = merge(
        {"type": "object", "keys": {"items": NAMED_ITEM_LIST}},
        [
            {"items": [{"name": "a", "value": "1"}, {"name": "b", "value": "2"}]},
            {"items": [{"name": "-a", "value": ""}]},
        ],
    )
    assert [i["name"] for i in result["items"]] == ["b"]


def test_list_drop_prefix_nonexistent_is_noop():
    result = merge(
        {"type": "object", "keys": {"items": NAMED_ITEM_LIST}},
        [
            {"items": [{"name": "a", "value": "1"}]},
            {"items": [{"name": "-z", "value": ""}]},
        ],
    )
    assert [i["name"] for i in result["items"]] == ["a"]


def test_list_drop_prefix_then_reintroduce():
    """After dropping, later inputs may reintroduce the item."""
    result = merge(
        {"type": "object", "keys": {"items": NAMED_ITEM_LIST}},
        [
            {"items": [{"name": "a", "value": "original"}]},
            {"items": [{"name": "-a", "value": ""}]},  # remove
            {"items": [{"name": "a", "value": "reborn"}]},  # add again
        ],
    )
    assert result["items"] == [{"name": "a", "value": "reborn"}]


# ---------------------------------------------------------------------------
# Union
# ---------------------------------------------------------------------------


def test_union_selects_string_branch():
    assert merge(STR_INT_UNION, ["hello"]) == "hello"


def test_union_selects_integer_branch():
    assert merge(STR_INT_UNION, [42]) == 42


def test_union_override_latest_wins():
    assert merge(STR_INT_UNION, ["first", "second"]) == "second"


def test_union_no_match_raises():
    with pytest.raises(MergeError, match="No union branch"):
        merge(STR_INT_UNION, [[1, 2, 3]])  # list matches neither branch


def test_union_ambiguous_raises():
    # Both branches are 'any', so every value matches two branches.
    cfg = {
        "type": "union",
        "merge": "override",
        "value": [{"type": "any"}, {"type": "any"}],
    }
    with pytest.raises(AmbiguousUnionError):
        merge(cfg, ["hello"])


# ---------------------------------------------------------------------------
# Tagged union
# ---------------------------------------------------------------------------


def test_tagged_union_alpha_branch():
    cfg = {"type": "object", "keys": {"pkg": SIMPLE_TAGGED_UNION}}
    result = merge(cfg, [{"pkg": {"kind": "alpha", "name": "foo"}}])
    assert result["pkg"] == {"kind": "alpha", "name": "foo"}


def test_tagged_union_beta_branch_extra_key():
    cfg = {"type": "object", "keys": {"pkg": SIMPLE_TAGGED_UNION}}
    result = merge(cfg, [{"pkg": {"kind": "beta", "name": "bar", "extra": "hi"}}])
    assert result["pkg"]["extra"] == "hi"


def test_tagged_union_override_replaces():
    cfg = {"type": "object", "keys": {"pkg": SIMPLE_TAGGED_UNION}}
    result = merge(
        cfg,
        [
            {"pkg": {"kind": "alpha", "name": "first"}},
            {"pkg": {"kind": "beta", "name": "second", "extra": "x"}},
        ],
    )
    assert result["pkg"]["kind"] == "beta"
    assert result["pkg"]["name"] == "second"


def test_tagged_union_missing_tag_raises():
    cfg = {"type": "object", "keys": {"pkg": SIMPLE_TAGGED_UNION}}
    with pytest.raises(UnknownUnionTagError):
        merge(cfg, [{"pkg": {"name": "foo"}}])  # missing 'kind'


def test_tagged_union_unknown_tag_raises():
    cfg = {"type": "object", "keys": {"pkg": SIMPLE_TAGGED_UNION}}
    with pytest.raises(UnknownUnionTagError):
        merge(cfg, [{"pkg": {"kind": "gamma", "name": "foo"}}])


# ---------------------------------------------------------------------------
# Type mismatch errors
# ---------------------------------------------------------------------------


def test_type_mismatch_string_expects_int():
    with pytest.raises(TypeMismatchError, match="integer"):
        merge(INT_OBJ, [{"n": "not-an-int"}])


def test_type_mismatch_bool_is_not_integer():
    """bool is a subclass of int in Python; we reject it for 'integer'."""
    with pytest.raises(TypeMismatchError, match="integer"):
        merge(INT_OBJ, [{"n": True}])


def test_type_mismatch_object_expects_dict():
    with pytest.raises(TypeMismatchError, match="object"):
        merge(STR_OBJ, ["not-a-dict"])


# ---------------------------------------------------------------------------
# Missing id field
# ---------------------------------------------------------------------------


def test_missing_id_in_list_item():
    with pytest.raises(MissingRequiredIdError):
        merge(
            {"type": "object", "keys": {"items": NAMED_ITEM_LIST}},
            [{"items": [{"value": "no-name-here"}]}],
        )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_deterministic_output(example_config):
    """Identical inputs must always produce identical outputs."""
    inputs = [
        {
            "environment": {
                "packages": [
                    {"kind": "brew", "name": "git"},
                    {"kind": "mise", "name": "node", "version": "20.0.0"},
                ],
                "shell": {"aliases": {"gs": "git status"}},
            }
        },
        {
            "environment": {
                "packages": [{"kind": "brew", "name": "ripgrep"}],
                "shell": {"aliases": {"gl": "git log"}},
            }
        },
    ]
    result1 = merge(example_config, inputs)
    result2 = merge(example_config, inputs)
    assert result1 == result2


# ---------------------------------------------------------------------------
# Full integration test against example_config.yaml
# ---------------------------------------------------------------------------


def test_full_example_config_merge(example_config):
    input1 = {
        "data": {
            "user": {"name": "Alice", "email": "alice@example.com"},
        },
        "environment": {
            "packages": [
                {"kind": "brew", "name": "git"},
                {"kind": "mise", "name": "node", "version": "20.0.0"},
                {
                    "kind": "custom",
                    "name": "dotfiles",
                    "files": ["~/.zshrc", "~/.vimrc"],
                },
            ],
            "shell": {
                "aliases": {"gs": "git status"},
                "config": ["set -e"],
            },
        },
        "modules": {
            "work": {"theme": "dark"},
        },
    }
    input2 = {
        "environment": {
            "packages": [
                {"kind": "brew", "name": "ripgrep"},
                # Same name as input1 → override (tagged_union is override)
                {"kind": "mise", "name": "node", "version": "22.0.0"},
            ],
            "shell": {
                "aliases": {"gl": "git log"},
                "abbreviations": {"gco": "git checkout"},
            },
        },
        "modules": {
            "personal": {"theme": "light"},
            "work": {"font-size": 14},
        },
    }

    result = merge(example_config, [input1, input2])

    # ---- data ----
    assert result["data"]["user"]["name"] == "Alice"
    assert result["data"]["user"]["email"] == "alice@example.com"

    # ---- packages ----
    packages = result["environment"]["packages"]
    pkg_by_name = {p["name"]: p for p in packages}
    assert set(pkg_by_name) == {"git", "node", "dotfiles", "ripgrep"}
    # node was overridden by input2
    assert pkg_by_name["node"]["version"] == "22.0.0"
    assert pkg_by_name["node"]["kind"] == "mise"
    # custom package preserved its files
    assert "~/.zshrc" in pkg_by_name["dotfiles"]["files"]

    # ---- shell ----
    aliases = result["environment"]["shell"]["aliases"]
    assert aliases["gs"] == "git status"
    assert aliases["gl"] == "git log"
    assert result["environment"]["shell"]["abbreviations"]["gco"] == "git checkout"
    assert result["environment"]["shell"]["config"] == ["set -e"]

    # ---- modules ----
    modules = result["modules"]
    assert modules["work"]["theme"] == "dark"
    assert modules["work"]["font-size"] == 14
    assert modules["personal"]["theme"] == "light"


def test_drop_package_via_prefix(example_config):
    """Removing a list item by name via the drop prefix."""
    input1 = {
        "environment": {
            "packages": [
                {"kind": "brew", "name": "git"},
                {"kind": "brew", "name": "curl"},
            ]
        }
    }
    input2 = {
        "environment": {
            "packages": [{"kind": "brew", "name": "-git"}]  # remove git
        }
    }
    result = merge(example_config, [input1, input2])
    names = [p["name"] for p in result["environment"]["packages"]]
    assert "git" not in names
    assert "curl" in names


def test_union_version_in_mise_package(example_config):
    """The 'mise' version field supports both string and map."""
    # String version
    result_str = merge(
        example_config,
        [
            {
                "environment": {
                    "packages": [
                        {"kind": "mise", "name": "python", "version": "3.13.0"}
                    ]
                }
            }
        ],
    )
    node = next(
        p for p in result_str["environment"]["packages"] if p["name"] == "python"
    )
    assert node["version"] == "3.13.0"

    # Map version
    result_map = merge(
        example_config,
        [
            {
                "environment": {
                    "packages": [
                        {"kind": "mise", "name": "python", "version": {"system": True}}
                    ]
                }
            }
        ],
    )
    node = next(
        p for p in result_map["environment"]["packages"] if p["name"] == "python"
    )
    assert node["version"] == {"system": True}
