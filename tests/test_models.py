"""Tests for generation plan models and filesystem application."""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

import pytest

from autoinit.errors import OwnershipError
from autoinit.models import FileChange, GenerationPlan

if TYPE_CHECKING:
    from pathlib import Path


def test_file_change_reports_state_and_unified_diff(tmp_path: Path) -> None:
    """File changes expose useful state without touching the filesystem."""
    path = tmp_path / "example" / "__init__.py"
    unchanged = FileChange(path=path, before="same\n", after="same\n")
    changed = FileChange(path=path, before="old\n", after="new\n")

    assert not unchanged.changed
    assert unchanged.diff() == ""
    assert changed.changed
    assert "-old\n+new\n" in changed.diff()
    assert f"--- a/{path.as_posix()}" in changed.diff()
    assert f"+++ b/{path.as_posix()}" in changed.diff()


def test_generation_plan_preserves_permissions(tmp_path: Path) -> None:
    """Atomic replacement retains an existing initializer's permission bits."""
    path = tmp_path / "__init__.py"
    path.write_text("before\n", encoding="utf-8")
    path.chmod(0o640)
    generation = GenerationPlan(
        roots=(tmp_path,),
        changes=(FileChange(path=path, before="before\n", after="after\n"),),
    )

    assert generation.write() == (path,)

    assert path.read_text(encoding="utf-8") == "after\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_generation_plan_wraps_read_and_write_failures(tmp_path: Path) -> None:
    """Filesystem failures retain their paths and use the ownership error API."""
    unreadable = tmp_path / "unreadable.py"
    unreadable.mkdir()
    read_plan = GenerationPlan(
        roots=(tmp_path,),
        changes=(FileChange(path=unreadable, before="before\n", after="after\n"),),
    )
    with pytest.raises(OwnershipError, match=r"unreadable\.py: cannot read"):
        read_plan.write()

    missing_parent = tmp_path / "missing" / "__init__.py"
    write_plan = GenerationPlan(
        roots=(tmp_path,),
        changes=(FileChange(path=missing_parent, before=None, after="after\n"),),
    )
    with pytest.raises(OwnershipError, match=r"__init__\.py: cannot write"):
        write_plan.write()
