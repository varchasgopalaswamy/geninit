"""Discover packages and generate managed ``__init__.py`` files."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import keyword
import os
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from autoinit.config import load_config
from autoinit.errors import (
    AnalysisError,
    CollisionError,
    ConfigurationError,
    OwnershipError,
)
from autoinit.models import Config, FileChange, GenerationPlan

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

START_MARKER = "# <autoinit>"
END_MARKER = "# </autoinit>"

_VISIBILITY_NAMES = ("__public__", "__protected__", "__private__")
_IGNORED_DIRECTORIES = frozenset(
    {
        ".eggs",
        ".git",
        ".hg",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "env",
        "venv",
    }
)


@dataclass(frozen=True, slots=True)
class _Child:
    name: str
    source: Path
    exports: tuple[str, ...]
    eager_path: str


@dataclass(frozen=True, slots=True)
class _Package:
    path: Path
    modules: tuple[Path, ...]
    subpackages: tuple[Path, ...]


def plan(
    roots: Iterable[str | Path] = (),
    *,
    config: Config | None = None,
    config_path: str | Path | None = None,
    start: str | Path | None = None,
) -> GenerationPlan:
    """Build a complete generation plan without changing the filesystem.

    Args:
        roots: Additional package roots. These are combined with configured roots.
        config: Preloaded configuration. Mutually exclusive with ``config_path``.
        config_path: Explicit ``pyproject.toml`` path.
        start: Configuration discovery directory when no path is provided.

    Returns:
        A validated generation plan that can be inspected or written.

    Raises:
        ConfigurationError: If roots or configuration are invalid.
        AnalysisError: If source declarations are not statically resolvable.
        OwnershipError: If an existing package file is not managed safely.
        CollisionError: If generated names would be ambiguous.
    """
    if config is not None and config_path is not None:
        msg = "config and config_path are mutually exclusive"
        raise ConfigurationError(msg)
    resolved_config = config or load_config(config_path, start=start)
    requested = (
        *resolved_config.roots,
        *(Path(root).expanduser().resolve() for root in roots),
    )
    resolved_roots = _unique_roots(requested)
    if not resolved_roots:
        msg = "no package roots supplied; configure tool.autoinit.roots or pass a path"
        raise ConfigurationError(msg)

    changes: list[FileChange] = []
    for root in resolved_roots:
        changes.extend(_plan_root(root, resolved_config))
    changes.sort(key=lambda change: change.path.as_posix())
    return GenerationPlan(roots=resolved_roots, changes=tuple(changes))


def _unique_roots(roots: Sequence[Path]) -> tuple[Path, ...]:
    unique = tuple(dict.fromkeys(root.resolve() for root in roots))
    for root in unique:
        if not root.is_dir():
            msg = f"{root}: package root is not a directory"
            raise ConfigurationError(msg)
        if root.is_symlink():
            msg = f"{root}: package root cannot be a symbolic link"
            raise ConfigurationError(msg)
        _validate_module_name(root.name, root)
    ordered = tuple(sorted(unique, key=lambda path: path.as_posix()))
    for index, root in enumerate(ordered):
        for other in ordered[index + 1 :]:
            if root in other.parents:
                msg = f"overlapping package roots are not allowed: {root} and {other}"
                raise ConfigurationError(msg)
    return ordered


def _plan_root(root: Path, config: Config) -> list[FileChange]:
    packages = _discover_packages(root, config.exclude)
    exports_by_package: dict[Path, tuple[str, ...]] = {}
    changes: list[FileChange] = []
    for package in sorted(
        packages,
        key=lambda item: (
            -len(item.path.relative_to(root).parts),
            item.path.as_posix(),
        ),
    ):
        init_path = package.path / "__init__.py"
        before = init_path.read_text(encoding="utf-8") if init_path.exists() else None
        handwritten = _handwritten_source(init_path, before)
        visibility = {
            name: _literal_names(handwritten, init_path, name) for name in _VISIBILITY_NAMES
        }
        children = _children_for(package, root, exports_by_package)
        generated, exports = _render_package(
            init_path,
            children,
            visibility,
            config.eager,
        )
        after = _replace_managed(init_path, before, generated)
        exports_by_package[package.path] = exports
        changes.append(FileChange(path=init_path, before=before, after=after))
    return changes


def _discover_packages(root: Path, exclude: Sequence[str]) -> tuple[_Package, ...]:
    python_files: dict[Path, tuple[Path, ...]] = {}
    for current, directory_names, file_names in os.walk(root, topdown=True):
        directory = Path(current)
        relative_directory = directory.relative_to(root)
        kept_directories: list[str] = []
        for name in sorted(directory_names):
            candidate = directory / name
            relative = candidate.relative_to(root).as_posix()
            if _ignore_directory(name) or candidate.is_symlink():
                continue
            if _matches(relative, exclude, directory=True):
                continue
            kept_directories.append(name)
        directory_names[:] = kept_directories

        files: list[Path] = []
        for name in sorted(file_names):
            if not name.endswith(".py"):
                continue
            candidate = directory / name
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink() or _matches(relative, exclude):
                continue
            files.append(candidate)
        if files or not relative_directory.parts:
            python_files[directory] = tuple(files)

    qualifying = set(python_files)
    for directory in tuple(qualifying):
        parent = directory.parent
        while parent != root.parent:
            qualifying.add(parent)
            if parent == root:
                break
            parent = parent.parent

    packages: list[_Package] = []
    for directory in sorted(qualifying, key=lambda path: path.as_posix()):
        _validate_module_name(directory.name, directory)
        modules = tuple(
            path for path in python_files.get(directory, ()) if path.name != "__init__.py"
        )
        for module in modules:
            _validate_module_name(module.stem, module)
        subpackages = tuple(
            child
            for child in sorted(qualifying, key=lambda path: path.as_posix())
            if child.parent == directory
        )
        module_names = {module.stem for module in modules}
        duplicate_names = module_names.intersection(child.name for child in subpackages)
        if duplicate_names:
            name = min(duplicate_names)
            msg = f"{directory}: both {name}.py and {name}/ define the same child"
            raise CollisionError(msg)
        packages.append(_Package(directory, modules, subpackages))
    return tuple(packages)


def _ignore_directory(name: str) -> bool:
    return name.startswith(".") or name in _IGNORED_DIRECTORIES or name.endswith(".egg-info")


def _children_for(
    package: _Package,
    root: Path,
    exports_by_package: dict[Path, tuple[str, ...]],
) -> tuple[_Child, ...]:
    children: list[_Child] = []
    for module in package.modules:
        exports = _literal_names(
            module.read_text(encoding="utf-8"),
            module,
            "__all__",
        )
        children.append(
            _Child(
                name=module.stem,
                source=module,
                exports=exports,
                eager_path=module.relative_to(root).as_posix(),
            )
        )
    children.extend(
        _Child(
            name=subpackage.name,
            source=subpackage / "__init__.py",
            exports=exports_by_package[subpackage],
            eager_path=(subpackage / "__init__.py").relative_to(root).as_posix(),
        )
        for subpackage in package.subpackages
    )
    return tuple(sorted(children, key=lambda child: child.name))


def _render_package(
    init_path: Path,
    children: Sequence[_Child],
    visibility: dict[str, tuple[str, ...]],
    eager_patterns: Sequence[str],
) -> tuple[str, tuple[str, ...]]:
    child_by_name = {child.name: child for child in children}
    known = set(child_by_name)
    declared = {kind: set(names) for kind, names in visibility.items()}
    for kind, names in declared.items():
        unknown = names - known
        if unknown:
            joined = ", ".join(sorted(unknown))
            msg = f"{init_path}: {kind} contains unknown child name(s): {joined}"
            raise AnalysisError(msg)
    for index, left in enumerate(_VISIBILITY_NAMES):
        for right in _VISIBILITY_NAMES[index + 1 :]:
            overlap = declared[left] & declared[right]
            if overlap:
                joined = ", ".join(sorted(overlap))
                msg = f"{init_path}: {left} and {right} overlap: {joined}"
                raise AnalysisError(msg)

    public = declared["__public__"]
    protected = declared["__protected__"]
    private = declared["__private__"]
    exposed = tuple(
        child
        for child in children
        if child.name not in private
        and (not child.name.startswith("_") or child.name in public or child.name in protected)
    )

    origins: dict[str, Path] = {}
    for child in exposed:
        origins[child.name] = child.source
    for child in exposed:
        if child.name not in public:
            continue
        for exported in child.exports:
            previous = origins.get(exported)
            if previous is not None:
                msg = (
                    f"{init_path}: export {exported!r} collides between "
                    f"{previous} and {child.source}"
                )
                raise CollisionError(msg)
            origins[exported] = child.source

    imports: list[str] = []
    for child in exposed:
        prefix = "" if _matches(child.eager_path, eager_patterns) else "lazy "
        imports.append(f"{prefix}from . import {child.name} as {child.name}")
        if child.name in public:
            imports.extend(
                f"{prefix}from .{child.name} import {name} as {name}" for name in child.exports
            )

    module_exports = tuple(child.name for child in exposed)
    lifted_exports = tuple(
        name for child in exposed if child.name in public for name in child.exports
    )
    exports = (*module_exports, *lifted_exports)
    lines = [START_MARKER, *imports]
    if imports:
        lines.append("")
    lines.extend(_render_all(exports))
    lines.append(END_MARKER)
    return "\n".join(lines) + "\n", exports


def _render_all(names: Sequence[str]) -> list[str]:
    if not names:
        return ["__all__ = ()"]
    return ["__all__ = (", *(f'    "{name}",' for name in names), ")"]


def _replace_managed(path: Path, before: str | None, generated: str) -> str:
    if before is None or not before.strip():
        return generated
    start_count = before.count(START_MARKER)
    end_count = before.count(END_MARKER)
    if start_count != 1 or end_count != 1:
        msg = (
            f"{path}: nonempty files must contain exactly one {START_MARKER!r} "
            f"and one {END_MARKER!r}"
        )
        raise OwnershipError(msg)
    start = before.index(START_MARKER)
    end_start = before.find(END_MARKER, start)
    if end_start < 0:
        msg = f"{path}: managed block markers are out of order"
        raise OwnershipError(msg)
    end = end_start + len(END_MARKER)
    if end < len(before) and before[end] == "\n":
        end += 1
    return f"{before[:start]}{generated}{before[end:]}"


def _handwritten_source(path: Path, source: str | None) -> str:
    if source is None or not source.strip():
        return ""
    start_count = source.count(START_MARKER)
    end_count = source.count(END_MARKER)
    if start_count != 1 or end_count != 1:
        msg = (
            f"{path}: nonempty files must contain exactly one {START_MARKER!r} "
            f"and one {END_MARKER!r}"
        )
        raise OwnershipError(msg)
    start = source.index(START_MARKER)
    end_start = source.find(END_MARKER, start)
    if end_start < 0:
        msg = f"{path}: managed block markers are out of order"
        raise OwnershipError(msg)
    end = end_start + len(END_MARKER)
    return f"{source[:start]}\n{source[end:]}"


def _literal_names(
    source: str,
    path: Path,
    variable: str,
) -> tuple[str, ...]:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        msg = f"{path}:{error.lineno}: invalid Python syntax: {error.msg}"
        raise AnalysisError(msg) from error

    writes = _module_writes(tree, variable)
    if not writes:
        return ()
    if len(writes) != 1 or writes[0] not in tree.body:
        msg = f"{path}: {variable} must be assigned once at module scope"
        raise AnalysisError(msg)
    assignment = writes[0]
    value_node = assignment.value if isinstance(assignment, (ast.Assign, ast.AnnAssign)) else None
    if value_node is None:
        msg = f"{path}:{assignment.lineno}: {variable} must use a literal assignment"
        raise AnalysisError(msg)
    try:
        value = ast.literal_eval(value_node)
    except (ValueError, TypeError, SyntaxError) as error:
        msg = f"{path}:{assignment.lineno}: {variable} must be a literal string sequence"
        raise AnalysisError(msg) from error
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        msg = f"{path}:{assignment.lineno}: {variable} must be a literal string sequence"
        raise AnalysisError(msg)
    names = tuple(value)
    if len(set(names)) != len(names):
        msg = f"{path}:{assignment.lineno}: {variable} contains duplicate names"
        raise AnalysisError(msg)
    invalid = next(
        (name for name in names if not name.isidentifier() or keyword.iskeyword(name)),
        None,
    )
    if invalid is not None:
        msg = f"{path}:{assignment.lineno}: {variable} contains invalid name {invalid!r}"
        raise AnalysisError(msg)
    return names


def _module_writes(tree: ast.Module, variable: str) -> list[ast.stmt]:
    writes: list[ast.stmt] = []

    class WriteVisitor(ast.NodeVisitor):
        def visit_Assign(self, node: ast.Assign) -> None:
            if any(_target_contains(target, variable) for target in node.targets):
                writes.append(node)
            self.generic_visit(node.value)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            if _target_contains(node.target, variable):
                writes.append(node)
            if node.value is not None:
                self.generic_visit(node.value)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            if _target_contains(node.target, variable):
                writes.append(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            del node

        def visit_AsyncFunctionDef(
            self,
            node: ast.AsyncFunctionDef,
        ) -> None:
            del node

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            del node

        def visit_Lambda(self, node: ast.Lambda) -> None:
            del node

    WriteVisitor().visit(tree)
    return writes


def _target_contains(target: ast.expr, variable: str) -> bool:
    if isinstance(target, ast.Name):
        return target.id == variable
    if isinstance(target, (ast.List, ast.Tuple)):
        return any(_target_contains(element, variable) for element in target.elts)
    return False


def _validate_module_name(name: str, path: Path) -> None:
    if not name.isidentifier() or keyword.iskeyword(name):
        msg = f"{path}: {name!r} is not a valid Python module name"
        raise AnalysisError(msg)


def _matches(path: str, patterns: Sequence[str], *, directory: bool = False) -> bool:
    candidates = [path]
    if directory:
        candidates.extend((f"{path}/", f"{path}/__init__.py"))
    for pattern in patterns:
        normalized = pattern.removeprefix("./")
        pattern_candidates = [normalized]
        if normalized.startswith("**/"):
            pattern_candidates.append(normalized[3:])
        if any(
            PurePosixPath(candidate).full_match(candidate_pattern, case_sensitive=True)
            for candidate in candidates
            for candidate_pattern in pattern_candidates
        ):
            return True
    return False
