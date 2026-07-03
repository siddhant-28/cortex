from typer.testing import CliRunner

from cortex.cli import app

runner = CliRunner()


def test_help_lists_all_subcommands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("chunk", "build", "status", "search", "serve", "watch"):
        assert cmd in result.stdout


def test_remaining_stubs_exit_nonzero():
    # watch (Phase 5) is the last stub; it should exit non-zero, not crash.
    # (Don't invoke `serve` — it now launches a blocking stdio server.)
    assert runner.invoke(app, ["watch", "somepath", "--alias", "a"]).exit_code == 1
