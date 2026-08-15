"""Black-box tests for package analysis and generation."""

from __future__ import annotations

import importlib
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from autoinit import Config, plan
from autoinit.errors import (
    AnalysisError,
    CollisionError,
    ConfigurationError,
    OwnershipError,
)


def test_recursive_generation_defaults_children_to_protected(tmp_path: Path) -> None:
    """Generation creates package chains and exposes modules without attributes."""
    package = tmp_path / "example"
    _module(package / "api.py", '__all__ = ("Widget",)\n\nclass Widget: ...\n')
    _module(package / "nested" / "service.py", '__all__ = ("serve",)\n')
    _module(package / "_hidden.py", '__all__ = ("secret",)\n')

    config = Config(roots=(package,), requires_python=">=3.15")
    generation = plan(config=config)

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
    assert not plan(config=config).has_changes


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
    assert '__all__ = (\n    "Widget",\n    "api",\n)' in content


def test_public_subpackage_propagates_its_generated_api(tmp_path: Path) -> None:
    """Bottom-up planning lets a public subpackage lift its generated exports."""
    package = tmp_path / "example"
    subpackage = package / "features"
    _module(subpackage / "api.py", '__all__ = ("Widget",)\nclass Widget: ...\n')
    _managed_init(subpackage, '__public__ = ("api",)\n')
    _managed_init(package, '__public__ = ("features",)\n')

    generation = plan(
        config=Config(roots=(package,), requires_python=">=3.15"),
    )
    generation.write()

    root_content = (package / "__init__.py").read_text(encoding="utf-8")
    assert "lazy from . import features as features" in root_content
    assert "lazy from .features import api as api" in root_content
    assert "lazy from .features import Widget as Widget" in root_content
    assert '__all__ = (\n    "Widget",\n    "api",\n    "features",\n)' in root_content


def test_generation_preserves_content_outside_the_managed_block(tmp_path: Path) -> None:
    """Regeneration replaces only the marked block, byte for byte."""
    package = tmp_path / "example"
    _module(package / "api.py", '__all__ = ("Widget",)\n')
    before = (
        '"""Handwritten package documentation."""\n\n'
        '__public__ = ("api",)\n\n'
        "# <autoinit>\n"
        "stale = True\n"
        "# </autoinit>\n\n"
        "HANDWRITTEN = 42\n"
    )
    _module(package / "__init__.py", before)

    plan(
        config=Config(roots=(package,), requires_python=">=3.15"),
    ).write()

    after = (package / "__init__.py").read_text(encoding="utf-8")
    prefix, managed_and_suffix = after.split("# <autoinit>", maxsplit=1)
    _, suffix = managed_and_suffix.split("# </autoinit>\n", maxsplit=1)
    assert prefix == before.split("# <autoinit>", maxsplit=1)[0]
    assert suffix == before.split("# </autoinit>\n", maxsplit=1)[1]
    assert "stale = True" not in after
    assert "lazy from .api import Widget as Widget" in after


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


def test_private_visibility_hides_normal_child_and_publicizes_underscore_child(
    tmp_path: Path,
) -> None:
    """Explicit declarations override both visibility defaults."""
    package = tmp_path / "example"
    _module(package / "api.py", '__all__ = ("Widget",)\n')
    _module(package / "_compat.py", '__all__ = ("legacy",)\n')
    _managed_init(
        package,
        '__public__ = ("_compat",)\n__private__ = ("api",)\n',
    )

    plan(
        config=Config(roots=(package,), requires_python=">=3.15"),
    ).write()

    content = (package / "__init__.py").read_text(encoding="utf-8")
    assert "from . import api" not in content
    assert "Widget as Widget" not in content
    assert "lazy from . import _compat as _compat" in content
    assert "lazy from ._compat import legacy as legacy" in content
    assert '__all__ = (\n    "_compat",\n    "legacy",\n)' in content


