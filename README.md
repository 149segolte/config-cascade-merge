# config-cascade-merge

A small, schema-driven YAML object merger and validator written in Python. It
loads a base schema, validates and applies ordered overlay operations, and
emits the complete configuration.

## Installation

config-cascade-merge requires Python 3.10 or newer.

```sh
python -m pip install config-cascade-merge
```

You can also install the latest development version directly from GitHub:

```sh
python -m pip install git+https://github.com/149segolte/config-cascade-merge.git
```

## Quick start

```sh
config-cascade-merge --base_config base.yaml --overlays_dir overlays/
```

The complete configuration object is written to standard output as YAML.
To select specific overlays and control their order explicitly, pass their
paths with `--overlays`:

```sh
config-cascade-merge --base_config base.yaml \
  --overlays overlays/common.yaml overlays/workstation.yaml
```

`--overlays` and `--overlays_dir` are mutually exclusive. Directory contents
are processed in lexical filename order; an explicit list is processed in the
order given.

The executable also supports short options:

```sh
config-cascade-merge -b base.yaml \
  -o overlays/common.yaml overlays/workstation.yaml
```

The module form is equivalent:

```sh
python -m config_cascade_merge -b base.yaml --overlays_dir overlays/
```

## Library usage

Create a reusable `Schema`, validate each `Overlay` against it, and compose an
immutable `MergePlan`:

```python
from config_cascade_merge import ConfigError, MergePlan, Overlay, Schema

try:
    schema = Schema.from_file("base.yaml")
    common = Overlay.from_file("overlays/common.yaml", schema)
    workstation = Overlay.from_file("overlays/workstation.yaml", schema)
    plan = MergePlan(schema).with_overlays([common, workstation])
except ConfigError as error:
    print(f"Invalid configuration: {error}")
else:
    config = plan.create_object()
    print(config)
```

`Schema`, `Overlay`, and `MergePlan` are immutable public objects. Their
factories do not configure logging or exit the calling process. Schema,
overlay, and execution failures derive from `ConfigError`, with the more
specific `SchemaError`, `OverlayError`, and `MergeError` types available when
callers need to distinguish them.

Calling `plan.create_object()` constructs the default schema-shaped object and
applies each overlay in order. Fixed object fields without values are `None`;
maps and lists start empty.

### Incremental composition and branching

Composition returns a new plan and leaves prior plans unchanged:

```python
base_plan = MergePlan(schema)
common_plan = base_plan.with_overlay(common)

workstation_plan = common_plan.with_overlay(workstation)
server_plan = common_plan.with_overlay(server)
```

`with_overlays(iterable)` appends several overlays in iterable order. The
read-only `plan.schema` and `plan.overlays` properties make plans easy to
inspect and reuse. Schemas expose their optional `source`; overlays expose
their `name`, optional `source`, and defensively copied `operations`.

### In-memory inputs

All input objects support file, YAML-text, and already-decoded forms:

```python
overlay = Overlay.from_file(path_to_overlay)
overlay = Overlay.from_yaml(yaml_text)
overlay = Overlay.from_data(
    {
        "name": "runtime",
        "operations": [
            {"action": "set", "path": ".profile.name", "data": "Ada"},
        ],
    },
    schema,
    source="runtime settings",
)
```

Use `Schema.from_file(...)`, `Schema.from_yaml(...)`, and `Schema.from_data(...)` for similar behavior. Optional `source` labels are included in validation errors.

### Starting from an existing value

Pass an existing complete configuration with `initial`:

```python
updated = plan.create_object(initial=existing_config)
```

The starting value is defensively copied and fully validated before any
overlay operation executes. Missing fields, unknown fields, and invalid types
fail immediately. Neither successful nor failed execution mutates the supplied
object.

## Base schema

The base file describes the allowed configuration shape rather than containing configuration values.

```yaml
# base.yaml
type: object
keys:
    profile:
        type: object
        keys:
            name:
                type: string
            active:
                type: boolean
                optional: true
    packages:
        type: list
        id: name
        value:
            type: object
            keys:
                name:
                    type: string
                version:
                    type: integer
    labels:
        type: map
        value:
            type: string
```

### Schema types

