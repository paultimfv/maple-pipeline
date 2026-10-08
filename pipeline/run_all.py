"""Daily job: logs -> block times -> decode -> offchain -> prune -> state -> llama -> syrup -> blockscout -> bridge -> l1 cost. Every step is incremental/idempotent."""
import datetime as dt, traceback
import fetch_logs, fetch_blocks, decode, load_offchain, load_dune_exports, fetch_borrowers, fetch_maple_api, fetch_maple_site, fetch_state, fetch_llama, fetch_syrup, fetch_blockscout, fetch_bridge, fetch_l1_cost, fetch_stables, subprocess, sys, os
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
        ("logs",   lambda: [fetch_logs.fetch(ev, conn) for conn in [db()] for ev in fetch_logs.tracked_events()]),
        ("blocks", fetch_blocks.main),
        ("decode", decode.run),
        ("offchain", load_offchain.main),
        ("dune_exports", load_dune_exports.main),
        ("borrowers", fetch_borrowers.main),
        ("maple_api", fetch_maple_api.main),
        ("maple_site", fetch_maple_site.main),   # Maple-reported revenue, AUM history, SSF, buybacks (transparency page)     # Maple-reported TVL incl. custodied collateral (not onchain)     # loan -> borrower via eth_call  # static history from the author's Dune dashboards        # OTC revenue + pre-2025 SYRUP prices (sourced static files)
        ("decode_earn", lambda: subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "decode_earn_chunked.py")], check=True)),
        ("prune",  lambda: prune(db())),
        ("state",  fetch_state.main),
        ("llama",  fetch_llama.main),
        ("syrup",  fetch_syrup.main),
        ("blockscout", fetch_blockscout.main),   # raw chain activity + holder counts
        ("bridge", fetch_bridge.main),           # ETH in the canonical L1 bridge
        ("stables", fetch_stables.main),         # stablecoin totalSupply on RH Chain
        ("l1_cost", fetch_l1_cost.main),         # sequencer batch cost on Ethereum
    ]
    for name, fn in steps:
        try: fn(); print(f"--- {name} ok")
        except Exception: print(f"--- {name} FAILED"); traceback.print_exc()
