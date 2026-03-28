"""ACE configuration — Pydantic Settings backed by ~/.ace/config.yaml."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ace.core.exceptions import ConfigNotFoundError

DEFAULT_ACE_DIR = Path.home() / ".ace"
DEFAULT_CONFIG_FILE = DEFAULT_ACE_DIR / "config.yaml"


class DiscoveryMode(str, Enum):
    CENTRALIZED = "centralized"
    GOSSIP = "gossip"
    REGISTRY = "registry"


class AceSettings(BaseSettings):
    """Global settings for an ACE agent node."""

    model_config = SettingsConfigDict(
        env_prefix="ACE_",
        env_nested_delimiter="__",
    )

    aid: str = Field(default="", description="Agent ID (derived from public key)")
    agent_name: str = Field(default="my-agent", description="Human-readable agent name")
    agent_description: str = Field(default="", description="Short agent description")
    port: int = Field(default=8080, ge=1, le=65535, description="HTTP server port")
    discovery_mode: DiscoveryMode = Field(
        default=DiscoveryMode.CENTRALIZED,
        description="Agent discovery mechanism",
    )
    registry_url: str = Field(
        default="https://namdvhxjugux.ap-southeast-1.clawcloudrun.com",
        description="URL of the public registry for agent discovery",
    )
    data_dir: Path = Field(
        default=DEFAULT_ACE_DIR / "data",
        description="Directory for SQLite DB and key files",
    )
    seed_peers: list[str] = Field(
        default_factory=list,
        description="Bootstrap peer URLs for gossip discovery",
    )
    gossip_interval: float = Field(
        default=30.0,
        description="Seconds between gossip rounds",
    )
    gossip_fanout: int = Field(
        default=3,
        description="Number of peers to exchange with each round",
    )
    heartbeat_interval: float = Field(
        default=60.0,
        description="Seconds between heartbeats to the public registry",
    )
    public_url: str = Field(
        default="",
        description="Externally reachable URL for this agent (used in agent card with --public)",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_path(cls, values: dict[str, Any]) -> dict[str, Any]:
        if "data_dir" in values and isinstance(values["data_dir"], str):
            values["data_dir"] = Path(values["data_dir"])
        return values


def load_settings(config_path: Path = DEFAULT_CONFIG_FILE) -> AceSettings:
    """Load settings from a YAML file, falling back to env vars and defaults."""
    overrides: dict[str, Any] = {}
    if config_path.exists():
        raw = config_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw)
        if isinstance(parsed, dict):
            overrides = parsed
    return AceSettings(**overrides)


def ensure_ace_dir(ace_dir: Path = DEFAULT_ACE_DIR) -> Path:
    """Create the ~/.ace directory tree if it doesn't exist. Returns the path."""
    ace_dir.mkdir(parents=True, exist_ok=True)
    data_dir = ace_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return ace_dir


def write_default_config(
    ace_dir: Path = DEFAULT_ACE_DIR,
    *,
    agent_name: str = "my-agent",
    agent_description: str = "",
    aid: str = "",
    port: int = 8080,
    discovery_mode: str = "centralized",
    seed_peers: list[str] | None = None,
    registry_url: str = "https://namdvhxjugux.ap-southeast-1.clawcloudrun.com",
    public_url: str = "",
) -> Path:
    """Write a default config.yaml into the given ACE directory."""
    config_path = ace_dir / "config.yaml"
    config_data: dict[str, Any] = {
        "agent_name": agent_name,
        "agent_description": agent_description,
        "aid": aid,
        "port": port,
        "discovery_mode": discovery_mode,
        "registry_url": registry_url,
        "data_dir": str(ace_dir / "data"),
    }
    if public_url:
        config_data["public_url"] = public_url
    if seed_peers:
        config_data["seed_peers"] = seed_peers
    config_path.write_text(yaml.dump(config_data, default_flow_style=False), encoding="utf-8")
    return config_path


def require_config(config_path: Path = DEFAULT_CONFIG_FILE) -> AceSettings:
    """Load config or raise ConfigNotFoundError if the file is missing."""
    if not config_path.exists():
        raise ConfigNotFoundError(f"Config not found at {config_path}. Run 'ace init' first.")
    return load_settings(config_path)


__all__ = [
    "AceSettings",
    "DiscoveryMode",
    "DEFAULT_ACE_DIR",
    "DEFAULT_CONFIG_FILE",
    "ensure_ace_dir",
    "load_settings",
    "require_config",
    "write_default_config",
]
