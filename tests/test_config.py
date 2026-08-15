"""Tests for project configuration loading."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from autoinit import Config
from autoinit.config import load_config
from autoinit.errors import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path


def test_load_config_resolves_values_relative_to_project(tmp_path: Path) -> None:
    """Configuration paths resolve from the declaring project file."""
    package = tmp_path / "src" / "example"
    package.mkdir(parents=True)
    project = tmp_path / "pyproject.toml"
    project.write_text(
        """
[tool.autoinit]
roots = ["src/example"]
exclude = ["**/tests/**"]
eager = ["core.py"]
""".lstrip(),
        encoding="utf-8",
    )

    config = load_config(start=package)

    assert config == Config(
        project_file=project,
        roots=(package,),
        exclude=("**/tests/**",),
        eager=("core.py",),
    )


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ('roots = "src/example"', "roots must be an array of strings"),
        ('roots = ["src/example", "src/example"]', "roots contains duplicates"),
        ("unknown = true", "unknown [tool.autoinit] option"),
    ],
)
def test_load_config_rejects_invalid_options(
    tmp_path: Path,
    table: str,
    message: str,
) -> None:
    """Malformed and unknown options fail with actionable messages."""
    project = tmp_path / "pyproject.toml"
    project.write_text(f"[tool.autoinit]\n{table}\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=re.escape(message)):
        load_config(project)


def test_load_config_without_project_returns_defaults(tmp_path: Path) -> None:
    """Library callers may supply roots without a project configuration."""
    assert load_config(start=tmp_path) == Config()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("tool = []\n", "[tool] must be a table"),
        ("[tool]\nautoinit = []\n", "[tool.autoinit] must be a table"),
        ('[tool.autoinit]\nroots = [""]\n', "entries must be nonempty POSIX paths"),
    ],
)
def test_load_config_rejects_invalid_table_shapes(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    """Configuration tables and path values retain strict shapes."""
    project = tmp_path / "pyproject.toml"
    project.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigurationError, match=re.escape(message)):
        load_config(project)


def test_load_config_rejects_missing_explicit_file(tmp_path: Path) -> None:
    """An explicit missing configuration path is never silently ignored."""
    missing = tmp_path / "missing.toml"

    with pytest.raises(ConfigurationError, match="configuration file does not exist"):
        load_config(missing)
