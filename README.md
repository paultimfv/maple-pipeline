# maple-pipeline

## 2026-09-18 — Robinhood dashboard pipeline (Postgres/Neon)

Scope narrowed to what `dune.com/ptimfv_team_000f9a82/maplexrobinhood` needs. DuckDB replaced by Neon Postgres
(`DATABASE_URL` in .env). Two chains: Ethereum (Infura for logs/blocks, Alchemy for eth_call) and
Robinhood Chain 4663 (public RPC for logs; Alchemy `robinhood-mainnet` for batched block lookups).

    python pipeline/run_all.py        # daily: logs -> blocks -> decode -> state -> llama
    python pipeline/fetch_logs.py rh. # one chain
    schema.sql                        # tables

Robinhood block timestamps: exact for syrup transfers/markets, anchor+interpolated for the ~270k
Morpho blocks (daily buckets only). Alchemy eth-mainnet free tier throttles hard (429) — keep Ethereum
block lookups on Infura. Web app: ~/Documents/maple-dashboard/web (Next.js, reads the same DB).


Rebuild of the Maple Finance "Business Analysis" Dune dashboard from raw chain data,
starting with syrupUSDG.

## Status — 2026-09-14

**Done**
- Contract map extracted: 239 addresses (Maple official registry + Dune event stats),
  9 ABI bundles, 89 events with topic0, 147 fixed-term loan contracts. `config/`
- Dune dashboard exported: 46 CSVs, inventoried by source type in `config/dashboard_inventory.csv`
- Findings that change the writeup: `0x191ac162…` is Maple's SyrupRouter, not a Robinhood
  vault; OTC revenue (46% of total) is an offchain Maple-uploaded dataset; Sky/Aave
  strategies dormant since Apr 2026; Robinhood Chain leg of syrupUSDG exists in Dune data.

**Next (this week)** — syrupUSDG module, both chains
- Ethereum `0x87b65c4aaffa76881f9e96f3e7ed945ddfc3cd7a` + Robinhood Chain deployment
- Transfer events + periodic `totalAssets()`, ~10 weeks of history
- Reusable: takes address + chain + ABI, not a one-off script
- Reconcile vs Etherscan supply and Maple's Dune figure before publishing

**Then** — piece one: syrupUSDG concentration, 3 live charts, disclosure block, repo linked.

## RPC notes
- Alchemy free tier: `eth_getLogs` capped at 10-block range. Fine for `eth_call`, useless for backfill.
- Infura free tier: no range cap. Use for logs.
- Public RPCs tested (publicnode, llamarpc, drpc, 1rpc, merkle): none usable for ranged getLogs.

## Setup
    pip install -r requirements.txt
    cp .env.example .env      # RPC_URL (Alchemy), INFURA_URL

## Layout
    config/     contract map, ABIs, dashboard inventory
    pipeline/   fetch_logs.py · decode.py · validate.py  (full 8-table backfill; deferred)
    db/         maple.duckdb
