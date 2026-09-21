# maple-pipeline

Onchain data pipeline behind the Maple × Robinhood dashboard.

Raw logs from two chains → decoded tables in Neon Postgres → daily refresh.

## How it runs

    python pipeline/run_all.py        # logs -> blocks -> decode -> prune -> state -> llama
    python pipeline/fetch_logs.py rh. # one chain
    schema.sql                        # tables

Runs daily at 06:15 UTC via `.github/workflows/daily.yml` (secrets: `DATABASE_URL`, `INFURA_URL`, `RPC_URL`).

Two chains: Ethereum (Infura for logs/blocks, Alchemy for `eth_call`) and Robinhood Chain 4663 (public RPC
for logs; Alchemy `robinhood-mainnet` for batched block lookups). Chain-level TVL/fees come from DeFiLlama
and are labeled as such on the dashboard.

## What's indexed
- syrupUSDG pool (Ethereum + Robinhood Chain): transfers, loans, interest, `totalAssets()` state
- Robinhood Earn: Steakhouse USDG vault deposits/withdrawals, Morpho Blue market flows and allocation
- Robinhood stock tokens: mint/burn events; Morpho markets using them as collateral
- USDG supply on Robinhood Chain (mint/burn only — never full transfer history)
- SYRUP price (CoinGecko) and buybacks (`config/syrup_buybacks.csv`)
- Robinhood Chain activity (Blockscout stats-service: txns, accounts, gas fees, smart wallets) and token holder counts (Blockscout REST, `BLOCKSCOUT_KEY`)
- Capital on chain: ETH in the canonical L1 bridge (`0xDf87…`, docs.robinhood.com/chain/protocol-contracts) + USDG minted natively; sequencer batch cost from the SequencerInbox on Ethereum

## RPC notes
- Alchemy free tier: `eth_getLogs` capped at 10-block range and throttles (429) on burst. Use for `eth_call` only.
- Infura free tier: no range cap — use for Ethereum logs and blocks. Rate-limit errors come back *inside* HTTP-200 batch responses; check every item has `result`.
- Robinhood Chain: public RPC handles 2M-block `getLogs` chunks; keep Alchemy block lookups ≤2 threads.
- Robinhood block timestamps: exact for syrup transfers/markets, anchor + interpolation for the ~290k Morpho blocks (daily buckets only).
- Neon drops idle connections during long fetches: fresh connection per insert, `COPY` not `executemany`. Raw rows are pruned after decode to stay under the 512 MB free tier.

## Setup
    pip install -r requirements.txt
    cp .env.example .env      # RPC_URL (Alchemy), INFURA_URL, DATABASE_URL, BLOCKSCOUT_KEY

## Layout
    config/       contract map (contracts.csv), ABI + event bundle (abis.json), buybacks csv
    pipeline/     fetch_logs.py · fetch_blocks.py · decode.py · fetch_state.py · fetch_llama.py · fetch_syrup.py · fetch_blockscout.py · fetch_bridge.py · fetch_l1_cost.py · run_all.py
    pipeline/experimental/  parked block sampler
