"""ACE Demo — Agent Capability Exchange end-to-end showcase.

Demonstrates the entire system working: identity, ledger, escrow,
capability registry, and the 8-state transaction engine.

Usage:
    pip install -e .
    python examples/demo.py
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

# ── Rich output (graceful fallback to plain text) ────────────

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console(force_terminal=True)
    RICH = True
except ImportError:
    RICH = False

# ── Core library imports (NO CLI, NO API, NO HTTP) ──────────

from ace.core.capability import (
    CapabilityRegistry,
    SkillDefinition,
    SkillPricing,
    generate_agent_card,
)
from ace.core.escrow import EscrowManager
from ace.core.identity import AgentIdentity
from ace.core.ledger import Ledger
from ace.core.transaction import TransactionEngine


# ── Output helpers ───────────────────────────────────────────


def banner(text: str) -> None:
    """Print a prominent section banner."""
    if RICH:
        console.print(Panel(f"[bold cyan]{text}[/]", expand=False))
    else:
        print(f"\n{'=' * 50}")
        print(f"  {text}")
        print(f"{'=' * 50}")


def header(text: str) -> None:
    """Print a scenario header."""
    if RICH:
        console.print(f"\n[bold yellow]{text}[/]")
    else:
        print(f"\n{text}")


def info(text: str) -> None:
    """Print an info line."""
    if RICH:
        console.print(f"  {text}")
    else:
        print(f"  {text}")


def success(text: str) -> None:
    """Print a success line."""
    if RICH:
        console.print(f"  [green]{text}[/]")
    else:
        print(f"  {text}")


def fail(text: str) -> None:
    """Print a failure line."""
    if RICH:
        console.print(f"  [bold red]{text}[/]")
    else:
        print(f"  FAIL: {text}")


async def print_balances(
    agents: list[tuple[str, str, str]], ledger: Ledger
) -> dict[str, int]:
    """Print a balance table and return {name: balance} dict."""
    balances: dict[str, int] = {}
    for name, aid, _ in agents:
        balances[name] = await ledger.get_balance(aid)

    if RICH:
        table = Table(title="Agent Balances")
        table.add_column("Agent", style="cyan")
        table.add_column("AID", style="dim")
        table.add_column("Balance", justify="right", style="green")
        for name, aid, _ in agents:
            table.add_row(name, aid[:16] + "...", f"{balances[name]:,} AGC")
        console.print(table)
    else:
        print(f"  {'Agent':<14} {'AID':<18} {'Balance':>12}")
        print(f"  {'-'*14} {'-'*18} {'-'*12}")
        for name, aid, _ in agents:
            print(f"  {name:<14} {aid[:16] + '...':<18} {balances[name]:>9,} AGC")
    return balances


def assert_balance(
    balances: dict[str, int], name: str, expected: int
) -> bool:
    """Check a balance and print result. Returns True if passed."""
    actual = balances[name]
    if actual == expected:
        success(f"  {name} balance = {actual:,} AGC  [OK]")
        return True
    fail(f"  {name} balance = {actual:,} AGC (expected {expected:,})")
    return False


# ── Main demo ────────────────────────────────────────────────


async def run_demo() -> bool:
    """Run all demo scenarios. Returns True if all assertions pass."""
    all_passed = True
    tmp_dir = Path(tempfile.mkdtemp(prefix="ace_demo_"))
    db_path = tmp_dir / "demo.db"

    try:
        banner("ACE Demo - Agent Capability Exchange")

        # ── 1. Create agent identities ───────────────────────
        header("Creating agent identities...")
        codegen = AgentIdentity()
        reviewer = AgentIdentity()
        summarizer = AgentIdentity()

        agents = [
            ("CodeGen", codegen.aid, codegen.public_key_b64),
            ("Reviewer", reviewer.aid, reviewer.public_key_b64),
            ("Summarizer", summarizer.aid, summarizer.public_key_b64),
        ]
        for name, aid, _ in agents:
            info(f"{name:>12}  {aid}")

        # ── 2. Initialize shared ledger ──────────────────────
        header("Initializing ledger...")
        ledger = Ledger(db_path)
        await ledger.initialize()

        for _, aid, _ in agents:
            await ledger.create_account(aid)

        # ── 3. Mint tokens ───────────────────────────────────
        header("Minting 10,000 AGC to each agent...")
        for name, aid, _ in agents:
            await ledger.mint(aid, 10_000, f"Initial mint for {name}")

        balances = await print_balances(agents, ledger)

        # ── 4. Register capabilities ─────────────────────────
        header("Registering capabilities...")
        registry = CapabilityRegistry(db_path)
        await registry.initialize()

        escrow_mgr = EscrowManager(ledger)
        engine = TransactionEngine(ledger, escrow_mgr)

        skills_data = [
            ("CodeGen", codegen, "python_code_generation", "Generate Python code from natural language", 100, ["python", "code-generation"]),
            ("Reviewer", reviewer, "code_review", "Review code for bugs and improvements", 75, ["review", "quality"]),
            ("Summarizer", summarizer, "text_summarization", "Summarize text documents concisely", 50, ["nlp", "summarization"]),
        ]
        for agent_name, identity, skill_name, desc, price, tags in skills_data:
            skill = SkillDefinition(
                name=skill_name,
                version="1.0.0",
                description=desc,
                pricing=SkillPricing(amount=price),
                tags=tags,
            )
            card = generate_agent_card(
                name=agent_name,
                description=desc,
                url=f"http://localhost:8000",
                skills=[skill],
                aid=identity.aid,
                public_key_b64=identity.public_key_b64,
            )
            await registry.register(identity.aid, card)
            info(f"  {agent_name}: {skill_name} @ {price} AGC/call")

        # ═══════════════════════════════════════════════════════
        # SCENARIO 1: Simple Transaction
        # ═══════════════════════════════════════════════════════

        header("--- Scenario 1: Simple Transaction ---")
        info("Reviewer wants Python code generated...")

        results = await registry.search("python code generation")
        info(f"Search found {len(results)} result(s): {results[0]['name']}")

        tx = await engine.create_transaction(
            buyer_aid=reviewer.aid,
            seller_aid=codegen.aid,
            capability_id="python_code_generation",
        )
        info(f"Transaction created: {tx.tx_id[:8]}...")

        tx = await engine.submit_quote(tx.tx_id, 100, seller_aid=codegen.aid)
        info("CodeGen quoted 100 AGC")

        tx = await engine.accept_quote(tx.tx_id, buyer_aid=reviewer.aid)
        info("Escrow created - 100 AGC held safely")

        result_hash = hashlib.sha256(b"def hello(): print('world')").hexdigest()
        tx = await engine.deliver_result(tx.tx_id, result_hash, seller_aid=codegen.aid)
        info("CodeGen delivered result")

        tx = await engine.confirm_delivery(tx.tx_id, buyer_aid=reviewer.aid)
        success("Transaction settled! Reviewer paid 100 AGC to CodeGen")

        balances = await print_balances(agents, ledger)
        all_passed &= assert_balance(balances, "CodeGen", 10_100)
        all_passed &= assert_balance(balances, "Reviewer", 9_900)

        # ═══════════════════════════════════════════════════════
        # SCENARIO 2: Currency Circulation
        # ═══════════════════════════════════════════════════════

        header("--- Scenario 2: Currency Circulation ---")
        info("CodeGen wants code review, Reviewer wants summarization...")

        # CodeGen → Reviewer (75 AGC for code review)
        tx1 = await engine.create_transaction(
            buyer_aid=codegen.aid,
            seller_aid=reviewer.aid,
            capability_id="code_review",
        )
        tx1 = await engine.submit_quote(tx1.tx_id, 75, seller_aid=reviewer.aid)
        tx1 = await engine.accept_quote(tx1.tx_id, buyer_aid=codegen.aid)
        tx1 = await engine.deliver_result(
            tx1.tx_id,
            hashlib.sha256(b"LGTM with minor fixes").hexdigest(),
            seller_aid=reviewer.aid,
        )
        tx1 = await engine.confirm_delivery(tx1.tx_id, buyer_aid=codegen.aid)
        info("CodeGen --75 AGC--> Reviewer  (code review)")

        # Reviewer → Summarizer (50 AGC for summarization)
        tx2 = await engine.create_transaction(
            buyer_aid=reviewer.aid,
            seller_aid=summarizer.aid,
            capability_id="text_summarization",
        )
        tx2 = await engine.submit_quote(tx2.tx_id, 50, seller_aid=summarizer.aid)
        tx2 = await engine.accept_quote(tx2.tx_id, buyer_aid=reviewer.aid)
        tx2 = await engine.deliver_result(
            tx2.tx_id,
            hashlib.sha256(b"TL;DR: code is clean").hexdigest(),
            seller_aid=summarizer.aid,
        )
        tx2 = await engine.confirm_delivery(tx2.tx_id, buyer_aid=reviewer.aid)
        info("Reviewer --50 AGC--> Summarizer  (summarization)")

        success("Currency has circulated: CodeGen -> Reviewer -> Summarizer")
        balances = await print_balances(agents, ledger)
        all_passed &= assert_balance(balances, "CodeGen", 10_025)
        all_passed &= assert_balance(balances, "Reviewer", 9_925)
        all_passed &= assert_balance(balances, "Summarizer", 10_050)

        # ═══════════════════════════════════════════════════════
        # SCENARIO 3: Escrow Timeout
        # ═══════════════════════════════════════════════════════

        header("--- Scenario 3: Escrow Timeout ---")
        summarizer_before = await ledger.get_balance(summarizer.aid)
        info("Summarizer initiates transaction with CodeGen...")

        tx3 = await engine.create_transaction(
            buyer_aid=summarizer.aid,
            seller_aid=codegen.aid,
            capability_id="python_code_generation",
        )
        tx3 = await engine.submit_quote(tx3.tx_id, 100, seller_aid=codegen.aid)
        tx3 = await engine.accept_quote(tx3.tx_id, buyer_aid=summarizer.aid)
        info("Escrow created - 100 AGC locked")
        info("Waiting for delivery... (CodeGen never delivers)")

        # Manually refund — simulates timeout without waiting
        await engine.refund(tx3.tx_id)
        success("Transaction timed out - funds safely returned to Summarizer")

        balances = await print_balances(agents, ledger)
        summarizer_after = balances["Summarizer"]
        if summarizer_after == summarizer_before:
            success(f"  Summarizer balance unchanged at {summarizer_after:,} AGC  [OK]")
        else:
            fail(f"  Summarizer balance {summarizer_after:,} (expected {summarizer_before:,})")
            all_passed = False

        # ═══════════════════════════════════════════════════════
        # FINAL SUMMARY
        # ═══════════════════════════════════════════════════════

        total_supply = sum(balances.values())
        invariant_ok = total_supply == 30_000

        if RICH:
            summary = Table.grid(padding=(0, 2))
            summary.add_row("Agents:", "3")
            summary.add_row("Transactions completed:", "3")
            summary.add_row("Transactions refunded:", "1")
            summary.add_row("Total AGC transferred:", "300 AGC")
            summary.add_row("")
            summary.add_row("[bold]Final Balances:[/]")
            summary.add_row(f"  CodeGen:", f"{balances['CodeGen']:,} AGC")
            summary.add_row(f"  Reviewer:", f"{balances['Reviewer']:,} AGC")
            summary.add_row(f"  Summarizer:", f"{balances['Summarizer']:,} AGC")
            summary.add_row("")
            inv = "[OK]" if invariant_ok else "[FAIL]"
            summary.add_row(f"Invariant:", f"Total supply = {total_supply:,} AGC {inv}")
            if all_passed and invariant_ok:
                summary.add_row("", "[bold green]The agent economy is working![/]")
            console.print(Panel(summary, title="[bold]ACE Demo - Final Summary[/]", expand=False))
        else:
            print(f"\n{'=' * 44}")
            print("  ACE Demo - Final Summary")
            print(f"{'=' * 44}")
            print(f"  Agents:                  3")
            print(f"  Transactions completed:  3")
            print(f"  Transactions refunded:   1")
            print(f"  Total AGC transferred:   300 AGC")
            print()
            print(f"  Final Balances:")
            print(f"    CodeGen:    {balances['CodeGen']:>10,} AGC")
            print(f"    Reviewer:   {balances['Reviewer']:>10,} AGC")
            print(f"    Summarizer: {balances['Summarizer']:>10,} AGC")
            print()
            inv = "[OK]" if invariant_ok else "[FAIL]"
            print(f"  Invariant: Total supply = {total_supply:,} AGC {inv}")
            if all_passed and invariant_ok:
                print(f"\n  The agent economy is working!")
            print(f"{'=' * 44}")

        all_passed &= invariant_ok
        return all_passed

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    """Entry point — run the async demo with graceful error handling."""
    try:
        passed = asyncio.run(run_demo())
        sys.exit(0 if passed else 1)
    except KeyboardInterrupt:
        print("\nDemo interrupted.")
        sys.exit(130)
    except Exception as exc:
        if RICH:
            console.print(f"[bold red]Demo failed: {exc}[/]")
        else:
            print(f"Demo failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
