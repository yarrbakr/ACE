# ACE Demo

Self-contained end-to-end demonstration of the Agent Capability Exchange.

## Quick Start

```bash
pip install -e .
python examples/demo.py
```

## What the Demo Shows

1. **Simple Transaction** — Reviewer pays CodeGen 100 AGC for code generation. Full lifecycle: create, quote, fund, deliver, settle.
2. **Currency Circulation** — Money flows through the economy: CodeGen pays Reviewer 75 AGC for code review, Reviewer pays Summarizer 50 AGC for summarization.
3. **Escrow Protection** — Summarizer requests work from CodeGen, but CodeGen never delivers. The escrow automatically refunds the buyer.

## Architecture

The demo uses the **core library directly** (identity, ledger, escrow, transaction engine, capability registry) — no CLI, no API server, no HTTP. This proves the core modules work as a standalone library.

## Expected Output

```
╭─────────────────────────────────────────────────╮
│ ACE Demo — Agent Capability Exchange            │
╰─────────────────────────────────────────────────╯

Creating agent identities...
      CodeGen  aid:...
     Reviewer  aid:...
   Summarizer  aid:...

Minting 10,000 AGC to each agent...
┌────────────┬──────────────────┬─────────────┐
│ Agent      │ AID              │     Balance │
├────────────┼──────────────────┼─────────────┤
│ CodeGen    │ aid:...          │  10,000 AGC │
│ Reviewer   │ aid:...          │  10,000 AGC │
│ Summarizer │ aid:...          │  10,000 AGC │
└────────────┴──────────────────┴─────────────┘

═══ Scenario 1: Simple Transaction ═══
  ...
  Transaction settled! Reviewer paid 100 AGC to CodeGen

═══ Scenario 2: Currency Circulation ═══
  ...
  Currency has circulated: CodeGen → Reviewer → Summarizer

═══ Scenario 3: Escrow Timeout ═══
  ...
  Transaction timed out — funds safely returned to Summarizer

╭──────────────────────────────────────╮
│ ACE Demo — Final Summary             │
│                                      │
│ Agents:                 3            │
│ Transactions completed: 3            │
│ Transactions refunded:  1            │
│ Total AGC transferred:  300 AGC      │
│                                      │
│ Final Balances:                      │
│   CodeGen:    10,025 AGC             │
│   Reviewer:    9,925 AGC             │
│   Summarizer: 10,050 AGC            │
│                                      │
│ Invariant: Total supply = 30,000 AGC │
│ The agent economy is working!        │
╰──────────────────────────────────────╯
```

## Notes

- Uses a temporary SQLite database (auto-cleaned after run)
- Works on Windows, macOS, and Linux
- Rich library provides colorful output; falls back to plain text if not installed
- Exit code 0 = all assertions passed, 1 = failure
