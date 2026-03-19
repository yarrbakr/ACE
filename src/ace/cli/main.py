"""ACE CLI — Typer application with subcommands."""

from __future__ import annotations

import typer

from ace.cli.commands import init, registry, skills, start, status, wallet

app = typer.Typer(
    name="ace",
    help="Agent Capability Exchange — trade AI capabilities with virtual currency.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

registry_app = typer.Typer(
    name="registry",
    help="Manage the ACE public registry.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
registry_app.command(name="start", help="Start the public registry server")(
    registry.registry_start_cmd
)
app.add_typer(registry_app)

app.command(name="init", help="Initialize a new ACE agent node in ~/.ace")(init.init_cmd)
app.command(name="start", help="Start the ACE API server")(start.start_cmd)
app.command(name="balance", help="Show the agent's token balance")(wallet.balance_cmd)
app.command(name="transfer", help="Transfer tokens to another agent")(wallet.transfer_cmd)
app.command(name="mint", help="Mint tokens to own account (dev only)")(wallet.mint_cmd)
app.command(name="register-skill", help="Register a capability from a SKILL.md file")(
    skills.register_skill_cmd
)
app.command(name="search", help="Search for agent capabilities")(skills.search_cmd)
app.command(name="skills", help="List registered skills")(skills.skills_cmd)
app.command(name="status", help="Show the agent's status and health")(status.status_cmd)


def _version_callback(value: bool) -> None:
    if value:
        from ace import __version__

        typer.echo(f"ace {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Agent Capability Exchange CLI."""


if __name__ == "__main__":
    app()
