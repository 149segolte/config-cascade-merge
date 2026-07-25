# Contributing

Thanks for contributing to config-merger.

## Development setup

Install [uv](https://docs.astral.sh/uv/), then create the development environment:

```sh
git clone https://github.com/149segolte/config-merger.git
cd config-merger
uv sync --dev
```

Run the tests before opening a pull request:

```sh
uv run pytest
uv build
```

Keep changes focused, add tests for changed behavior.

## Releasing

Releases are currently built and published manually.

### Prerequisites

- A PyPI account with permission to publish `config-merger`.
- A PyPI API token with permission to publish the project. The first upload may require an account-scoped token; replace it with a project-scoped token after the project exists on PyPI.
- A clean checkout of the `main` branch.

Use `__token__` as the Twine username and the complete API token, including its `pypi-` prefix, as the password. Do not store the token in the repository.

### Prepare the release

1. Update `project.version` in `pyproject.toml`.
2. Refresh the lockfile and run the test suite:

    ```sh
    uv lock
    uv sync --locked --dev
    uv run pytest
    ```

3. Commit the version and lockfile; merge them to `main`, and update the local branch:

    ```sh
    git switch main
    git pull --ff-only
    ```

### Tag and publish

Build fresh distributions from the updated `main` branch:

```sh
rm -rf dist/
uv build
uvx twine check --strict dist/*
```

Confirm that `dist/` contains exactly one wheel and one source distribution for the new version. Then replace `X.Y.Z` below with the release version:

```sh
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
uvx twine upload dist/*
```

After the upload succeeds, verify the files and metadata on the PyPI project page. PyPI releases cannot be overwritten, so verify the version and artifact names before uploading.

### Create the GitHub release

1. Open the repository's **Releases** page and choose **Draft a new release**.
2. Select the existing `vX.Y.Z` tag and use `vX.Y.Z` as the release title.
3. Copy the version's notes from `CHANGELOG.md` into the description.
4. Attach the wheel and source distribution from `dist/`.
5. Publish the release.

Finally, test installation from PyPI in a fresh environment:

```sh
uv venv /tmp/config-merger-release-check
uv pip install \
  --python /tmp/config-merger-release-check/bin/python \
  config-merger==X.Y.Z
/tmp/config-merger-release-check/bin/config-merger --help
```
