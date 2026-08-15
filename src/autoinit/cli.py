"""Click command-line interface for autoinit."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click

from autoinit import __version__
from autoinit.errors import AutoInitError
from autoinit.generator import plan

if TYPE_CHECKING:
    from collections.abc import Sequence


class _GenerationClickError(click.ClickException):
    exit_code = 2


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument(
    "roots",
    nargs=-1,
    type=click.Path(
        path_type=Path,
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
)
@click.option(
    "--config",
    type=click.Path(
        path_type=Path,
        exists=True,
        dir_okay=False,
        resolve_path=True,
    ),
    metavar="PATH",
    help="Use an explicit pyproject.toml.",
)
@click.option(
    "--check",
    is_flag=True,
    help="Do not write; fail if generated files are stale.",
)
@click.option(
    "--diff",
    "show_diff",
    is_flag=True,
    help="Print unified diffs and fail if generated files are stale.",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Report when no files need updating.",
)
@click.version_option(version=__version__, prog_name="autoinit")
def cli(
    roots: tuple[Path, ...],
    config: Path | None,
    *,
    check: bool,
    show_diff: bool,
    verbose: int,
) -> None:
    """Generate managed package initializers beneath ROOTS."""
    if check and show_diff:
        msg = "--check and --diff are mutually exclusive"
        raise click.UsageError(msg)
    try:
        generation = plan(roots, config_path=config)
        changed = generation.changed_files
        if show_diff:
            click.echo("".join(change.diff() for change in changed), nl=False)
            if changed:
                raise click.exceptions.Exit(1)
            return
        if check:
            for change in changed:
                click.echo(
                    f"would update {_display_path(change.path)}",
                    err=True,
                )
            if changed:
                raise click.exceptions.Exit(1)
            if verbose:
                click.echo("all package initializers are current", err=True)
            return

        written = generation.write()
        for path in written:
            click.echo(f"updated {_display_path(path)}")
        if not written and verbose:
            click.echo("all package initializers are current")
    except AutoInitError as error:
        raise _GenerationClickError(str(error)) from error


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Click command and return its process exit code.

    Args:
        argv: Arguments excluding the executable name. Defaults to ``sys.argv``.

    Returns:
        Zero on success, one for stale generated files, or two for usage and
        generation errors.
    """
    try:
        cli.main(args=argv, prog_name="autoinit", standalone_mode=False)
    except click.ClickException as error:
        error.show()
        return error.exit_code
    except click.exceptions.Exit as error:
        return error.exit_code
    return 0


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()
