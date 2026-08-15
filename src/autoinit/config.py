"""Load and validate ``[tool.autoinit]`` configuration."""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import TYPE_CHECKING, Any

from autoinit.errors import ConfigurationError
from autoinit.models import Config

if TYPE_CHECKING:
    from collections.abc import Mapping


def load_config(
    path: str | Path | None = None,
    *,
    start: str | Path | None = None,
) -> Config:
    """Load autoinit configuration from a ``pyproject.toml``.

    Args:
        path: Explicit configuration file. When omitted, search upward.
        start: Directory at which upward discovery begins. Defaults to the
            current working directory.

    Returns:
        Validated configuration with absolute package roots.

    Raises:
        ConfigurationError: If the file or its autoinit table is invalid.
    """
    project_file = _resolve_project_file(path, start=start)
    if project_file is None:
        return Config()

    try:
        with project_file.open("rb") as stream:
            document = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        msg = f"{project_file}: cannot read configuration: {error}"
        raise ConfigurationError(msg) from error

    tool = document.get("tool", {})
    if not isinstance(tool, dict):
        msg = f"{project_file}: [tool] must be a table"
        raise ConfigurationError(msg)
    raw = tool.get("autoinit")
    if raw is None:
        return Config(project_file=project_file)
    if not isinstance(raw, dict):
        msg = f"{project_file}: [tool.autoinit] must be a table"
        raise ConfigurationError(msg)

    _reject_unknown_keys(project_file, raw)
    root_strings = _string_list(project_file, raw, "roots")
    exclude = _string_list(project_file, raw, "exclude")
    eager = _string_list(project_file, raw, "eager")
    base = project_file.parent
    roots = tuple(_absolute_path(base, root) for root in root_strings)
    if len(set(roots)) != len(roots):
        msg = f"{project_file}: tool.autoinit.roots contains duplicates"
        raise ConfigurationError(msg)
    return Config(
        project_file=project_file,
        roots=roots,
        exclude=exclude,
        eager=eager,
    )


def _resolve_project_file(
    path: str | Path | None,
    *,
    start: str | Path | None,
) -> Path | None:
    if path is not None:
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_file():
            msg = f"{candidate}: configuration file does not exist"
            raise ConfigurationError(msg)
        return candidate

    directory = Path.cwd() if start is None else Path(start).expanduser().resolve()
    if not directory.is_dir():
        msg = f"{directory}: configuration search path is not a directory"
        raise ConfigurationError(msg)
    for candidate_dir in (directory, *directory.parents):
        candidate = candidate_dir / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def _reject_unknown_keys(path: Path, raw: Mapping[str, Any]) -> None:
    unknown = sorted(set(raw) - {"roots", "exclude", "eager"})
    if unknown:
        names = ", ".join(unknown)
        msg = f"{path}: unknown [tool.autoinit] option(s): {names}"
        raise ConfigurationError(msg)


def _string_list(
    path: Path,
    raw: Mapping[str, Any],
    key: str,
) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        msg = f"{path}: tool.autoinit.{key} must be an array of strings"
        raise ConfigurationError(msg)
    if any(not item or "\\" in item for item in value):
        msg = f"{path}: tool.autoinit.{key} entries must be nonempty POSIX paths"
        raise ConfigurationError(msg)
    if len(set(value)) != len(value):
        msg = f"{path}: tool.autoinit.{key} contains duplicates"
        raise ConfigurationError(msg)
    return tuple(value)


def _absolute_path(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()
