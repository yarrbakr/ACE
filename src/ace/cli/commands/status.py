"""ace status — agent health and info."""

from __future__ import annotations

import httpx
import typer
from rich import print as rprint

from ace.core.config import load_settings


def status_cmd(
    port: int | None = typer.Option(None, "--port", "-p", help="Override server port"),
) -> None:
    """Show the agent's status, health, and configuration."""
    settings = load_settings()
    server_port = port or settings.port
    url = f"http://127.0.0.1:{server_port}/admin/status"

    try:
        resp = httpx.get(url, timeout=5.0)
        data = resp.json()
    except httpx.ConnectError:
        rprint(
            "[yellow]Agent is not running.[/yellow] "
            "Start it with: [bold]ace start[/bold]"
        )
        raise typer.Exit(code=1) from None
    except Exception as exc:
        rprint(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None

    if data.get("status") != "ok":
        rprint(f"[red]Error:[/red] {data}")
        raise typer.Exit(code=1)

    rprint("\n[bold green]✅ ACE Agent Running[/bold green]")
    rprint(f"   Name:         [cyan]{data['agent_name']}[/cyan]")
    rprint(f"   AID:          [dim]{data['aid']}[/dim]")
    rprint(f"   Port:         [cyan]{data['port']}[/cyan]")
    rprint(f"   Uptime:       [cyan]{data['uptime_seconds']}s[/cyan]")
    rprint(f"   Skills:       [cyan]{data['skills_count']}[/cyan]")
    rprint(f"   Active Txns:  [cyan]{data['active_transactions']}[/cyan]")
    # Gossip info
    discovery_mode = data.get("discovery_mode", "centralized")
    rprint(f"   Discovery:    [cyan]{discovery_mode}[/cyan]")
    if discovery_mode == "gossip":
        rprint(f"   Known Peers:  [cyan]{data.get('known_peers', 0)}[/cyan]")
        seeds = data.get("seed_peers", [])
        if seeds:
            rprint(f"   Seed Peers:   [cyan]{len(seeds)}[/cyan]")
    rprint()
