from typer.testing import CliRunner

from cortex.cli import app

runner = CliRunner()


def test_help_lists_all_subcommands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("chunk", "build", "status", "search", "serve", "watch"):
        assert cmd in result.stdout


def test_stubs_exit_nonzero_until_implemented():
    # Every subcommand is a stub in Phase 0; each should exit non-zero, not crash.
    assert runner.invoke(app, ["status"]).exit_code == 1
    assert runner.invoke(app, ["serve"]).exit_code == 1
