"""Black-box tests for package analysis and generation."""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

import pytest

from autoinit import Config, plan
from autoinit.errors import AnalysisError, CollisionError, OwnershipError

if TYPE_CHECKING:
    from pathlib import Path


def test_recursive_generation_defaults_children_to_protected(tmp_path: Path) -> None:
    """Generation creates package chains and exposes modules without attributes."""
    package = tmp_path / "example"
    _module(package / "api.py", '__all__ = ("Widget",)\n\nclass Widget: ...\n')
    _module(package / "nested" / "service.py", '__all__ = ("serve",)\n')
    _module(package / "_hidden.py", '__all__ = ("secret",)\n')

    generation = plan([package])

    assert tuple(change.path.relative_to(package).as_posix() for change in generation.changes) == (
        "__init__.py",
        "nested/__init__.py",
    )
    generation.write()
    root_init = (package / "__init__.py").read_text(encoding="utf-8")
    nested_init = (package / "nested" / "__init__.py").read_text(encoding="utf-8")
    assert "lazy from . import api as api" in root_init
    assert "lazy from . import nested as nested" in root_init
    assert "Widget" not in root_init
    assert "_hidden" not in root_init
    assert "lazy from . import service as service" in nested_init
    assert not plan([package]).has_changes


def test_public_visibility_lifts_explicit_exports_and_can_be_eager(
    tmp_path: Path,
) -> None:
    """Public children lift only ``__all__`` and honor eager path patterns."""
    package = tmp_path / "example"
    _module(
        package / "api.py",
        '__all__ = ("Widget",)\n\nclass Widget: ...\n\nclass Internal: ...\n',
    )
    _managed_init(package, '__public__ = ("api",)\n')
    config = Config(roots=(package,), eager=("**/api.py",))

    generation = plan(config=config)
    generation.write()

    content = (package / "__init__.py").read_text(encoding="utf-8")
    assert "from . import api as api" in content
    assert "from .api import Widget as Widget" in content
    assert "lazy " not in content
    assert "Internal" not in content
    assert '__all__ = (\n    "api",\n    "Widget",\n)' in content


def test_exclusions_and_explicit_underscore_override(tmp_path: Path) -> None:
    """Configured globs prune trees while declarations may expose underscore names."""
    package = tmp_path / "example"
    _module(package / "_compat.py", '__all__ = ("old",)\n')
    _module(package / "tests" / "test_api.py", "value = 1\n")
    _managed_init(package, '__protected__ = ("_compat",)\n')

    generation = plan(
        config=Config(roots=(package,), exclude=("**/tests/**",)),
    )
    generation.write()

    content = (package / "__init__.py").read_text(encoding="utf-8")
    assert "_compat" in content
    assert not (package / "tests" / "__init__.py").exists()


@pytest.mark.parametrize(
    "source",
    [
        "__all__ = make_exports()\n",
        '__all__ = ("valid",)\n__all__ += ("other",)\n',
        '__all__ = ("duplicate", "duplicate")\n',
        '__all__ = ("not-valid",)\n',
    ],
)
def test_invalid_all_fails_before_writes(tmp_path: Path, source: str) -> None:
    """Unsupported export declarations abort planning without partial files."""
    package = tmp_path / "example"
    _module(package / "api.py", source)

    with pytest.raises(AnalysisError, match="__all__"):
        plan([package])

    assert not (package / "__init__.py").exists()


def test_unmanaged_nonempty_init_is_refused(tmp_path: Path) -> None:
    """Handwritten initializers require explicit ownership markers."""
    package = tmp_path / "example"
    _module(package / "api.py", "value = 1\n")
    _module(package / "__init__.py", "setup()\n")

    with pytest.raises(OwnershipError, match="nonempty files"):
        plan([package])


def test_visibility_errors_and_export_collisions(tmp_path: Path) -> None:
    """Ambiguous declarations and lifted names fail deterministically."""
    package = tmp_path / "example"
    _module(package / "one.py", '__all__ = ("Shared",)\n')
    _module(package / "two.py", '__all__ = ("Shared",)\n')
    _managed_init(package, '__public__ = ("one", "two")\n')

    with pytest.raises(CollisionError, match=r"Shared.*collides"):
        plan([package])

    _managed_init(
        package,
        '__public__ = ("one",)\n__private__ = ("one",)\n',
    )
    with pytest.raises(AnalysisError, match="overlap"):
        plan([package])


def test_unknown_visibility_child_is_rejected(tmp_path: Path) -> None:
    """Misspelled visibility declarations report their unknown child."""
    package = tmp_path / "example"
    _module(package / "api.py", "value = 1\n")
    _managed_init(package, '__public__ = ("missing",)\n')

    with pytest.raises(AnalysisError, match=r"unknown child.*missing"):
        plan([package])


def test_stale_plan_refuses_every_write(tmp_path: Path) -> None:
    """A plan cannot overwrite files changed after validation."""
    package = tmp_path / "example"
    _module(package / "api.py", "value = 1\n")
    generation = plan([package])
    init_path = package / "__init__.py"
    init_path.write_text("changed concurrently\n", encoding="utf-8")

    with pytest.raises(OwnershipError, match="changed after"):
        generation.write()

    assert init_path.read_text(encoding="utf-8") == "changed concurrently\n"


@pytest.mark.parametrize(("eager", "loaded_immediately"), [((), False), (("api.py",), True)])
def test_generated_imports_have_native_runtime_semantics(
    tmp_path: Path,
    eager: tuple[str, ...],
    loaded_immediately: bool,
) -> None:
    """Native lazy imports defer modules while configured eager imports do not."""
    package = tmp_path / "runtime_package"
    _module(
        package / "api.py",
        '__all__ = ("VALUE",)\nVALUE = 42\n',
    )
    _managed_init(package, '__public__ = ("api",)\n')
    plan(config=Config(roots=(package,), eager=eager)).write()

    sys.path.insert(0, str(tmp_path))
    try:
        imported = importlib.import_module("runtime_package")
        assert ("runtime_package.api" in sys.modules) is loaded_immediately
        assert imported.VALUE == 42
        assert "runtime_package.api" in sys.modules
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("runtime_package.api", None)
        sys.modules.pop("runtime_package", None)


def _module(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _managed_init(package: Path, declarations: str) -> Path:
    return _module(
        package / "__init__.py",
        f"{declarations}\n# <autoinit>\n__all__ = ()\n# </autoinit>\n",
    )
