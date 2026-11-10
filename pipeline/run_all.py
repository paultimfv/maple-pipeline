"""Daily job: quick API steps (Maple, llama, syrup, offchain) first, then logs -> block times -> decode -> prune -> state -> blockscout -> bridge -> stables -> l1 cost. Every step is incremental/idempotent."""
import datetime as dt, traceback
import fetch_loans, fetch_logs, fetch_blocks, decode, load_offchain, load_dune_exports, fetch_borrowers, fetch_maple_api, fetch_maple_site, fetch_state, fetch_llama, fetch_syrup, fetch_blockscout, fetch_bridge, fetch_l1_cost, fetch_stables, fetch_markets, fetch_loanbook, fetch_macro, subprocess, sys, os
from common import db, RH_MORPHO_BLUE, RH_EARN_VAULT_V2

def prune(conn):
    """Morpho raw rows are large and already decoded; keep only CreateMarket (Neon free tier = 512 MB).
    Also drop Robinhood block times no raw row still needs (decoded tables carry their own block_time)."""
    # only rows that already have a block time (= were decoded); on a day the blocks step fails, the rest wait for tomorrow
    timed = "AND EXISTS (SELECT 1 FROM blocks k WHERE k.chain=raw_logs.chain AND k.block_number=raw_logs.block_number)"
    n = conn.execute("DELETE FROM raw_logs WHERE chain='robinhood' AND address=%s AND topic0 <> %s " + timed,
                     (RH_MORPHO_BLUE, "0xac4b2400f169220b0c0afdde7a0b32e775ba727ea1cb30b35f935cdaab8683ac")).rowcount
    n += conn.execute("DELETE FROM raw_logs WHERE chain='robinhood' AND address=%s " + timed, (RH_EARN_VAULT_V2,)).rowcount
    b = conn.execute("DELETE FROM blocks k WHERE k.chain='robinhood' AND NOT EXISTS (SELECT 1 FROM raw_logs r WHERE r.chain=k.chain AND r.block_number=k.block_number)").rowcount
    conn.commit(); print(f"pruned {n} decoded morpho/earn raw rows, {b} robinhood block times")

if __name__ == "__main__":
    print(f"=== run_all {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC")
    steps = [
        # quick API steps first: they only touch their own tables, so a slow chain backfill can't starve them (runs time out at 60 min)
        ("maple_api", fetch_maple_api.main),     # Maple-reported TVL incl. custodied collateral (not onchain)
        ("maple_site", fetch_maple_site.main),   # Maple-reported revenue, AUM history, SSF, buybacks (transparency pages)
        ("llama",  fetch_llama.main),
        ("syrup",  fetch_syrup.main),
        ("markets", fetch_markets.main),     # stSYRUP balance + top holders of SYRUP / syrupUSDC / syrupUSDT
        ("macro", fetch_macro.main),         # growth drivers: yield-bearing stablecoins + stablecoin lending (Ethereum reads, DefiLlama)
        ("offchain", load_offchain.main),        # OTC revenue + pre-2025 SYRUP prices (sourced static files)
        ("dune_exports", load_dune_exports.main),
        # chain backfill
        ("logs",   lambda: [fetch_logs.fetch(ev, conn) for conn in [db()] for ev in fetch_logs.tracked_events()]),
        ("blocks", fetch_blocks.main),
        ("decode", decode.run),
        ("borrowers", fetch_borrowers.main),     # loan -> borrower via eth_call
        ("decode_earn", lambda: subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "decode_earn_chunked.py")], check=True)),
        ("prune",  lambda: prune(db())),
        ("state",  fetch_state.main),
        ("loans",  fetch_loans.main),           # principalOut per loan manager at pool_state's blocks (needs state)
        ("loanbook", fetch_loanbook.main),      # open loans: principal, rate, date funded, read from each loan contract
        ("blockscout", fetch_blockscout.main),   # raw chain activity + holder counts
        ("bridge", fetch_bridge.main),           # ETH in the canonical L1 bridge
        ("stables", fetch_stables.main),         # stablecoin totalSupply on RH Chain
        # sequencer batch cost on Ethereum: slow-moving and heavy on the free RPC, so only in runs at 00, 06, 12, 18 UTC
        ("l1_cost", fetch_l1_cost.main if dt.datetime.now(dt.timezone.utc).hour % 6 == 0 or os.environ.get("L1_COST") else lambda: print("l1_cost: daily step, skipped this hour")),
    ]
    for name, fn in steps:
        t0 = dt.datetime.now()
        try: fn(); print(f"--- {name} ok ({(dt.datetime.now() - t0).seconds}s)")
        except Exception: print(f"--- {name} FAILED"); traceback.print_exc()
