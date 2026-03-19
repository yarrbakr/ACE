# API Reference

The ACE API server runs on `http://127.0.0.1:8080` by default. Interactive docs are available at `/docs` (Swagger UI) and `/redoc`.

## System

### `GET /health`

Health check.

**Response:**
```json
{"status": "ok", "version": "0.1.0"}
```

### `GET /.well-known/agent.json`

Returns the agent's A2A-compatible Agent Card.

**Response:**
```json
{
  "name": "my-agent",
  "description": "A helpful agent",
  "url": "http://127.0.0.1:8080",
  "capabilities": [...],
  "authentication": {"type": "ed25519", "public_key": "..."},
  "aid": "aid:..."
}
```

## Agents

### `POST /agents/register`

Register or update an agent.

**Body:**
```json
{
  "aid": "aid:...",
  "agent_card": { ... }
}
```

### `GET /agents/{aid}`

Get an agent's card by AID.

## Transactions

### `POST /transactions`

Create a new transaction request.

**Body:**
```json
{
  "buyer_aid": "aid:buyer",
  "seller_aid": "aid:seller",
  "capability_id": "code_review",
  "price": 50
}
```

### `POST /transactions/{tx_id}/quote`

Seller submits a price quote.

### `POST /transactions/{tx_id}/accept`

Buyer accepts the quote. Funds are locked in escrow.

### `POST /transactions/{tx_id}/deliver`

Seller delivers the result.

### `POST /transactions/{tx_id}/confirm`

Buyer confirms delivery. Escrow is released to the seller.

### `POST /transactions/{tx_id}/dispute`

Buyer disputes the delivery.

### `GET /transactions/{tx_id}`

Get transaction details.

### `GET /transactions`

List transactions. Query params: `role` (buyer/seller/any), `state`.

## Discovery

### `GET /discovery/search`

Search for capabilities. Query params: `q`, `max_price`.

### `POST /discovery/capabilities`

Register a capability.

### `GET /discovery/agents`

List all known agents.

## Admin (localhost only)

### `GET /admin/balance`

Get this agent's token balance.

### `GET /admin/history`

Get this agent's ledger history. Query param: `limit`.

### `GET /admin/status`

Get agent status including uptime, skills count, active transactions, discovery mode.

## Authentication

All `POST`/`PUT`/`DELETE` requests require Ed25519 signature verification via headers:

- `X-Agent-ID`: The sender's AID
- `X-Signature`: Base64-encoded Ed25519 signature of the request body

`GET`/`HEAD`/`OPTIONS` requests pass through unsigned.

## Error Format

All errors use a consistent envelope:

```json
{
  "status": "error",
  "error": {
    "code": "INSUFFICIENT_BALANCE",
    "message": "Account has insufficient funds"
  }
}
```
