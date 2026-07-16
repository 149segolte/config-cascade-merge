# config-merger

Deterministic, schema-driven merging of an ordered sequence of Python dicts.

---

## Quick start

```python
from pathlib import Path
import yaml
from config_merger import merge

config = yaml.safe_load(Path("example_config.yaml").read_text())
result = merge(config, [layer1, layer2, layer3])
```

`merge` accepts any `Iterable[dict]` and returns a single merged `dict`.

### Running

```sh
# Demo
uv run python main.py

# Tests
uv run --group dev pytest
```
---

## How merging works

The iterable is converted into a stable list, which is folded **left-to-right**: each successive dict is merged into the accumulator produced by all preceding dicts. Input ordering is preserved throughout (insertion order of dicts, list element order, schema key order).

---

## Schema node types

Every config node must have a `type` field.

### Primitive nodes

These can be `string`, `integer`, `float`, `boolean`, or `any` types.

Primitive nodes are **always override**: the newest non-None value wins.

### `object`

A fixed-key mapping.  Keys not declared in `keys` are ignored.

```yaml
type: object
merge: append          # default
id: name               # optional – identity field
drop_prefix: "-"       # optional – default "-"
keys:
  name:
    type: string
  email:
    type: string
```

#### Merge policies for `object`

- **`append`** (default): each incoming key is merged recursively into the accumulator. A key prefixed with `drop_prefix` (e.g. `-email`) removes the unprefixed key from the accumulator instead of merging.
- **`override`**: the incoming dict entirely replaces the accumulator.

#### `id` on an object

When `id` is set, both sides must agree on that field's value before merging. Mismatched id values raise `MergeConflictError`.

### `map`

Arbitrary string keys, uniform value schema.

```yaml
type: map
merge: append          # default
drop_prefix: "-"       # optional – default "-"
value:
  type: string
```

`merge` and `drop_prefix` work the same as on `object`.

### `list`

Ordered list with a uniform item schema.

```yaml
type: list
merge: append          # default
drop_prefix: "-"       # optional – default "-"
value:
  type: string
```

Values prefixed with `drop_prefix` remove the unprefixed value from the accumulator. If value is map like instead of a string, the `drop prefix` is applied to the map's `id` field.

### `union`

Exactly one of several possible schemas; always `override`.

```yaml
type: union
merge: override        # required
value:
  - type: string
  - type: map
    merge: override
    value:
      type: any
```

When a value is merged:
- Every branch is tested structurally.
- **Zero matches** -> `MergeError`
- **More than one match** -> `AmbiguousUnionError`
- **Exactly one match** -> validated against that branch and returned.

### `tagged_union`

Dispatches on a *tag field* to select a schema branch; always `override`.

```yaml
type: tagged_union
merge: override        # required
tag:
  name: kind           # the field that carries the tag value
  options:
    tag1:              # null → no extra fields for this tag
    tag2:
      custom:
        type: list
        value:
          type: string
    tag3:
      settings:
        type: string
  keys:                # fields common to every tag variant
    name:
      type: string
```

An unknown or missing tag raises `UnknownUnionTagError`.

---

## `id` and identity matching

`id` can be placed on `object` or `map` nodes. The id field is **required** in data when declared in the schema. A missing id field raises `MissingRequiredIdError`.

---

## `drop_prefix` removal

Default prefix: `-`

Removal applies only to the *current accumulator* at the moment the incoming
item is processed.  A later input can re-introduce the field, and a further
prefixed entry is needed to remove it again.

---

## Error reference

| Exception | Cause |
|-----------|-------|
| `SchemaValidationError`        | Config schema is structurally invalid                 |
| `UnsupportedPolicyError`       | `union`/`tagged_union` declared with non-`override`   |
| `InvalidTaggedUnionConfigError`| `tagged_union` `tag` section is malformed             |
| `TypeMismatchError`            | Data value type does not match schema type            |
| `MissingRequiredIdError`       | Id field absent from a data item                      |
| `AmbiguousUnionError`          | More than one `union` branch matches                  |
| `UnknownUnionTagError`         | Tag value missing or not in `options`                 |
| `MergeConflictError`           | Object id fields disagree across merge inputs         |

All errors include a `path` attribute (dot-separated) pointing at the
offending schema or data node.
