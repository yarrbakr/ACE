"""ace init — bootstrap the ~/.ace directory, generate identity, and save config."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import typer

from ace.core.config import DEFAULT_ACE_DIR, ensure_ace_dir, write_default_config
from ace.core.identity import AgentIdentity

MIN_PASSWORD_LENGTH = 8


def _set_owner_readonly(path: Path) -> None:
    """Set file to owner-read-only. Warns on Windows where chmod is limited."""
    if sys.platform == "win32":
        typer.echo("  ⚠ Windows: verify that identity.key is not world-readable.")
        return
    os.chmod(path, stat.S_IRUSR)


def init_cmd(
    name: str = typer.Option("my-agent", "--name", "-n", help="Agent name"),
    description: str = typer.Option("", "--description", "-d", help="Agent description"),
    port: int = typer.Option(8080, "--port", "-p", help="API server port"),
    ace_dir: str | None = typer.Option(None, "--dir", help="Custom ACE directory"),
    discovery: str = typer.Option(
        "centralized", "--discovery", help="Discovery mode: centralized | gossip | registry"
    ),
    seed_peers: str = typer.Option(
        "", "--seed-peers", help="Comma-separated seed peer URLs for gossip mode"
    ),
    registry_url: str = typer.Option(
        "https://namdvhxjugux.ap-southeast-1.clawcloudrun.com", "--registry-url", help="URL of the public registry"
    ),
) -> None:
    """Initialize a new ACE agent node with a cryptographic identity."""
    target = Path(ace_dir) if ace_dir else DEFAULT_ACE_DIR

    # ── Guard: already initialized ──────────────────────────────
    if target.exists() and (target / "config.yaml").exists():
        reinit = typer.confirm(
            "⚠ Agent already initialized. Old identity will be PERMANENTLY destroyed.\n"
            "Reinitialize?",
            default=False,
        )
        if not reinit:
            typer.echo("Aborted.")
            raise typer.Exit(code=0)

    # ── Password prompt ─────────────────────────────────────────
    password = typer.prompt("Set identity password", hide_input=True)
    if len(password) < MIN_PASSWORD_LENGTH:
        typer.echo(f"✗ Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        raise typer.Exit(code=1)

    password_confirm = typer.prompt("Confirm password", hide_input=True)
    if password != password_confirm:
        typer.echo("✗ Passwords do not match.")
        raise typer.Exit(code=1)

    # ── Generate identity ───────────────────────────────────────
    identity = AgentIdentity()
    ensure_ace_dir(target)

    key_path = target / "identity.key"
    identity.save_encrypted(key_path, password)
    _set_owner_readonly(key_path)

    # ── Parse gossip options ─────────────────────────────────────
    parsed_seeds = [s.strip() for s in seed_peers.split(",") if s.strip()] if seed_peers else []

    # ── Write config ────────────────────────────────────────────
    config_path = write_default_config(
        target,
        agent_name=name,
        agent_description=description,
        aid=identity.aid,
        port=port,
        discovery_mode=discovery,
        seed_peers=parsed_seeds or None,
        registry_url=registry_url,
    )

    # ── Summary ─────────────────────────────────────────────────
    typer.echo("")
    typer.echo("[bold green]✔ ACE agent initialized![/bold green]")
    typer.echo(f"  AID          : [bold]{identity.aid}[/bold]")
    typer.echo(f"  Agent name   : {name}")
    typer.echo(f"  Discovery    : {discovery}")
    if discovery == "gossip" and parsed_seeds:
        typer.echo(f"  Seed peers   : {len(parsed_seeds)}")
    if discovery == "registry":
        typer.echo(f"  Registry URL : {registry_url}")
    typer.echo(f"  Config       : {config_path}")
    typer.echo(f"  Identity key : {key_path}")
    typer.echo(f"  Data dir     : {target / 'data'}")
    typer.echo("")
    typer.echo(
        "Next: run [bold]ace register-skill path/to/SKILL.md[/bold] then [bold]ace start[/bold]"
    )
