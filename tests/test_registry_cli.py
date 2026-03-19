"""CLI tests for the registry subcommand."""

from __future__ import annotations

import re

from typer.testing import CliRunner

from ace.cli.main import app

runner = CliRunner()


def _plain(text: str) -> str:
    """Strip ANSI escape codes so assertions work on Linux CI."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_registry_subcommand_group_exists() -> None:
    """The 'registry' command group appears in help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "registry" in _plain(result.output)


def test_registry_start_help() -> None:
    """'ace registry start --help' shows options."""
    result = runner.invoke(app, ["registry", "start", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--port" in output
    assert "--host" in output
    assert "--db" in output
    assert "--prune-interval" in output
    assert "--prune-max-age" in output


def test_start_public_flag_in_help() -> None:
    """'ace start --help' shows --public flag."""
    result = runner.invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    assert "--public" in _plain(result.output)


def test_init_registry_url_in_help() -> None:
    """'ace init --help' shows --registry-url option."""
    result = runner.invoke(app, ["init", "--help"])
    assert result.exit_code == 0
    assert "--registry-url" in _plain(result.output)


def test_init_discovery_modes_in_help() -> None:
    """'ace init --help' shows registry in discovery modes."""
    result = runner.invoke(app, ["init", "--help"])
    assert result.exit_code == 0
    assert "registry" in _plain(result.output)
