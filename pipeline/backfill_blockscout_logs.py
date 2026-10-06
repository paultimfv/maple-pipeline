"""
One-off backfill of an Ethereum event key through Blockscout's logs API (eth.blockscout.com, no key), for when
Infura's 10k-block getLogs cap makes a multi-year sweep too slow. Same raw logs, written to raw_logs in the same
format; then the key's checkpoint is advanced so the daily RPC job carries on from there.

usage: python pipeline/backfill_blockscout_logs.py eth.Maple.Fees
"""
import os, sys, time, requests
from common import db, tracked_events, w3

API = "https://api.blockscout.com/1/api"          # Blockscout PRO, Ethereum; BLOCKSCOUT_KEY from .env
KEY = os.environ.get("BLOCKSCOUT_KEY", "")

def logs_for(address, topic0, frm, to):
    out, start, seen = [], frm, set()
    while True:
        res = None
        for i in range(8):
            try:
                r = requests.get(API, params={"module": "logs", "action": "getLogs", "fromBlock": start, "toBlock": to,
                                              "address": address, "topic0": topic0, "apikey": KEY}, timeout=60)
                j = r.json()
                if r.status_code == 200 and (j.get("result") is not None or j.get("message") == "No records found"):
                    res = j.get("result") or []; break
            except Exception:
                pass
            time.sleep(min(2 ** i, 30))
        if res is None:
            raise RuntimeError(f"Blockscout failed for {address} {topic0[:10]} from {start}")
        new = [l for l in res if (l["transactionHash"], l["logIndex"]) not in seen]
        seen.update((l["transactionHash"], l["logIndex"]) for l in res)
        out += new
        if len(res) < 1000 or not new: return out
        start = int(res[-1]["blockNumber"], 16)          # page: resume from the last block

def main(key):
    ev = next(e for e in tracked_events() if e["key"] == key)
    head = w3("ethereum").eth.block_number - 50
    topics = ev["topic0"] if isinstance(ev["topic0"], list) else [ev["topic0"]]
    topics = [t if t.startswith("0x") else "0x" + t for t in topics]
    pairs = ev.get("blockscout_pairs") or [(a, t0) for a in ev["addresses"] for t0 in topics]
    total = 0
    with db() as conn:
        for a, t0 in pairs:
            t0 = t0 if t0.startswith("0x") else "0x" + t0
            rows, blocks = [], set()
            for l in logs_for(a, t0, ev["from_block"], head):
                blocks.add((int(l["blockNumber"], 16), int(l["timeStamp"], 16)))
                tp = [t for t in l["topics"] if t]
                rows.append(("ethereum", l["address"].lower(), tp[0], tp, l["data"], int(l["blockNumber"], 16),
                             l["transactionHash"], int(l["logIndex"], 16)))
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO raw_logs VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", rows)
                # Blockscout returns each log's block timestamp: no separate block lookups needed
                cur.executemany("INSERT INTO blocks VALUES ('ethereum', %s, to_timestamp(%s)) ON CONFLICT DO NOTHING", list(blocks))
            conn.commit(); total += len(rows)
            print(f"{a} {t0[:10]} +{len(rows)}  total {total}", flush=True)
        rows = []
        conn.execute("INSERT INTO checkpoint VALUES (%s,%s) ON CONFLICT (event_key) DO UPDATE SET last_block=EXCLUDED.last_block", (key, head))
        conn.commit()
    print(f"{key}: {total} logs via Blockscout, checkpoint -> {head:,}")

if __name__ == "__main__":
    main(sys.argv[1])
