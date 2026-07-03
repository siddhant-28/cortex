from typer.testing import CliRunner

from cortex.cli import app

runner = CliRunner()


def test_help_lists_all_subcommands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("chunk", "build", "status", "search", "serve", "watch"):
        assert cmd in result.stdout


def test_build_rejects_non_directory(tmp_path):
    # All subcommands are implemented now; a bad build path should exit non-zero cleanly.
    result = runner.invoke(app, ["build", str(tmp_path / "nope"), "--alias", "x"])
    assert result.exit_code == 1
