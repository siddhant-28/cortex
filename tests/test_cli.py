from typer.testing import CliRunner

from cortex.cli import app

runner = CliRunner()


def test_help_lists_all_subcommands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("chunk", "build", "status", "search", "serve", "watch"):
        assert cmd in result.stdout


def test_remaining_stubs_exit_nonzero():
    # serve (Phase 4) is still a stub; it should exit non-zero, not crash.
    assert runner.invoke(app, ["serve"]).exit_code == 1
