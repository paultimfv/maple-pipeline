"""
Decode raw_logs into typed tables named like Dune's decoded tables.
Idempotent: drops and rebuilds each decoded table from raw_logs.

usage: python pipeline/decode.py
"""
import duckdb
from eth_abi import decode as abi_decode
from web3 import Web3
from common import DB_PATH, load_abis, load_contracts, tracked_events

db = duckdb.connect(str(DB_PATH))
abis = load_abis()
contracts = load_contracts()

def event_abi(ct, name, sig):
    for it in abis["abis"][ct]:
        if it.get("type") == "event" and it["name"] == name:
            s = name + "(" + ",".join(i["type"] for i in it["inputs"]) + ")"
            if s == sig: return it
    raise KeyError(sig)

def sql_type(t):
    if t == "address": return "VARCHAR"
    if t.startswith("uint") or t.startswith("int"): return "HUGEINT"
    if t == "bool": return "BOOLEAN"
    return "VARCHAR"

def decode_one(ev):
    ab = event_abi(ev["contract_type"], ev["event"], ev["signature"])
    table = ev["dune_table"]
    idx = [i for i in ab["inputs"] if i.get("indexed")]
    dat = [i for i in ab["inputs"] if not i.get("indexed")]
    cols = ", ".join(f'"{i["name"]}" {sql_type(i["type"])}' for i in ab["inputs"])
    db.execute(f"DROP TABLE IF EXISTS {table}")
    db.execute(f"""CREATE TABLE {table} (
        contract_address VARCHAR, contract_type VARCHAR, pool_group VARCHAR, decimals INTEGER,
        evt_block_time TIMESTAMP, evt_block_number BIGINT, evt_tx_hash VARCHAR, evt_index INTEGER, {cols})""")
    rows = db.execute("""
        SELECT r.address, r.topics, r.data, r.block_number, b.block_time, r.tx_hash, r.log_index
        FROM raw_logs r LEFT JOIN blocks b USING (block_number) WHERE r.topic0 = ?""", [ev["topic0"]]).fetchall()
    out = []
    for addr, topics, data, bn, bt, txh, li in rows:
        vals = {}
        for i, t in zip(idx, topics[1:]):
            vals[i["name"]] = abi_decode([i["type"]], bytes.fromhex(t[2:] if t.startswith("0x") else t))[0]
        raw = bytes.fromhex(data[2:] if data.startswith("0x") else data) if data and data not in ("0x", "") else b""
        if dat:
            for i, v in zip(dat, abi_decode([i["type"] for i in dat], raw)): vals[i["name"]] = v
        c = contracts.get(addr, {})
        out.append((addr, c.get("contract_type", ev["contract_type"]), c.get("pool_group", ""), int(c.get("decimals", 6) or 6),
                    bt, bn, txh, li, *[str(vals[i["name"]]).lower() if i["type"] == "address" else vals[i["name"]] for i in ab["inputs"]]))
    if out:
        ph = ",".join("?" * (8 + len(ab["inputs"])))
        db.executemany(f"INSERT INTO {table} VALUES ({ph})", out)
    print(f"{table:55s} {len(out):>7,} rows")

if __name__ == "__main__":
    for ev in tracked_events():
        decode_one(ev)
