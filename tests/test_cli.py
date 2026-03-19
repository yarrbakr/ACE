"""Tests for the ACE CLI entry point and commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ace.cli.main import app

runner = CliRunner()


class TestCliHelp:
    """Verify that `ace --help` shows all expected commands."""

    def test_help_exits_cleanly(self) -> None:
        # Arrange — runner and app already available
        # Act
        result = runner.invoke(app, ["--help"])
        # Assert
        assert result.exit_code == 0

    def test_help_shows_all_commands(self) -> None:
        # Arrange
        expected_commands = [
            "init",
            "start",
            "balance",
            "transfer",
            "mint",
            "register-skill",
            "search",
            "skills",
            "status",
        ]
        # Act
        result = runner.invoke(app, ["--help"])
        # Assert
        for cmd in expected_commands:
            assert cmd in result.output, f"Missing command: {cmd}"

    def test_version_flag(self) -> None:
        # Act
        result = runner.invoke(app, ["--version"])
        # Assert
        assert result.exit_code == 0
        assert "ace" in result.output


class TestCliStubs:
    """Verify stub commands exit cleanly with step references."""

    def test_start_fails_without_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ace.core.exceptions import ConfigNotFoundError

        def _raise(*_a: object, **_kw: object) -> None:
            raise ConfigNotFoundError("No config")

        monkeypatch.setattr("ace.core.config.require_config", _raise)
        result = runner.invoke(app, ["start"])
        assert result.exit_code == 1

    def test_balance_fails_without_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Point DEFAULT_ACE_DIR to an empty temp dir so require_config() fails
        monkeypatch.setattr("ace.cli.commands.wallet.DEFAULT_ACE_DIR", tmp_path)
        monkeypatch.setattr("ace.core.config.DEFAULT_CONFIG_FILE", tmp_path / "config.yaml")
        result = runner.invoke(app, ["balance"])
        assert result.exit_code != 0

    def test_status_fails_when_server_not_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Point to a port where no server is running
        monkeypatch.setattr("ace.cli.commands.status.load_settings", lambda: type("S", (), {"port": 19999})())
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        assert "not running" in result.output.lower()

    def test_search_fails_without_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # search calls require_config() via _get_registry() — mock it to raise
        from ace.core.exceptions import ConfigNotFoundError

        def _raise(*_a: object, **_kw: object) -> None:
            raise ConfigNotFoundError("No config found")

        monkeypatch.setattr("ace.cli.commands.skills.require_config", _raise)
        result = runner.invoke(app, ["search", "test-query"])
        assert result.exit_code != 0

    def test_register_skill_file_not_found(self) -> None:
        result = runner.invoke(app, ["register-skill", "nonexistent_file.md"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_transfer_fails_without_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Point DEFAULT_ACE_DIR to an empty temp dir so require_config() fails
        monkeypatch.setattr("ace.cli.commands.wallet.DEFAULT_ACE_DIR", tmp_path)
        monkeypatch.setattr("ace.core.config.DEFAULT_CONFIG_FILE", tmp_path / "config.yaml")
        result = runner.invoke(app, ["transfer", "agent-123", "100"])
        assert result.exit_code != 0


class TestInitCommand:
    """Verify `ace init` creates identity and config."""

    def test_init_creates_config_and_key(self, tmp_path: Path) -> None:
        ace_dir = tmp_path / ".ace"
        result = runner.invoke(
            app,
            ["init", "--name", "TestAgent", "--dir", str(ace_dir)],
            input="TestPass123\nTestPass123\n",
        )
        assert result.exit_code == 0
        assert (ace_dir / "config.yaml").exists()
        assert (ace_dir / "identity.key").exists()

    def test_init_config_contains_aid(self, tmp_path: Path) -> None:
        import yaml

        ace_dir = tmp_path / ".ace"
        runner.invoke(
            app,
            ["init", "--name", "TestAgent", "--description", "A test agent", "--dir", str(ace_dir)],
            input="TestPass123\nTestPass123\n",
        )
        config = yaml.safe_load((ace_dir / "config.yaml").read_text(encoding="utf-8"))
        assert "aid" in config
        assert config["aid"].startswith("aid:")
        assert config["agent_name"] == "TestAgent"
        assert config["agent_description"] == "A test agent"

    def test_init_identity_key_is_not_empty(self, tmp_path: Path) -> None:
        ace_dir = tmp_path / ".ace"
        runner.invoke(
            app,
            ["init", "--name", "TestAgent", "--dir", str(ace_dir)],
            input="TestPass123\nTestPass123\n",
        )
        assert (ace_dir / "identity.key").stat().st_size > 0

    def test_init_twice_prompts_confirmation(self, tmp_path: Path) -> None:
        ace_dir = tmp_path / ".ace"
        # First init
        runner.invoke(
            app,
            ["init", "--name", "First", "--dir", str(ace_dir)],
            input="TestPass123\nTestPass123\n",
        )
        # Second init — decline
        result = runner.invoke(
            app,
            ["init", "--name", "Second", "--dir", str(ace_dir)],
            input="n\n",
        )
        assert result.exit_code == 0
        assert "Aborted" in result.output

    def test_init_rejects_short_password(self, tmp_path: Path) -> None:
        ace_dir = tmp_path / ".ace"
        result = runner.invoke(
            app,
            ["init", "--name", "TestAgent", "--dir", str(ace_dir)],
            input="short\nshort\n",
        )
        assert result.exit_code == 1