| Type                                           | Purpose                                    | Main fields                                          |
| ---------------------------------------------- | ------------------------------------------ | ---------------------------------------------------- |
| `string`, `integer`, `float`, `boolean`, `any` | Primitive value                            | optional `optional`                                  |
| `object`                                       | Fixed-key mapping                          | `keys`, optional `merge`, `id`, and `optional`       |
| `map`                                          | Arbitrary-key mapping with uniform values  | `value`, optional `merge`, `id`, and `optional`      |
| `list`                                         | Ordered values with a uniform item schema  | `value`, optional `merge`, `id`, and `optional`      |
| `union`                                        | Value matching one of at least two schemas | `value` (list of schemas), optional `optional`        |
| `tagged_union`                                 | Object selected by a discriminator field   | `keys`, `tag.name`, `tag.options`, optional `optional` |

The `merge` policy is either `append` (default) or `override`. An `id` identifies values for identity-based merging.

Every schema node accepts a boolean `optional` field, which defaults to
`false`. Complete objects and tagged unions may omit named fields marked
optional. Empty plans do not materialize optional object fields, and `remove`
deletes them instead of replacing them with `null`. `optional` does not allow
an explicit `null` value. On roots, list items, map values, and union branches
the flag is retained for structural equality but has no effect unless the node
is later used as a named fixed field. A field used by an object or list `id`
cannot be optional.

Example tagged union:

```yaml
type: tagged_union
keys:
    label:
        type: string
tag:
    name: kind
    options:
        file:
            path:
                type: string
        service:
            port:
                type: integer
        disabled: null
```

## Overlays

Each overlay has a non-empty name and an ordered list of operations. Paths start with `.`; `.` addresses the schema root.

```yaml
# overlays/10-workstation.yaml
name: workstation
operations:
    - action: set
      path: .profile
      data:
          name: Ada
          active: true

    - action: merge
      path: .packages
      data:
          - name: ruff
            version: 1

    - action: test
      path: .profile.name
      data: Ada
      on_fail: warn
      message: unexpected profile

    - action: remove
      path: .labels.legacy

    - action: clear
      path: .packages
```

### Operations

| Action   | Behavior                                                             | Required fields                               |
| -------- | -------------------------------------------------------------------- | --------------------------------------------- |
| `set`    | Creates or replaces a value; data must fully match the target schema | `path`, `data`                                |
| `merge`  | Validates a recursive merge into an object, map, or list             | `path`, `data`                                |
| `remove` | Deletes an optional fixed field or map entry; nulls a required field | `path`                                        |
| `test`   | Checks equality before later execution                               | `path`, `data`; optional `on_fail`, `message` |
| `clear`  | Removes all entries from a map or list                               | `path`                                        |

`test.on_fail` accepts:

- `error` — stop execution (default)
- `warn` — report the optional message and continue
- `skip` — keep prior operations from this overlay and skip the remainder
- `drop` — discard all operations from this overlay

These failure behaviors are applied to each explicit `Overlay` group while
creating the object. `drop` rolls back earlier changes from that overlay, while
`skip` preserves earlier changes and skips its remaining operations. Separate
overlay documents remain separate groups even when they use the same name.

## Validation and errors

The validator rejects malformed YAML, invalid schemas, unknown paths or fields, incompatible values, and unsupported operations. Errors include source filenames and line numbers when available:

```text
overlays/10-workstation.yaml:8: Data at '.packages[0].version' must be integer, got str
```

The CLI exits with status `1` for invalid paths, schemas, overlays, or empty
schema documents.

## Development

Clone the repository, install development dependencies, and run the test suite:

```sh
git clone https://github.com/149segolte/config-cascade-merge.git
cd config-cascade-merge
uv sync --dev
uv run pytest
```

Build both source and wheel distributions:

```sh
uv build
```

Project layout:

```text
src/config_cascade_merge/api.py         high-level library API
src/config_cascade_merge/cli.py         CLI entry point
src/config_cascade_merge/engine.py      merge-plan execution
src/config_cascade_merge/schema.py      schema parsing and normalization
src/config_cascade_merge/overlay.py     overlay loading and validation
src/config_cascade_merge/yaml_loader.py YAML loading with source locations
tests/                                  pytest test suite
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution and release process.

## License

Licensed under the [Mozilla Public License 2.0](LICENSE.txt).
