# maple-pipeline

Onchain data pipeline for Maple Finance on Ethereum and Robinhood Chain. Raw event logs → decoded tables in Postgres (Neon), refreshed daily.

Used by: [maple-dashboard](https://github.com/paultimfv/maple-dashboard), [robinhood-earn](https://github.com/paultimfv/robinhood-earn), [maple-model](https://github.com/paultimfv/maple-model)

## Data

| Data | Source |
|---|---|
| Maple pool events: deposits, withdrawals, loans, interest (239 contracts, `config/contracts.csv`) | Ethereum logs (Infura), Robinhood Chain logs (public RPC) |
| Pool state: `totalAssets`, `totalSupply`, exchange rate | `eth_call` (Alchemy) |
| Borrower per loan | `loan.borrower()` via `eth_call` |
| Robinhood Earn vault and Morpho market flows | Robinhood Chain logs |
| Stablecoin supply on Robinhood Chain | `totalSupply()` per canonical token, daily |
| ETH in the canonical L1 bridge | Ethereum RPC, bridge contract balance |
| Sequencer batch cost | SequencerInbox logs + receipts on Ethereum |
| Chain activity, holder counts | Blockscout |
| Global stablecoin supply, chain TVL/fees | DeFiLlama |
| SYRUP price, market cap | CoinGecko |
| Offchain: OTC revenue, custodied collateral, buybacks | Maple API, maple.finance/transparency, `config/*.csv` |
| History before the pipeline | Dune exports, `config/dune_exports/` (static) |

## Steps

`pipeline/run_all.py`, in order. Each step is incremental and idempotent.

```
fetch_logs        raw event logs -> raw_logs
fetch_blocks      block timestamps (Robinhood: anchors + interpolation)
decode            raw_logs -> transfers, loans, morpho flows, claims
load_offchain     config CSVs
load_dune_exports config/dune_exports -> schema dune
fetch_borrowers   loan -> borrower
fetch_maple_api   Maple GraphQL -> maple_pool_state
fetch_maple_site  transparency page -> reported revenue, AUM, buybacks
decode_earn       Earn vault logs (chunked)
prune             drop decoded raw rows (Neon 512 MB limit)
fetch_state       pool state via eth_call
fetch_llama       DeFiLlama
fetch_syrup       CoinGecko + buybacks
fetch_blockscout  chain activity, holders
fetch_bridge      L1 bridge ETH
fetch_stables     Robinhood Chain stablecoin supply
fetch_l1_cost     sequencer batch cost
```

## Run

```
pip install -r requirements.txt
cp .env.example .env
psql $DATABASE_URL -f schema.sql
python pipeline/run_all.py
```

Env: `DATABASE_URL`, `INFURA_URL`, `RPC_URL` (Alchemy), `RH_RPC_URL`, `BLOCKSCOUT_KEY`.
Daily at 06:15 UTC via `.github/workflows/daily.yml`.

## RPC notes

- Alchemy free tier caps `eth_getLogs` at 10 blocks; used for `eth_call` only.
- Infura free tier returns rate-limit errors inside HTTP 200 batch responses; every item is checked for `result`.
- Robinhood Chain public RPC handles 2M-block `getLogs` ranges.
- Neon drops idle connections during long fetches: fresh connection per insert, `COPY` for bulk writes.
