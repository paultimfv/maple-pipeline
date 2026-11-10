"""Maple's open loan book, read from each open-term loan contract (eth_call): principal(), interestRate(), dateFunded().
Loans are every loan contract that has paid interest (claimed_funds) or been opened (loan_events); a loan is open
while principal() > 0. Rates are the contract's interestRate (1e6 = 100% a year). -> loan_book, one snapshot a day."""
import datetime as dt
from web3 import Web3
from common import db, ETH_CALL_RPC

w3 = Web3(Web3.HTTPProvider(ETH_CALL_RPC, request_kwargs={"timeout": 60}))
F = lambda name, out: {"name": name, "type": "function", "inputs": [], "outputs": [{"type": out}], "stateMutability": "view"}
ABI = [F("principal", "uint256"), F("interestRate", "uint256"), F("dateFunded", "uint256"), F("fundsAsset", "address"), F("lender", "address")]
SYMBOL = {"0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC", "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
          "0xe343167631d89b6ffc58b88d6b7fb0228795491d": "USDG", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH"}

def main():
    conn = db(); day = dt.datetime.now(dt.timezone.utc).date()
    loans = conn.execute("""SELECT DISTINCT c.loan, c.otlm FROM claimed_funds c
                            UNION SELECT loan, otlm FROM loan_events WHERE kind = 'initialized' AND loan IS NOT NULL""").fetchall()
    pool_of = dict(conn.execute("SELECT DISTINCT manager, pool FROM loan_state").fetchall())
    who = dict(conn.execute("SELECT loan, borrower FROM loan_borrowers").fetchall())
    dec = {r[0]: r[2] for r in conn.execute("SELECT loan, asset, decimals FROM loan_assets").fetchall()}
    rows = []
    for loan, otlm in loans:
        try:
            c = w3.eth.contract(address=Web3.to_checksum_address(loan), abi=ABI).functions
            p = c.principal().call()
            if p == 0: continue
            asset = c.fundsAsset().call().lower()
            d = dec.get(loan) or (18 if SYMBOL.get(asset) == "WETH" else 6)
            rows.append((day, loan, pool_of.get(otlm, "other"), who.get(loan), SYMBOL.get(asset, asset[:10]), p / 10 ** d,
                         c.interestRate().call() / 1e6, dt.datetime.fromtimestamp(c.dateFunded().call(), dt.timezone.utc).date()))
        except Exception:
            pass   # fixed-term loans and closed contracts don't expose these
    conn.execute("DELETE FROM loan_book WHERE day=%s", (day,))
    conn.cursor().executemany("INSERT INTO loan_book VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", rows)
    conn.commit()
    print(f"loan_book {day}: {len(rows)} open loans, ${sum(r[5] for r in rows if r[4] != 'WETH')/1e6:,.0f}M")

if __name__ == "__main__":
    main()
