"""Load and validate ``[tool.geninit]`` configuration."""

from __future__ import annotations

import os
from pathlib import Path
import tomllib
from typing import TYPE_CHECKING, Any

from packaging.specifiers import InvalidSpecifier, Specifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from geninit.errors import ConfigurationError
from geninit.models import Config

if TYPE_CHECKING:
    from collections.abc import Mapping

_NATIVE_LAZY_IMPORT_VERSION = Version("3.15")


def load_config(
    path: str | Path | None = None,
    *,
    start: str | Path | None = None,
) -> Config:
    """Load geninit configuration from a ``pyproject.toml``.

    Args:
        path: Explicit configuration file. When omitted, search upward.
        start: Directory at which upward discovery begins. Defaults to the
            current working directory.

    Returns:
        Validated configuration with absolute package roots.

    Raises:
        ConfigurationError: If the file or its geninit table is invalid.
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

    requires_python = _requires_python(project_file, document)
    tool = document.get("tool", {})
    if not isinstance(tool, dict):
        msg = f"{project_file}: [tool] must be a table"
        raise ConfigurationError(msg)
    raw = tool.get("geninit")
    if raw is None:
        return Config(
            project_file=project_file,
            requires_python=requires_python,
        )
    if not isinstance(raw, dict):
        msg = f"{project_file}: [tool.geninit] must be a table"
        raise ConfigurationError(msg)

    _reject_unknown_keys(project_file, raw)
    root_strings = _string_list(project_file, raw, "roots")
    exclude = _string_list(project_file, raw, "exclude")
    eager = _string_list(project_file, raw, "eager")
    base = project_file.parent
    roots = tuple(_absolute_path(base, root) for root in root_strings)
    if len(set(roots)) != len(roots):
        msg = f"{project_file}: tool.geninit.roots contains duplicates"
        raise ConfigurationError(msg)
    return Config(
        project_file=project_file,
        roots=roots,
        exclude=exclude,
        eager=eager,
        requires_python=requires_python,
    )


def supports_native_lazy_imports(
    requires_python: str | None,
    *,
    path: Path | None = None,
) -> bool:
    """Return whether a Python constraint proves support starts at 3.15.

    Args:
        requires_python: PEP 440 constraint from ``project.requires-python``.
        path: Optional configuration path included in validation errors.

    Returns:
        Whether native lazy-import syntax is safe for every supported version.

    Raises:
        ConfigurationError: If the constraint is not valid PEP 440 syntax.
    """
    if requires_python is None:
        return False
    try:
        specifiers = SpecifierSet(requires_python)
    except InvalidSpecifier as error:
        location = f"{path}: " if path is not None else ""
        msg = f"{location}project.requires-python is not a valid version specifier: {error}"
        raise ConfigurationError(msg) from error
    return any(_requires_python_315(specifier) for specifier in specifiers)


def _requires_python_315(specifier: Specifier) -> bool:
    if specifier.operator not in {"===", "==", ">", ">=", "~="}:
        return False
    version_text = specifier.version.removesuffix(".*")
    try:
        version = Version(version_text)
    except InvalidVersion:
        return False
    return version >= _NATIVE_LAZY_IMPORT_VERSION


def _requires_python(path: Path, document: Mapping[str, Any]) -> str | None:
    project = document.get("project")
    if project is None:
        return None
    if not isinstance(project, dict):
        msg = f"{path}: [project] must be a table"
        raise ConfigurationError(msg)
    value = project.get("requires-python")
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{path}: project.requires-python must be a string"
        raise ConfigurationError(msg)
    supports_native_lazy_imports(value, path=path)
    return value


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
        msg = f"{path}: unknown [tool.geninit] option(s): {names}"
        raise ConfigurationError(msg)


def _string_list(
    path: Path,
    raw: Mapping[str, Any],
    key: str,
) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        msg = f"{path}: tool.geninit.{key} must be an array of strings"
        raise ConfigurationError(msg)
    if any(not item or "\\" in item for item in value):
        msg = f"{path}: tool.geninit.{key} entries must be nonempty POSIX paths"
        raise ConfigurationError(msg)
    if len(set(value)) != len(value):
        msg = f"{path}: tool.geninit.{key} contains duplicates"
        raise ConfigurationError(msg)
    return tuple(value)


def _absolute_path(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    candidate = path if path.is_absolute() else base / path
    # ``Path.resolve()`` would hide a final-component package-root symlink.
    return Path(os.path.abspath(candidate))  # noqa: PTH100
