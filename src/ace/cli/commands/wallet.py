"""ace balance / ace transfer / ace mint — wallet operations."""

from __future__ import annotations

import asyncio

import typer
from rich import print as rprint

from ace.core.config import DEFAULT_ACE_DIR, require_config
from ace.core.exceptions import AccountNotFoundError, InsufficientBalanceError
from ace.core.identity import AgentIdentity
from ace.core.ledger import Ledger


def _load_identity() -> AgentIdentity:
    """Load the agent identity, prompting for password."""
    key_path = DEFAULT_ACE_DIR / "identity.key"
    if not key_path.exists():
        typer.echo("No identity found. Run 'ace init' first.")
        raise typer.Exit(code=1)
    password = typer.prompt("Identity password", hide_input=True)
    return AgentIdentity.load_encrypted(key_path, password)


def _get_ledger() -> Ledger:
    """Create a Ledger instance from the configured data directory."""
    settings = require_config()
    db_path = settings.data_dir / "ace.db"
    return Ledger(db_path)


def balance_cmd() -> None:
    """Show the agent's current token balance."""
    ledger = _get_ledger()
    identity = _load_identity()

    async def _run() -> int:
        await ledger.initialize()
        try:
            return await ledger.get_balance(identity.aid)
        except AccountNotFoundError:
            return 0

    balance = asyncio.run(_run())
    rprint(
        f"Agent: [bold]{identity.aid}[/bold]  Balance: [bold green]{balance:,} AGC[/bold green]"
    )


def transfer_cmd(
    to_aid: str = typer.Argument(help="Recipient Agent ID"),
    amount: int = typer.Argument(help="Number of tokens to transfer"),
    memo: str = typer.Option("", "--memo", "-m", help="Transfer memo"),
) -> None:
    """Transfer tokens to another agent."""
    if amount <= 0:
        typer.echo("Amount must be a positive integer.")
        raise typer.Exit(code=1)

    ledger = _get_ledger()
    identity = _load_identity()

    async def _run() -> str:
        await ledger.initialize()
        return await ledger.transfer(
            from_aid=identity.aid,
            to_aid=to_aid,
            amount=amount,
            description=memo,
        )

    try:
        tx_id = asyncio.run(_run())
        rprint("[bold green]Transfer successful![/bold green]")
        typer.echo(f"  Transaction : {tx_id}")
        typer.echo(f"  From        : {identity.aid}")
        typer.echo(f"  To          : {to_aid}")
        typer.echo(f"  Amount      : {amount:,} AGC")
    except InsufficientBalanceError as e:
        rprint(f"[bold red]Transfer failed:[/bold red] {e}")
        raise typer.Exit(code=1) from None
    except AccountNotFoundError as e:
        rprint(f"[bold red]Transfer failed:[/bold red] {e}")
        raise typer.Exit(code=1) from None


def mint_cmd(
    amount: int = typer.Argument(help="Number of tokens to mint"),
) -> None:
    """Mint tokens to own account (development only)."""
    if amount <= 0:
        typer.echo("Amount must be a positive integer.")
        raise typer.Exit(code=1)

    rprint("[bold yellow]Warning:[/bold yellow] This is a development-only command.")

    ledger = _get_ledger()
    identity = _load_identity()

    async def _run() -> str:
        await ledger.initialize()
        # Ensure the agent's account exists
        try:
            await ledger.get_balance(identity.aid)
        except AccountNotFoundError:
            await ledger.create_account(identity.aid)
        return await ledger.mint(
            to_aid=identity.aid,
            amount=amount,
            description=f"CLI mint {amount} AGC",
        )

    try:
        tx_id = asyncio.run(_run())
        rprint(f"[bold green]Minted {amount:,} AGC[/bold green]")
        typer.echo(f"  Transaction : {tx_id}")
        typer.echo(f"  Account     : {identity.aid}")
    except AccountNotFoundError as e:
        rprint(f"[bold red]Mint failed:[/bold red] {e}")
        raise typer.Exit(code=1) from None
