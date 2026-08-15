"""Tests for the Click command-line adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from click.testing import CliRunner

from geninit.cli import cli, main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_cli_write_check_diff(tmp_path: Path) -> None:
    """The CLI writes by default and exposes non-mutating CI modes."""
    package = tmp_path / "example"
    package.mkdir()
    (package / "api.py").write_text("value = 1\n", encoding="utf-8")
    runner = CliRunner()

    written = runner.invoke(cli, [str(package)])
    assert written.exit_code == 2
    assert "updated" in written.output

    current = runner.invoke(cli, ["--check", str(package)])
    assert current.exit_code == 0
    verbose = runner.invoke(cli, ["--verbose", str(package)])
    assert verbose.exit_code == 0
    assert "all package initializers are current" in verbose.output
    (package / "new.py").write_text("value = 2\n", encoding="utf-8")

    stale = runner.invoke(cli, ["--check", str(package)])
    assert stale.exit_code == 2
    assert "would update" in stale.output
    diff = runner.invoke(cli, ["--diff", str(package)])
    assert diff.exit_code == 2
    assert "+++ b/" in diff.output
    assert "new" in diff.output


def test_cli_combines_configured_and_positional_roots(tmp_path: Path) -> None:
    """Positional roots add to, rather than replace, configured roots."""
    configured = tmp_path / "configured"
    additional = tmp_path / "additional"
    configured.mkdir()
    additional.mkdir()
    (configured / "api.py").write_text("value = 1\n", encoding="utf-8")
    (additional / "api.py").write_text("value = 2\n", encoding="utf-8")
    project = tmp_path / "pyproject.toml"
    project.write_text(
        '[tool.geninit]\nroots = ["configured"]\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["--config", str(project), str(additional)],
    )

    assert result.exit_code == 2
    assert (configured / "__init__.py").is_file()
    assert (additional / "__init__.py").is_file()


def test_main_reports_generation_and_usage_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The installed entry point maps generation and invocation errors to one."""
    package = tmp_path / "example"
    package.mkdir()
    (package / "api.py").write_text("value = 1\n", encoding="utf-8")
    (package / "__init__.py").write_text("unmanaged = True\n", encoding="utf-8")

    assert main([str(package)]) == 1
    assert "nonempty files" in capsys.readouterr().err

    assert main(["--check", "--diff", str(package)]) == 1
    assert "mutually exclusive" in capsys.readouterr().err

    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    assert main([str(alias)]) == 1
    assert "symbolic link" in capsys.readouterr().err

    invalid_utf8 = tmp_path / "invalid_utf8"
    invalid_utf8.mkdir()
    (invalid_utf8 / "api.py").write_bytes(b"\xff")
    assert main([str(invalid_utf8)]) == 1
    assert "cannot decode Python source as UTF-8" in capsys.readouterr().err

    executable_directory = tmp_path / "bin"
    executable_directory.mkdir()
    ruff = executable_directory / "ruff"
    ruff.write_text(
        "#!/bin/sh\necho 'Ruff normalization failed' >&2\nexit 7\n",
        encoding="utf-8",
    )
    ruff.chmod(0o755)
    monkeypatch.setenv("PATH", str(executable_directory))
    ruff_failure = tmp_path / "ruff_failure"
    ruff_failure.mkdir()
    (ruff_failure / "api.py").write_text("value = 1\n", encoding="utf-8")

    assert main([str(ruff_failure)]) == 1
    assert "Ruff normalization failed" in capsys.readouterr().err
    assert not (ruff_failure / "__init__.py").exists()


def test_main_returns_documented_exit_codes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The non-raising entry point maps success, staleness, and usage failures."""
    package = tmp_path / "example"
    package.mkdir()
    (package / "api.py").write_text("value = 1\n", encoding="utf-8")

    assert main([str(package)]) == 2
    capsys.readouterr()
    assert main(["--check", str(package)]) == 0
    capsys.readouterr()
    (package / "new.py").write_text("value = 2\n", encoding="utf-8")
    assert main(["--check", str(package)]) == 2
    capsys.readouterr()
    assert main(["--check", "--diff", str(package)]) == 1
    assert "mutually exclusive" in capsys.readouterr().err
    assert main(["--unknown-option"]) == 1
    assert "No such option" in capsys.readouterr().err
