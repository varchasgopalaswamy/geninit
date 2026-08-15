"""Tests for the Click command-line adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from click.testing import CliRunner

from autoinit.cli import cli

if TYPE_CHECKING:
    from pathlib import Path


def test_cli_write_check_diff_and_version(tmp_path: Path) -> None:
    """The CLI writes by default and exposes non-mutating CI modes."""
    package = tmp_path / "example"
    package.mkdir()
    (package / "api.py").write_text("value = 1\n", encoding="utf-8")
    runner = CliRunner()

    written = runner.invoke(cli, [str(package)])
    assert written.exit_code == 0
    assert "updated" in written.output

    current = runner.invoke(cli, ["--check", str(package)])
    assert current.exit_code == 0
    (package / "new.py").write_text("value = 2\n", encoding="utf-8")

    stale = runner.invoke(cli, ["--check", str(package)])
    assert stale.exit_code == 1
    assert "would update" in stale.output
    diff = runner.invoke(cli, ["--diff", str(package)])
    assert diff.exit_code == 1
    assert "+++ b/" in diff.output
    assert "new" in diff.output

    version = runner.invoke(cli, ["--version"])
    assert version.exit_code == 0
    assert version.output.startswith("autoinit, version 0.1.0")


def test_cli_reports_generation_and_usage_errors(tmp_path: Path) -> None:
    """Expected generation failures and invalid option combinations exit two."""
    package = tmp_path / "example"
    package.mkdir()
    (package / "api.py").write_text("value = 1\n", encoding="utf-8")
    (package / "__init__.py").write_text("unmanaged = True\n", encoding="utf-8")
    runner = CliRunner()

    failure = runner.invoke(cli, [str(package)])
    assert failure.exit_code == 2
    assert "nonempty files" in failure.output

    invalid = runner.invoke(cli, ["--check", "--diff", str(package)])
    assert invalid.exit_code == 2
    assert "mutually exclusive" in invalid.output
