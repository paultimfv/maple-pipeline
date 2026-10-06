"""
One-off backfill of an Ethereum event key through Blockscout's logs API (eth.blockscout.com, no key), for when
Infura's 10k-block getLogs cap makes a multi-year sweep too slow. Same raw logs, written to raw_logs in the same
format; then the key's checkpoint is advanced so the daily RPC job carries on from there.

usage: python pipeline/backfill_blockscout_logs.py eth.Maple.Fees
"""
import sys, time, requests
from common import db, tracked_events, w3

API = "https://eth.blockscout.com/api"

def logs_for(address, topic0, frm, to):
    out, start = [], frm
    while True:
        for i in range(6):
            r = requests.get(API, params={"module": "logs", "action": "getLogs", "fromBlock": start, "toBlock": to,
                                          "address": address, "topic0": topic0}, timeout=90)
            if r.status_code == 200: break
            time.sleep(2 ** i)
        res = r.json().get("result") or []
        out += res
        if len(res) < 1000: return out
        start = int(res[-1]["blockNumber"], 16)          # page: resume from the last block (dupes dropped on insert)

def main(key):
    ev = next(e for e in tracked_events() if e["key"] == key)
    head = w3("ethereum").eth.block_number - 50
    topics = ev["topic0"] if isinstance(ev["topic0"], list) else [ev["topic0"]]
    topics = [t if t.startswith("0x") else "0x" + t for t in topics]
    rows = []
    for a in ev["addresses"]:
        for t0 in topics:
            for l in logs_for(a, t0, ev["from_block"], head):
                tp = [t for t in l["topics"] if t]
                rows.append(("ethereum", l["address"].lower(), tp[0], tp, l["data"], int(l["blockNumber"], 16),
                             l["transactionHash"], int(l["logIndex"], 16)))
        print(f"{a}  total {len(rows)}", end="\r")
    with db() as conn:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO raw_logs VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", rows)
        conn.execute("INSERT INTO checkpoint VALUES (%s,%s) ON CONFLICT (event_key) DO UPDATE SET last_block=EXCLUDED.last_block", (key, head))
        conn.commit()
    print(f"\n{key}: {len(rows)} logs via Blockscout, checkpoint -> {head:,}")

if __name__ == "__main__":
    main(sys.argv[1])
