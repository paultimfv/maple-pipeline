"""Borrower behind every Maple loan contract we have seen pay (open-term + fixed-term): loan.borrower() via eth_call -> loan_borrowers."""
from web3 import Web3
from common import db, ETH_CALL_RPC

ABI = [{"name": n, "type": "function", "inputs": [], "outputs": [{"type": "address"}], "stateMutability": "view"} for n in ("borrower", "fundsAsset")]
DEC = [{"name": "decimals", "type": "function", "inputs": [], "outputs": [{"type": "uint8"}], "stateMutability": "view"}]
w3 = Web3(Web3.HTTPProvider(ETH_CALL_RPC, request_kwargs={"timeout": 60}))

def main():
    with db() as conn:
        loans = [r[0] for r in conn.execute("""
            SELECT loan FROM claimed_funds UNION SELECT loan FROM protocol_fees WHERE loan IS NOT NULL
            UNION SELECT loan FROM loan_events WHERE loan IS NOT NULL
            EXCEPT SELECT loan FROM loan_borrowers""")]
        out = []
        for loan in loans:
            try:
                b = w3.eth.contract(address=Web3.to_checksum_address(loan), abi=ABI).functions.borrower().call()
                out.append((loan, b.lower()))
            except Exception:
                pass   # not a loan contract (or self-destructed)
        conn.cursor().executemany("INSERT INTO loan_borrowers VALUES (%s,%s) ON CONFLICT DO NOTHING", out)
        # funds asset per loan (fixes decimals for fee events on WETH loans)
        assets, dec_cache = [], {}
        for (loan,) in conn.execute("SELECT DISTINCT loan FROM protocol_fees WHERE loan IS NOT NULL EXCEPT SELECT loan FROM loan_assets").fetchall():
            try:
                fa = w3.eth.contract(address=Web3.to_checksum_address(loan), abi=ABI).functions.fundsAsset().call()
                if fa not in dec_cache:
                    dec_cache[fa] = w3.eth.contract(address=fa, abi=DEC).functions.decimals().call()
                assets.append((loan, fa.lower(), dec_cache[fa]))
            except Exception:
                pass
        conn.cursor().executemany("INSERT INTO loan_assets VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", assets)
        conn.commit()
        print("loan_borrowers +", len(out), "of", len(loans), "| total", conn.execute("SELECT count(*), count(DISTINCT borrower) FROM loan_borrowers").fetchone())

if __name__ == "__main__":
    main()
