# MEFAI Signal Agent

**An open-source, self-hosted AI agent on BNB Chain that delivers [MEFAI](https://mefai.io)'s live crypto trading signals as verifiable on-chain jobs.**

A buyer negotiates a signed quote, funds the job in `$U` via **x402**, and the agent
delivers MEFAI's current signals as an **ERC-8183** deliverable anchored on BNB Smart
Chain. Identity is registered under **ERC-8004**. The reasoning is done by a
**BNB-native LLM (Pieverse)** · no closed AI provider, no proprietary API keys, every
layer runs on BNB Chain rails.

**Live showcase:** https://mefai.io/bnb-agent/

---

## Why this exists

MEFAI runs a live trading-signal engine (40+ assets, 6 timeframes). This agent turns
that feed into a **machine-payable, verifiable product**: any other agent or app on BNB
Chain can discover it (ERC-8004), pay for a signal job (x402 / ERC-8183), and read the
result straight from the chain. No accounts, no keys, no trust in an off-chain API.

- **On-chain identity** · ERC-8004 registry, discoverable and verifiable.
- **On-chain jobs & escrow** · ERC-8183: negotiate → fund → deliver → settle.
- **Self-funding payments** · x402 in `$U`; the agent pays on-chain for what it needs.
- **BNB-native LLM** · Pieverse, zero-deposit `auto/free` model, on-chain metered.
- **Sole signer** · the agent holds its own wallet and is the only signer of every
  quote, delivery and settlement. Pricing is fixed; signing is deterministic code, never
  an LLM-callable tool.

## How it works

```
buyer                         MEFAI Signal Agent (sole signer)
  │  negotiate  ───────────▶  read fixed list price → clamp → EIP-191 sign the offer
  │  ◀───────────────────────  signed quote (price, currency, provider_sig)
  │  createJob + fund (x402) ─────────────────────────────────▶ escrow on BSC
  │  notify_funded ─────────▶  verify funded job → LLM pulls MEFAI signals →
  │                            write deliverable → sign `submit` (on-chain)
  │  read deliverable from CHAIN  ◀────────────  SUBMITTED / get_deliverable_url
```

The LLM only runs **after** a job is verified funded, and it can only **read** · the
value tools (`mefai_latest_signals`, `mefai_signal_for_symbol`) are read-only, and all
signing lives in fixed code, never in the model.

## Project layout

```
app/agent/
  main.py            A2A entrypoint; builds the agent + LLM work hook
  seller_core.py     ERC-8183 seller logic (negotiate / notify_funded / deliver)
  executor.py        A2A skill dispatch
  signing.py         deterministic signing (quote / submit / settle) · never an LLM tool
  tools.py           read-only tools exposed to the LLM
  mefai_signals.py   MEFAI live-signal reader (SQLite-direct, HTTP fallback)  <- the product
  agent_card.py      ERC-8004 / A2A discoverable identity
  managed_model.py   BNB-native LLM (Pieverse) wrapper
  studio.toml        network, wallet, pricing (ERC-8183), LLM config
showcase/
  index.html         the live showcase page (self-contained, no build step)
  update_feed.py     writes signals.json from MEFAI's signal DB (stdlib only)
```

## Signal source

The agent reads MEFAI signals from, in priority order:

1. **`MEFAI_SIGNAL_DB`** · path to MEFAI's signals SQLite. When co-located with a MEFAI
   deployment, the agent reads the latest signal per symbol+timeframe **directly**,
   read-only, with no tier gate and no empty responses. This is the recommended path.
2. **`MEFAI_SIGNALS_URL`** · HTTP fallback (e.g. a MEFAI signals endpoint).

A single signal:

```json
{ "symbol": "BTCUSDT.P", "timeframe": "1h", "side": "LONG", "price": 62516.8, "timestamp": 1784015160 }
```

## Configuration

Secrets live at the workspace root under `.studio/.env.local` (git-ignored, never
published). Key variables:

| Variable | Purpose |
|---|---|
| `WALLET_PASSWORD` | unlocks the agent's encrypted keystore |
| `PIEVERSE_LLM_API_KEY` | BNB-native LLM key (created by `bag llm activate`, $0 default) |
| `MEFAI_SIGNAL_DB` | path to MEFAI's signals SQLite (primary signal source) |
| `MEFAI_SIGNALS_URL` | HTTP signal endpoint (fallback) |

## Quick start

Built with [BNB Agent Studio](https://pypi.org/project/bnbagent-studio/) (`bag`).

```bash
# 1. scaffold + install
bag init myagent --network bsc-testnet --wallet-kind evm-local --llm-provider pieverse-llm
cd myagent/app/agent && pip install -e .

# 2. wallet + LLM (zero-deposit, no funding needed to start)
bag wallet new
bag llm activate

# 3. point at your signal source and run
export MEFAI_SIGNAL_DB=/path/to/signal.db
bag doctor
bag dev
```

## Self-host the showcase feed

The showcase page reads a `signals.json` file refreshed on a short timer:

```ini
# /etc/systemd/system/mefai-bnb-agent-feed.service
[Service]
Type=oneshot
Environment=MEFAI_SIGNAL_DB=/path/to/signal.db
Environment=SHOWCASE_OUT=/path/to/webroot/bnb-agent/signals.json
ExecStart=/usr/bin/python3 /path/to/showcase/update_feed.py
```

Pair it with a `.timer` firing every 30s. The writer is atomic and never overwrites a
good feed with an empty one.

## Security model

- The agent is the **sole on-chain signer**; the private key never leaves the encrypted
  keystore and is never bundled into any deploy artifact.
- **Pricing is fixed** in `studio.toml` and clamped before signing · the LLM never prices.
- **All signing is deterministic code** (`signing.py`) · never a tool the LLM can call.
- **LLM tools are read-only** · no chain writes, no wallet spend, no signing.

## Disclaimer

MEFAI signals are **informational only** and do not constitute financial advice.
On-chain figures in the showcase are from BNB Smart Chain testnet.

## License

[MIT](./LICENSE) (c) 2026 MEFAI
