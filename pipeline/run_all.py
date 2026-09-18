"""Daily job: logs -> block times -> decode -> prune -> state -> llama. Every step is incremental/idempotent."""
import datetime as dt, traceback
import fetch_logs, fetch_blocks, decode, fetch_state, fetch_llama
from common import db, RH_MORPHO_BLUE

def prune(conn):
    """Morpho raw rows are large and already decoded; keep only CreateMarket (Neon free tier = 512 MB)."""
    n = conn.execute("DELETE FROM raw_logs WHERE chain='robinhood' AND address=%s AND topic0 <> %s",
                     (RH_MORPHO_BLUE, "0xac4b2400f169220b0c0afdde7a0b32e775ba727ea1cb30b35f935cdaab8683ac")).rowcount
    conn.commit(); print(f"pruned {n} decoded morpho raw rows")

if __name__ == "__main__":
    print(f"=== run_all {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC")
    steps = [
        ("logs",   lambda: [fetch_logs.fetch(ev, conn) for conn in [db()] for ev in fetch_logs.tracked_events()]),
        ("blocks", fetch_blocks.main),
        ("decode", decode.run),
        ("prune",  lambda: prune(db())),
        ("state",  fetch_state.main),
        ("llama",  fetch_llama.main),
    ]
    for name, fn in steps:
        try: fn(); print(f"--- {name} ok")
        except Exception: print(f"--- {name} FAILED"); traceback.print_exc()
