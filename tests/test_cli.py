from click.testing import CliRunner

from regress import __version__
from regress.cli import main


def test_cli_version() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_cli_help_lists_up_command() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "up" in result.output
