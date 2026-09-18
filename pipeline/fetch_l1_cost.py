"""
Robinhood Chain's L1 cost: batch-poster txs to the SequencerInbox on Ethereum.
Found via SequencerBatchDelivered logs (topic0) on the inbox; each log's tx receipt = fee paid. Resumable.
"""
import time, datetime as dt, requests
from web3 import Web3
from common import db, RPC, BATCH_RPC

INBOX = "0xBd0D173EEb87D57A09521c24388a12789F33ba96"
TOPIC = "0x" + Web3.keccak(text="SequencerBatchDelivered(uint256,bytes32,bytes32,bytes32,uint256,(uint64,uint64,uint64,uint64),uint8)").hex()
eth = Web3(Web3.HTTPProvider(RPC["ethereum"], request_kwargs={"timeout": 60}))
URL = BATCH_RPC["ethereum"]

def batch(calls):
    delay = 1
    for _ in range(8):
        r = requests.post(URL, json=calls, timeout=90)
        if r.status_code == 429: time.sleep(delay); delay = min(delay*2, 30); continue
        out = r.json()
        if any("result" not in x for x in out): time.sleep(delay); delay = min(delay*2, 30); continue
        return {x["id"]: x["result"] for x in out}
    raise RuntimeError("batch failed")

def main():
    with db() as conn:
        row = conn.execute("SELECT last_block FROM checkpoint WHERE event_key='eth.RH.SequencerBatch'").fetchone()
        frm = row[0] + 1 if row else 22_400_000   # ~Apr 2026
        head = eth.eth.block_number; chunk = 50_000
        while frm <= head:
            to = min(frm + chunk - 1, head)
            try: logs = eth.eth.get_logs({"address": INBOX, "topics": [TOPIC], "fromBlock": frm, "toBlock": to})
            except Exception: chunk = max(chunk // 2, 2000); continue
            hashes = sorted({"0x" + l["transactionHash"].hex() if not l["transactionHash"].hex().startswith("0x") else l["transactionHash"].hex() for l in logs})
            rows = []
            for i in range(0, len(hashes), 10):
                hs = hashes[i:i+10]
                res = batch([{"jsonrpc": "2.0", "id": h, "method": "eth_getTransactionReceipt", "params": [h]} for h in hs])
                bn = {int(r["blockNumber"], 16) for r in res.values()}
                bt = batch([{"jsonrpc": "2.0", "id": str(b), "method": "eth_getBlockByNumber", "params": [hex(b), False]} for b in bn])
                for h, r in res.items():
                    b = int(r["blockNumber"], 16)
                    gas = int(r["gasUsed"], 16); fee = gas * int(r["effectiveGasPrice"], 16) / 1e18
                    blob = int(r.get("blobGasUsed", "0x0"), 16) * int(r.get("blobGasPrice", "0x0"), 16) / 1e18
                    rows.append((h, b, dt.datetime.fromtimestamp(int(bt[str(b)]["timestamp"], 16), dt.timezone.utc), gas, fee + blob, blob))
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO rh_l1_batches VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", rows)
            conn.execute("INSERT INTO checkpoint VALUES ('eth.RH.SequencerBatch',%s) ON CONFLICT (event_key) DO UPDATE SET last_block=EXCLUDED.last_block", (to,))
            conn.commit(); print(f"  {to:,} +{len(rows)} batches", end="\r"); frm = to + 1
        print(); print(conn.execute("SELECT count(*), min(block_time)::date, max(block_time)::date, sum(fee_eth) FROM rh_l1_batches").fetchone())

if __name__ == "__main__":
    main()