def test_discovery_ignores_standard_directories_and_directory_symlinks(
    tmp_path: Path,
) -> None:
    """Discovery never follows generated trees or directory symlinks."""
    package = tmp_path / "example"
    external = tmp_path / "external"
    _module(package / "api.py", "value = 1\n")
    _module(package / "build" / "generated.py", "value = 2\n")
    _module(external / "linked.py", "value = 3\n")
    (package / "linked").symlink_to(external, target_is_directory=True)

    plan([package]).write()

    assert (package / "__init__.py").is_file()
    assert not (package / "build" / "__init__.py").exists()
    assert not (external / "__init__.py").exists()


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


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("# <autoinit>\n__all__ = ()\n", "must contain exactly one"),
        ("# </autoinit>\n# <autoinit>\n", "markers are out of order"),
    ],
)
def test_malformed_managed_markers_are_rejected(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    """Incomplete or reversed ownership markers cannot authorize a rewrite."""
    package = tmp_path / "example"
    _module(package / "api.py", "value = 1\n")
    _module(package / "__init__.py", source)

    with pytest.raises(OwnershipError, match=message):
        plan([package])


def test_invalid_utf8_and_initializer_directories_report_analysis_errors(
    tmp_path: Path,
) -> None:
    """Unreadable Python inputs fail with paths and domain-specific errors."""
    invalid_source = tmp_path / "invalid_source"
    invalid_source.mkdir()
    (invalid_source / "api.py").write_bytes(b"\xff")

    with pytest.raises(AnalysisError, match=r"api\.py: cannot decode Python source as UTF-8"):
        plan([invalid_source])

    invalid_initializer = tmp_path / "invalid_initializer"
    _module(invalid_initializer / "api.py", "value = 1\n")
    (invalid_initializer / "__init__.py").mkdir()

    with pytest.raises(
        AnalysisError,
        match=r"__init__\.py: cannot read package initializer",
    ):
        plan([invalid_initializer])


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


def test_planning_all_roots_is_deterministic_and_all_or_nothing(tmp_path: Path) -> None:
    """Root order is stable and a later failure leaves every root untouched."""
    first = tmp_path / "alpha"
    second = tmp_path / "beta"
    _module(first / "api.py", "value = 1\n")
    _module(second / "broken.py", "__all__ = make_exports()\n")

    with pytest.raises(AnalysisError, match="__all__"):
        plan([second, first])

    assert not (first / "__init__.py").exists()
    assert not (second / "__init__.py").exists()

    (second / "broken.py").write_text("value = 2\n", encoding="utf-8")
    generation = plan([second, first])
    assert generation.roots == (first, second)
    assert tuple(change.path.parent for change in generation.changes) == (first, second)


def test_symlink_overlapping_and_invalid_roots_are_rejected(tmp_path: Path) -> None:
    """Root validation rejects ambiguous and non-importable package layouts."""
    package = tmp_path / "example"
    nested = package / "nested"
    nested.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(package, target_is_directory=True)

    with pytest.raises(ConfigurationError, match="symbolic link"):
        plan([alias])
    with pytest.raises(ConfigurationError, match="overlapping package roots"):
        plan([package, nested])

    invalid_package = tmp_path / "not-valid"
    invalid_package.mkdir()
    with pytest.raises(AnalysisError, match="not a valid Python module name"):
        plan([invalid_package])

    _module(package / "not-valid.py", "value = 1\n")
    with pytest.raises(AnalysisError, match="not a valid Python module name"):
        plan([package])


@pytest.mark.parametrize(
    ("requires_python", "eager", "loaded_immediately"),
    [
        pytest.param(
            ">=3.15",
            (),
            False,
            marks=pytest.mark.skipif(
                sys.version_info < (3, 15),
                reason="native lazy imports require Python 3.15",
            ),
        ),
        (">=3.15", ("api.py",), True),
        (">=3.14", (), True),
        (None, (), True),
    ],
)
def test_generated_imports_have_native_runtime_semantics(
    tmp_path: Path,
    requires_python: str | None,
    eager: tuple[str, ...],
    loaded_immediately: bool,
) -> None:
    """Runtime imports follow target support and explicit eager overrides."""
    package = tmp_path / "runtime_package"
    _module(
        package / "api.py",
        '__all__ = ("VALUE",)\nVALUE = 42\n',
    )
    _managed_init(package, '__public__ = ("api",)\n')
    plan(
        config=Config(
            roots=(package,),
            eager=eager,
            requires_python=requires_python,
        )
    ).write()

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


@pytest.mark.parametrize(
    ("requires_python", "uses_lazy_imports"),
    [
        (None, False),
        (">=3.14", False),
        (">=3.14,<3.15", False),
        (">=3.15", True),
        ("~=3.15", True),
        ("==3.15.*", True),
    ],
)
def test_generated_import_mode_follows_supported_python_versions(
    tmp_path: Path,
    requires_python: str | None,
    uses_lazy_imports: bool,
) -> None:
    """Any declared support below Python 3.15 makes every import eager."""
    package = tmp_path / "example"
    _module(package / "api.py", "value = 1\n")

    plan(
        config=Config(
            roots=(package,),
            requires_python=requires_python,
        )
    ).write()

    content = (package / "__init__.py").read_text(encoding="utf-8")
    assert ("lazy from . import api as api" in content) is uses_lazy_imports
    assert ("\nfrom . import api as api\n" in content) is not uses_lazy_imports


@pytest.mark.parametrize(
    ("requires_python", "expected_import"),
    [
        (">=3.14", "from . import api as api"),
        (">=3.15", "lazy from . import api as api"),
    ],
)
def test_project_metadata_controls_generated_import_mode(
    tmp_path: Path,
    requires_python: str,
    expected_import: str,
) -> None:
    """Planning reads supported Python versions from the target project."""
    package = tmp_path / "example"
    _module(package / "api.py", "value = 1\n")
    project = tmp_path / "pyproject.toml"
    project.write_text(
        f'\n[project]\nrequires-python = "{requires_python}"\n'
        '\n[tool.autoinit]\nroots = ["example"]\n',
        encoding="utf-8",
    )

    plan(config_path=project).write()

    content = (package / "__init__.py").read_text(encoding="utf-8")
    assert f"\n{expected_import}\n" in content


def test_generated_initializer_passes_ruff(tmp_path: Path) -> None:
    """Generated blocks already satisfy the subsequent Ruff hooks."""
    package = tmp_path / "example"
    _module(
        package / "api.py",
        '__all__ = ("Zebra", "Apple")\nclass Zebra: ...\nclass Apple: ...\n',
    )
    _module(
        package / "other.py",
        '__all__ = ("value", "Beta")\nvalue = 1\nclass Beta: ...\n',
    )
    _managed_init(
        package,
        '"""Example package."""\n\n__public__ = ("api", "other")\n',
    )
    generated_package = tmp_path / "generated"
    _module(generated_package / "module.py", "value = 1\n")
    plan(
        config=Config(
            roots=(package, generated_package),
            eager=("api.py",),
        )
    ).write()
    init_paths = (package / "__init__.py", generated_package / "__init__.py")
    assert (
        init_paths[1]
        .read_text(encoding="utf-8")
        .startswith(
            '"""Automatically generated by autoinit.\n\n'
            "Content between the autoinit markers will be overwritten; keep both "
            'markers intact.\n"""\n'
        )
    )
    ruff = shutil.which("ruff")
    assert ruff is not None
    config = Path(__file__).parents[1] / "ruff.toml"

    for arguments in (("format", "--check"), ("check",)):
        completed = subprocess.run(  # noqa: S603 -- Ruff is resolved from the locked environment.
            [
                ruff,
                *arguments,
                "--config",
                str(config),
                *(str(path) for path in init_paths),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


def _module(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _managed_init(package: Path, declarations: str) -> Path:
    return _module(
        package / "__init__.py",
        f"{declarations}\n# <autoinit>\n__all__ = ()\n# </autoinit>\n",
    )
