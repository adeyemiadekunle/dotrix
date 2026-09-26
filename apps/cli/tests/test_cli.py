from typer.testing import CliRunner

from pmagent_cli.cli import app


def test_help() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
