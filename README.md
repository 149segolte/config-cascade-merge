# config-cascade-merge

A small, schema-driven YAML object merger and validator written in Python. It loads a base schema and validates ordered overlay operations against it.

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

The executable also supports short options:

```sh
config-cascade-merge -b base.yaml -o overlays/
```

The module form is equivalent:

```sh
python -m config_cascade_merge -b base.yaml -o overlays/
```

## Library usage

Use `load_merge_plan` to load the same validated data without invoking the
command-line interface:

```python
from config_cascade_merge import ConfigError, load_merge_plan

try:
    plan = load_merge_plan("base.yaml", "overlays/")
except ConfigError as error:
    print(f"Invalid configuration: {error}")
else:
    if plan is not None:
        print(plan.schema)
        for operation in plan.operations:
            print(operation.action, operation.path)
```

`load_merge_plan` returns a `MergePlan` containing the normalized `schema` and
the ordered, validated `operations`. An empty base file returns `None`, matching
the CLI behavior. The function does not configure logging or exit the calling
process. Schema and overlay failures derive from `ConfigError`, with the more
specific `SchemaError` and `OverlayError` types available when callers need to
distinguish them.

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

| Type                                           | Purpose                                    | Main fields                              |
| ---------------------------------------------- | ------------------------------------------ | ---------------------------------------- |
| `string`, `integer`, `float`, `boolean`, `any` | Primitive value                            | -                                        |
| `object`                                       | Fixed-key mapping                          | `keys`, optional `merge`, optional `id`  |
| `map`                                          | Arbitrary-key mapping with uniform values  | `value`, optional `merge`, optional `id` |
| `list`                                         | Ordered values with a uniform item schema  | `value`, optional `merge`, optional `id` |
| `union`                                        | Value matching one of at least two schemas | `value` (list of schemas)                |
| `tagged_union`                                 | Object selected by a discriminator field   | `keys`, `tag.name`, `tag.options`        |

The `merge` policy is either `append` (default) or `override`. An `id` identifies values for identity-based merging. These policies are normalized and validated now; merge execution is not yet implemented.

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
| `remove` | Nulls a fixed object field or deletes a dynamic map entry            | `path`                                        |
| `test`   | Checks equality before later execution                               | `path`, `data`; optional `on_fail`, `message` |
| `clear`  | Removes all entries from a map or list                               | `path`                                        |

`test.on_fail` accepts:

- `error` — stop execution (default)
- `warn` — report the optional message and continue
- `skip` — keep prior operations from this overlay and skip the remainder
- `drop` — discard all operations from this overlay

These failure behaviors are represented by normalized operations but are not executed yet.

## Validation and errors

The validator rejects malformed YAML, invalid schemas, unknown paths or fields, incompatible values, and unsupported operations. Errors include source filenames and line numbers when available:

```text
overlays/10-workstation.yaml:8: Data at '.packages[0].version' must be integer, got str
```

The CLI exits with status `1` for invalid paths, schemas, or overlays. An empty base file exits successfully without processing overlays.

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
src/config_cascade_merge/schema.py      schema parsing and normalization
src/config_cascade_merge/overlay.py     overlay loading and validation
src/config_cascade_merge/yaml_loader.py YAML loading with source locations
tests/                                  pytest test suite
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution and release process.

## License

Licensed under the [Mozilla Public License 2.0](LICENSE.txt).
