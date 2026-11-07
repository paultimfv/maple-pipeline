"""
Loans outstanding per pool via eth_call -> loan_state. Resumable.
For every open-term and fixed-term loan manager in the registry, principalOut() at the same blocks pool_state
already snapshotted for its pool (month-ends since 2023, daily for live pools), so loans line up with deposits.
6-decimal pools only (USD); WETH pools are excluded, as everywhere else.
"""
from web3 import Web3
from common import db, load_contracts
from fetch_state import w3

ABI = [{"name": "principalOut", "type": "function", "inputs": [], "outputs": [{"type": "uint128"}], "stateMutability": "view"}]

def managers():
    return [(a, r["contract_type"], r["pool_group"]) for a, r in load_contracts().items()
            if r["contract_type"] in ("OpenTermLoanManager", "FixedTermLoanManager")
            and r["pool_group"] != "(derived only)" and int(r["decimals"] or 6) == 6]

def load_registry(conn):
    """config/contracts.csv -> contracts table, so SQL views can map a fee's contract to its pool (syrupUSD vs other pools)."""
    conn.execute("""CREATE TABLE IF NOT EXISTS contracts (address text PRIMARY KEY, contract_type text, official_name text,
                    pool_group text, decimals int)""")
    rows = [(a.lower(), r["contract_type"], r["official_name"], r["pool_group"], int(r["decimals"] or 6)) for a, r in load_contracts().items()]
    conn.cursor().executemany("""INSERT INTO contracts VALUES (%s,%s,%s,%s,%s) ON CONFLICT (address) DO UPDATE SET
        contract_type=EXCLUDED.contract_type, official_name=EXCLUDED.official_name, pool_group=EXCLUDED.pool_group, decimals=EXCLUDED.decimals""", rows)
    conn.commit()

def main():
    with db() as conn:
        load_registry(conn)
        conn.execute("""CREATE TABLE IF NOT EXISTS loan_state (
            day date NOT NULL, pool text NOT NULL, manager text NOT NULL, kind text NOT NULL,
            block_number bigint NOT NULL, principal_out_usd numeric NOT NULL, PRIMARY KEY (day, manager))""")
        done = {(r[0], r[1]) for r in conn.execute("SELECT day, manager FROM loan_state")}
        latest = conn.execute("SELECT max(day) FROM pool_state").fetchone()[0]
        n = 0
        for addr, kind, group in managers():
            c = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI)
            for day, block in conn.execute("SELECT day, block_number FROM pool_state WHERE pool = %s ORDER BY day", (group,)).fetchall():
                if (day, addr) in done and day != latest: continue
                try: out = c.functions.principalOut().call(block_identifier=int(block)) / 1e6
                except Exception: continue          # manager not deployed yet at that block
                conn.execute("""INSERT INTO loan_state VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (day, manager) DO UPDATE
                                SET block_number=EXCLUDED.block_number, principal_out_usd=EXCLUDED.principal_out_usd""",
                             (day, group, addr, kind, block, out))
                n += 1
                if n % 200 == 0: conn.commit()
        conn.commit()
        print(f"loan_state: {n} snapshots written;",
              conn.execute("SELECT day, round(sum(principal_out_usd)) FROM loan_state WHERE day = (SELECT max(day) FROM loan_state) GROUP BY 1").fetchone())

if __name__ == "__main__":
    main()
