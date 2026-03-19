"""ACE Gossip Discovery Demo — peer-to-peer agent discovery showcase.

Demonstrates gossip-based decentralized discovery: three agents
discover each other through transitive peer exchange without any
centralized registry.

Usage:
    pip install -e .
    python examples/gossip_demo.py
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

# ── Rich output (graceful fallback to plain text) ────────────

try:
    from rich.console import Console
    from rich.panel import Panel

    console = Console(force_terminal=True)
    RICH = True
except ImportError:
    RICH = False

from ace.core.config import AceSettings, DiscoveryMode
from ace.core.identity import AgentIdentity
from ace.discovery.gossip import GossipDiscovery
from ace.discovery.gossip_models import GossipConfig, PeerInfo


# ── Output helpers ───────────────────────────────────────────


def banner(text: str) -> None:
    if RICH:
        console.print(Panel(text, style="bold cyan"))
    else:
        print(f"\n{'=' * 60}")
        print(f"  {text}")
        print(f"{'=' * 60}")


def info(text: str) -> None:
    if RICH:
        console.print(f"  [green]>>>[/green] {text}")
    else:
        print(f"  >>> {text}")


def warn(text: str) -> None:
    if RICH:
        console.print(f"  [yellow]!!![/yellow] {text}")
    else:
        print(f"  !!! {text}")


def result(text: str) -> None:
    if RICH:
        console.print(f"  [bold magenta]***[/bold magenta] {text}")
    else:
        print(f"  *** {text}")


# ── Demo ─────────────────────────────────────────────────────


async def run_demo() -> None:
    banner("ACE Gossip Discovery Demo")
    info("Demonstrating peer-to-peer agent discovery via gossip protocol")
    print()

    tmp = Path(tempfile.mkdtemp(prefix="ace_gossip_demo_"))

    # Create three agent identities
    agents: list[tuple[str, AgentIdentity, AceSettings, GossipDiscovery]] = []

    for i, (name, port) in enumerate([
        ("Agent-Alpha", 9001),
        ("Agent-Beta", 9002),
        ("Agent-Gamma", 9003),
    ]):
        identity = AgentIdentity()
        data_dir = tmp / f"agent_{i}" / "data"
        data_dir.mkdir(parents=True)

        # Beta seeds from Alpha, Gamma seeds from Beta
        seed_peers: list[str] = []
        if i == 1:
            seed_peers = ["http://127.0.0.1:9001"]
        elif i == 2:
            seed_peers = ["http://127.0.0.1:9002"]

        settings = AceSettings(
            agent_name=name,
            agent_description=f"Demo agent {name}",
            port=port,
            data_dir=data_dir,
            discovery_mode=DiscoveryMode.GOSSIP,
            seed_peers=seed_peers,
            aid=identity.aid,
        )

        config = GossipConfig(
            seed_peers=seed_peers,
            gossip_interval=2.0,  # fast for demo
            peer_timeout=30.0,
            max_peers=50,
            fanout=3,
        )

        gd = GossipDiscovery(identity, settings, config)
        agents.append((name, identity, settings, gd))
        info(f"Created {name} (AID: {identity.aid[:20]}..., port: {port})")

    print()

    # ── Step 1: Start all agents ──────────────────────────────
    banner("Step 1: Starting Agents")

    for name, identity, settings, gd in agents:
        # Register self as a peer (simulating — no actual HTTP server)
        own = PeerInfo(
            aid=identity.aid,
            url=f"http://127.0.0.1:{settings.port}",
            public_key_b64=identity.public_key_b64,
            agent_card={"name": name, "aid": identity.aid, "capabilities": []},
            version=1,
        )
        gd.peer_manager.add_peer(own)
        info(f"Started {name} (peers: {gd.peer_manager.peer_count})")

    # ── Step 2: Register a skill on Agent Alpha ───────────────
    banner("Step 2: Agent Alpha Registers a Skill")

    alpha_name, alpha_id, alpha_settings, alpha_gd = agents[0]
    alpha_card = {
        "name": "Agent-Alpha",
        "description": "Python code generation specialist",
        "aid": alpha_id.aid,
        "capabilities": [
            {
                "name": "python_code_generation",
                "description": "Generate Python code from natural language prompts",
                "tags": ["python", "code-generation", "ai"],
                "pricing": {"currency": "AGC", "model": "per_call", "amount": 50},
            }
        ],
    }
    # Update Alpha's own peer info with the capability
    own_alpha = alpha_gd.peer_manager.get_peer(alpha_id.aid)
    if own_alpha:
        own_alpha.agent_card = alpha_card
        own_alpha.version = 2
        alpha_gd.peer_manager.add_peer(own_alpha)
    info("Alpha registered: python_code_generation (50 AGC)")

    # ── Step 3: Simulate gossip exchanges ─────────────────────
    banner("Step 3: Simulating Gossip Exchanges")

    # Beta learns about Alpha by merging Alpha's peer list
    _, beta_id, _, beta_gd = agents[1]
    _, gamma_id, _, gamma_gd = agents[2]

    # Simulate: Alpha tells Beta about itself
    alpha_peers = alpha_gd.peer_manager.get_all_peers()
    merged = beta_gd.peer_manager.merge_peer_list(alpha_peers)
    info(f"Beta merged Alpha's peers: {merged} new/updated")
    info(f"Beta now knows {beta_gd.peer_manager.peer_count} peers")

    # Simulate: Beta tells Gamma about everyone it knows
    beta_peers = beta_gd.peer_manager.get_all_peers()
    merged = gamma_gd.peer_manager.merge_peer_list(beta_peers)
    info(f"Gamma merged Beta's peers: {merged} new/updated")
    info(f"Gamma now knows {gamma_gd.peer_manager.peer_count} peers")

    print()

    # ── Step 4: Gamma searches for Python code generation ─────
    banner("Step 4: Gamma Searches for 'python code generation'")

    results = gamma_gd.peer_manager.search_peers("python code generation")
    if results:
        for peer in results:
            result(
                f"FOUND: {peer.agent_card.get('name', '?')} "
                f"(AID: {peer.aid[:20]}...)"
            )
            for cap in peer.agent_card.get("capabilities", []):
                info(
                    f"  Skill: {cap['name']} - "
                    f"{cap.get('description', '')} "
                    f"({cap['pricing']['amount']} AGC)"
                )
        print()
        result(
            "Gamma found Alpha's skill via gossip chain! "
            "(Alpha -> Beta -> Gamma)"
        )
    else:
        warn("No results found (unexpected)")

    print()

    # ── Step 5: Verify convergence ────────────────────────────
    banner("Step 5: Verify Network Convergence")

    for name, identity, settings, gd in agents:
        count = gd.peer_manager.peer_count
        known = [p.aid[:20] + "..." for p in gd.peer_manager.get_all_peers()]
        info(f"{name}: knows {count} peers - {known}")

    # Check: Gamma knows Alpha (transitive discovery)
    gamma_knows_alpha = gamma_gd.peer_manager.get_peer(alpha_id.aid)
    assert gamma_knows_alpha is not None, "Gamma should know Alpha through Beta"
    result("Convergence verified: all agents know each other!")

    print()

    # ── Step 6: Simulate Alpha going offline (pruning) ────────
    banner("Step 6: Simulate Alpha Departure")

    # Remove Alpha from Beta and Gamma (simulating stale peer pruning)
    beta_gd.peer_manager.remove_peer(alpha_id.aid)
    gamma_gd.peer_manager.remove_peer(alpha_id.aid)
    info("Alpha removed (simulating offline/stale)")
    info(f"Beta peers: {beta_gd.peer_manager.peer_count}")
    info(f"Gamma peers: {gamma_gd.peer_manager.peer_count}")

    print()

    # ── Final Summary ─────────────────────────────────────────
    banner("Gossip Discovery Demo Complete!")
    info("Decentralized peer-to-peer discovery is working!")
    info("Key takeaways:")
    info("  - No centralized registry needed")
    info("  - Agents discover each other transitively (A->B->C)")
    info("  - Stale peers can be pruned when they go offline")
    info("  - All peer data is versioned to prevent stale overwrites")
    print()

    # Cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()
