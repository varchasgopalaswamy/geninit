# geninit

Keeping `__init__.py` files up to date gets tedious once a package has more
than a few modules. geninit takes care of generating those files while still letting you
decide what belongs in your public API.

The geninit command itself requires Python 3.15 or newer, but can generate eager
`__init__.py` files for projects that support older Python versions.

## Installation

The simplest way to install geninit is as an isolated uv tool:

```console
uv tool install --python 3.15 geninit
```

You can then run `geninit` from any project. If you only want to try it once,
use `uvx` instead:

```console
uvx --python 3.15 geninit --check
```

For a project that keeps its development tools in `uv.lock`, add geninit to the
development dependency group:

```console
uv add --dev geninit
```

Commands in the rest of this README can then be written as
`uv run --locked --no-sync geninit ...`.

## Getting started

Add a `[tool.geninit]` table to your `pyproject.toml` and list the packages you
want geninit to manage:

```toml
[project]
requires-python = ">=3.14"

[tool.geninit]
roots = ["src/acme"]
```

Run geninit from the directory containing `pyproject.toml`:

```console
geninit
```

The first run creates the necessary `__init__.py` files. Later runs update the
managed sections when modules or exports change.

You can also pass additional package roots on the command line:

```console
geninit src/acme_plugins
```

Command-line roots are added to the roots from `pyproject.toml`.

## Choosing what to export

By default, a normal child module is protected: the package exposes the module
itself, but does not copy names from that module into the package namespace.
Modules whose names start with an underscore are private by default.

Use these declarations in the handwritten part of `__init__.py` when you want
different behavior:

```python
__public__ = ("api",)
__protected__ = ("models",)
__private__ = ("legacy",)

# <geninit>
# </geninit>
```

- A public child exposes the module and the names listed in that child's
  `__all__`.
- A protected child exposes only the module.
- A private child is not exposed by the package.

For example, `src/acme/api.py` might contain:

```python
__all__ = ("Client", "connect")


class Client: ...


def connect() -> Client:
    return Client()
```

With `api` declared public, users can then write either
`from acme import Client` or `from acme import api`.

The `__public__`, `__protected__`, `__private__`, and child `__all__`
declarations must contain literal strings. geninit reports an error for unknown
children, duplicate names, overlapping declarations, or conflicting exports.

## Managed files

geninit only replaces content between these markers:

```python
# <geninit>
# </geninit>
```

New and empty `__init__.py` files are generated automatically. geninit will not
overwrite a nonempty file unless it already contains exactly one matching pair
of markers. To adapt an existing `__init__.py` file, add the empty marker pair where
you want the generated section to appear, then run geninit.

## Excluding files and forcing eager imports

`exclude` removes matching paths from discovery. `eager` forces selected
modules to use ordinary eager imports:

```toml
[tool.geninit]
roots = ["src/acme"]
exclude = ["**/tests/**", "**/fixtures/**"]
eager = ["core.py", "plugins/builtin.py"]
```

Both options use paths relative to their package root.

geninit reads `[project].requires-python` to decide which import syntax is
safe. If every supported version is Python 3.15 or newer, imports are lazy
unless they match `eager`. If the project supports an earlier version, or the
version constraint is missing, all generated imports are eager.

## Checking without changing files

Use `--check` in CI or whenever you only want to verify that the generated
files are current:

```console
geninit --check
```

Use `--diff` to print the changes geninit would make:

```console
geninit --diff
```

The command uses these exit codes:

- `0` means every managed file was already current.
- `1` means configuration, input, or generation failed.
- `2` means files were changed, or `--check`/`--diff` found stale files.

The normal write command deliberately exits with status 2 after changing
files. This makes generated changes visible in pre-commit hooks instead of
letting a commit continue with unstaged output.

## Using geninit with prek or pre-commit

For a uv-managed project, add this local hook to your pre-commit config:

```toml
[[repos]]
repo = "local"

[[repos.hooks]]
id = "geninit"
name = "Generate package initializers"
entry = "uv run --locked --no-sync geninit"
language = "system"
pass_filenames = false
always_run = true
stages = ["pre-commit"]
```

`pass_filenames = false` is important: geninit works from package roots rather
than a list of staged files. `always_run = true` makes sure module deletions and
configuration-only changes are noticed too.

If the hook updates anything, review the changes, stage them, and commit again.

If you are using `ruff` to format and lint your code, be sure to put `geninit` before `ruff` in pre-commit. Then, make sure ruff is available in the hook environment so that geninit can use the target project's
Ruff configuration to format and sort the generated section.

## CI example

A typical uv-based CI job can verify generated files before running the rest
of the checks:

```console
uv sync --locked
uv run --locked --no-sync geninit --check
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync ruff check .
```

If an initializer is stale, `geninit --check` exits with status 2 and the job
fails without modifying the checkout.
