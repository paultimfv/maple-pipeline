"""Daily job: logs -> block times -> decode -> prune -> state -> llama. Every step is incremental/idempotent."""
import datetime as dt, traceback
import fetch_logs, fetch_blocks, decode, fetch_state, fetch_llama, fetch_syrup, subprocess, sys, os
from common import db, RH_MORPHO_BLUE, RH_EARN_VAULT_V2

def prune(conn):
    """Morpho raw rows are large and already decoded; keep only CreateMarket (Neon free tier = 512 MB)."""
    n = conn.execute("DELETE FROM raw_logs WHERE chain='robinhood' AND address=%s AND topic0 <> %s",
                     (RH_MORPHO_BLUE, "0xac4b2400f169220b0c0afdde7a0b32e775ba727ea1cb30b35f935cdaab8683ac")).rowcount
    n += conn.execute("DELETE FROM raw_logs WHERE chain='robinhood' AND address=%s", (RH_EARN_VAULT_V2,)).rowcount
    n += conn.execute("DELETE FROM raw_logs r USING stock_token_flows s WHERE r.tx_hash=s.tx_hash AND r.log_index=s.log_index").rowcount
    conn.commit(); print(f"pruned {n} decoded morpho/earn raw rows")

if __name__ == "__main__":
    print(f"=== run_all {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC")
    steps = [
        ("logs",   lambda: [fetch_logs.fetch(ev, conn) for conn in [db()] for ev in fetch_logs.tracked_events()]),
        ("blocks", fetch_blocks.main),
        ("decode", decode.run),
        ("decode_earn", lambda: subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "decode_earn_chunked.py")], check=True)),
        ("prune",  lambda: prune(db())),
        ("state",  fetch_state.main),
        ("llama",  fetch_llama.main),
        ("syrup",  fetch_syrup.main),
    ]
    for name, fn in steps:
        try: fn(); print(f"--- {name} ok")
        except Exception: print(f"--- {name} FAILED"); traceback.print_exc()
