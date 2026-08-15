"""Public immutable models for generation plans."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import os
from pathlib import Path
import stat
import tempfile

from autoinit.errors import OwnershipError


@dataclass(frozen=True, slots=True)
class Config:
    """Resolved project configuration.

    Attributes:
        project_file: Configuration file from which relative paths are resolved.
        roots: Package roots processed when the caller supplies no extra roots.
        exclude: Root-relative path globs omitted from discovery.
        eager: Root-relative module globs imported eagerly.
    """

    project_file: Path | None = None
    roots: tuple[Path, ...] = ()
    exclude: tuple[str, ...] = ()
    eager: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FileChange:
    """The complete planned content for one ``__init__.py`` file."""

    path: Path
    before: str | None
    after: str

    @property
    def changed(self) -> bool:
        """Return whether applying this change would alter the filesystem."""
        return self.before != self.after

    def diff(self) -> str:
        """Return a unified diff for this change."""
        before = () if self.before is None else self.before.splitlines(keepends=True)
        after = self.after.splitlines(keepends=True)
        label = self.path.as_posix()
        return "".join(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"a/{label}",
                tofile=f"b/{label}",
            )
        )


@dataclass(frozen=True, slots=True)
class GenerationPlan:
    """A fully validated, side-effect-free package generation plan."""

    roots: tuple[Path, ...]
    changes: tuple[FileChange, ...]

    @property
    def changed_files(self) -> tuple[FileChange, ...]:
        """Return only files whose generated content differs."""
        return tuple(change for change in self.changes if change.changed)

    @property
    def has_changes(self) -> bool:
        """Return whether the plan contains any filesystem changes."""
        return any(change.changed for change in self.changes)

    def write(self) -> tuple[Path, ...]:
        """Apply all changed files after checking that none became stale.

        Returns:
            Paths written in deterministic order.

        Raises:
            OwnershipError: If a file changed after this plan was created.
        """
        changed = self.changed_files
        for change in changed:
            current = change.path.read_text(encoding="utf-8") if change.path.exists() else None
            if current != change.before:
                msg = f"{change.path}: file changed after the generation plan was created"
                raise OwnershipError(msg)

        for change in changed:
            _atomic_write(change)
        return tuple(change.path for change in changed)


def _atomic_write(change: FileChange) -> None:
    """Atomically replace one file while preserving existing permissions."""
    mode = None
    if change.path.exists():
        mode = stat.S_IMODE(change.path.stat().st_mode)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=change.path.parent,
        prefix=f".{change.path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(change.after)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            temporary.chmod(mode)
        temporary.replace(change.path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
