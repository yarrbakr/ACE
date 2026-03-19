"""ace registry start — launch the public registry service."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich import print as rprint


def registry_start_cmd(
    port: int = typer.Option(9000, "--port", "-p", help="Registry server port"),
    host: str = typer.Option("0.0.0.0", "--host", "-H", help="Bind address (default: 0.0.0.0)"),
    db_path: str = typer.Option(
        "", "--db", help="Path to registry SQLite database (default: ./registry_data/registry.db)"
    ),
    prune_interval: float = typer.Option(
        60.0, "--prune-interval", help="Seconds between prune checks"
    ),
    prune_max_age: float = typer.Option(
        300.0, "--prune-max-age", help="Seconds before an agent is considered stale"
    ),
) -> None:
    """Start the ACE public registry server."""
    if host == "0.0.0.0" and sys.platform == "win32":
        rprint(
            "[yellow]Warning:[/yellow] Binding to 0.0.0.0 on Windows may "
            "trigger a firewall prompt."
        )

    resolved_db = Path(db_path) if db_path else Path("registry_data/registry.db")
    resolved_db.parent.mkdir(parents=True, exist_ok=True)

    rprint("\n[bold green]ACE Registry Starting[/bold green]")
    rprint(f"   Port:           [cyan]{port}[/cyan]")
    rprint(f"   Host:           [cyan]{host}[/cyan]")
    rprint(f"   Database:       [cyan]{resolved_db}[/cyan]")
    rprint(f"   Prune interval: [cyan]{prune_interval}s[/cyan]")
    rprint(f"   Prune max age:  [cyan]{prune_max_age}s[/cyan]")
    rprint(f"   Health:         [link]http://{host}:{port}/health[/link]")
    rprint(f"   Docs:           [link]http://{host}:{port}/docs[/link]")
    rprint()

    import uvicorn

    from registry.app import create_registry_app

    app = create_registry_app(
        db_path=resolved_db,
        prune_interval=prune_interval,
        prune_max_age=prune_max_age,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")
