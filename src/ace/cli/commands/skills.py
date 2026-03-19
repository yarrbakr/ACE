"""ace register-skill / ace search / ace skills — capability management."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import typer
from rich import print as rprint
from rich.table import Table

from ace.core.capability import (
    CapabilityRegistry,
    SkillParser,
    generate_agent_card,
)
from ace.core.config import DEFAULT_ACE_DIR, require_config
from ace.core.exceptions import SkillParseError


def _get_registry() -> tuple[CapabilityRegistry, Path]:
    """Create a CapabilityRegistry from the configured data directory."""
    settings = require_config()
    db_path = settings.data_dir / "ace.db"
    return CapabilityRegistry(db_path), settings.data_dir


def _skills_dir() -> Path:
    """Return the ~/.ace/skills directory, creating it if needed."""
    skills = DEFAULT_ACE_DIR / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    return skills


def register_skill_cmd(
    path: Path = typer.Argument(help="Path to a SKILL.md file"),
) -> None:
    """Register a capability from a SKILL.md file."""
    resolved = Path(path).resolve()
    if not resolved.exists():
        rprint(f"[bold red]File not found:[/bold red] {resolved}")
        raise typer.Exit(code=1)

    content = resolved.read_text(encoding="utf-8")

    try:
        skill = SkillParser.parse(content)
    except SkillParseError as exc:
        rprint(f"[bold red]Parse error:[/bold red] {exc}")
        raise typer.Exit(code=1) from None

    dest_dir = _skills_dir()
    dest = dest_dir / f"{skill.name}.md"
    shutil.copy2(resolved, dest)

    settings = require_config()
    registry, _ = _get_registry()

    agent_card = generate_agent_card(
        name=settings.agent_name,
        description=settings.agent_description,
        url=f"http://localhost:{settings.port}",
        skills=[skill],
        aid=settings.aid,
        public_key_b64="",
    )

    async def _run() -> None:
        await registry.initialize()
        await registry.register(settings.aid, agent_card)

    asyncio.run(_run())

    price_label = f"{skill.pricing.amount} {skill.pricing.currency}/{skill.pricing.model}"
    tags_label = ", ".join(skill.tags) if skill.tags else "(none)"

    rprint("[bold green]✅ Skill registered![/bold green]")
    rprint(f"   Name:    [bold]{skill.name}[/bold]")
    rprint(f"   Version: {skill.version}")
    rprint(f"   Price:   {price_label}")
    rprint(f"   Tags:    {tags_label}")
    rprint(f"   Stored:  {dest}")


def search_cmd(
    query: str = typer.Argument(help="Search query for capabilities"),
    max_price: int | None = typer.Option(None, "--max-price", help="Maximum price filter"),
) -> None:
    """Search for agent capabilities in the registry."""
    registry, _ = _get_registry()

    async def _run() -> list[dict]:
        await registry.initialize()
        return await registry.search(query, max_price=max_price)

    results = asyncio.run(_run())

    if not results:
        rprint(
            f"[yellow]No skills found matching '{query}'.[/yellow]\n"
            "Try different keywords or remove the --max-price filter."
        )
        return

    table = Table(title=f"Search results for '{query}'")
    table.add_column("AID", style="dim", max_width=24)
    table.add_column("Skill", style="bold")
    table.add_column("Price", justify="right")
    table.add_column("Tags", style="cyan")

    for row in results:
        aid_display = row["aid"][:24] + "…" if len(row["aid"]) > 24 else row["aid"]
        table.add_row(
            aid_display,
            row["name"],
            f"{row['price']} AGC",
            row["tags"] or "-",
        )

    rprint(table)


def skills_cmd() -> None:
    """List all skills this agent has registered."""
    registry, _ = _get_registry()

    async def _run() -> list[dict]:
        await registry.initialize()
        return await registry.list_skills()

    results = asyncio.run(_run())

    if not results:
        rprint(
            "[yellow]No skills registered yet.[/yellow] Register one with:\n"
            "  ace register-skill ./my_skill.md"
        )
        return

    table = Table(title="Registered Skills")
    table.add_column("Name", style="bold")
    table.add_column("Description", max_width=40)
    table.add_column("Price", justify="right")
    table.add_column("Tags", style="cyan")

    for row in results:
        desc = row["description"]
        if len(desc) > 40:
            desc = desc[:37] + "..."
        table.add_row(
            row["name"],
            desc,
            f"{row['price']} AGC",
            row["tags"] or "-",
        )

    rprint(table)
