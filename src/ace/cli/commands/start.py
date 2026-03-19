"""ace start — launch the FastAPI server."""

from __future__ import annotations

import os
import sys

import typer
from rich import print as rprint


def start_cmd(
    port: int | None = typer.Option(None, "--port", "-p", help="Override server port"),
    host: str = typer.Option(
        "127.0.0.1", "--host", "-H", help="Bind address (default: 127.0.0.1)"
    ),
    daemon: bool = typer.Option(False, "--daemon", "-d", help="Run in background"),
    public: bool = typer.Option(
        False, "--public", help="Register with the public registry on startup"
    ),
) -> None:
    """Start the ACE API server."""
    from ace.core.config import DEFAULT_ACE_DIR, DiscoveryMode, require_config
    from ace.core.identity import AgentIdentity

    # Load config
    try:
        settings = require_config()
    except Exception as exc:
        rprint(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None

    # Override discovery mode when --public is used
    if public:
        settings.discovery_mode = DiscoveryMode.REGISTRY

    server_port = port or settings.port

    # Load identity
    key_path = DEFAULT_ACE_DIR / "identity.key"
    if not key_path.exists():
        rprint("[red]Error:[/red] No identity found. Run 'ace init' first.")
        raise typer.Exit(code=1)

    password = os.environ.get("ACE_PASSWORD")
    if not password:
        password = typer.prompt("Enter identity password", hide_input=True)

    try:
        identity = AgentIdentity.load_encrypted(key_path, password)
    except Exception:
        rprint("[red]Error:[/red] Failed to decrypt identity. Wrong password?")
        raise typer.Exit(code=1) from None

    # Warn about 0.0.0.0 on Windows
    if host == "0.0.0.0" and sys.platform == "win32":
        rprint(
            "[yellow]Warning:[/yellow] Binding to 0.0.0.0 on Windows may "
            "trigger a firewall prompt."
        )

    # Startup banner
    rprint("\n[bold green]ACE Agent Starting[/bold green]")
    rprint(f"   Agent:  [cyan]{settings.agent_name}[/cyan]")
    rprint(f"   AID:    [dim]{identity.aid}[/dim]")
    rprint(f"   Port:   [cyan]{server_port}[/cyan]")
    rprint(f"   Host:   [cyan]{host}[/cyan]")
    if public:
        rprint(f"   Registry: [cyan]{settings.registry_url}[/cyan] (public mode)")
    rprint(f"   Card:   [link]http://{host}:{server_port}/.well-known/agent.json[/link]")
    rprint(f"   Docs:   [link]http://{host}:{server_port}/docs[/link]")
    rprint()

    # Launch uvicorn programmatically
    import uvicorn

    from ace.api.server import create_app

    app = create_app(settings=settings, identity=identity)
    uvicorn.run(app, host=host, port=server_port, log_level="info")
