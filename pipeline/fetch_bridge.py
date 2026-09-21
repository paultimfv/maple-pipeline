"""Canonical Arbitrum-Orbit bridge for Robinhood Chain: ETH held in the L1 Bridge contract, daily -> bridge_tvl.
Stablecoins (USDG, syrupUSDG) are minted natively on the chain, not bridged — the ERC-20 gateways hold ~nothing,
so bridged value = ETH only. Addresses from docs.robinhood.com/chain/protocol-contracts."""
import datetime as dt
from web3 import Web3
from common import db, ETH_CALL_RPC
from fetch_state import block_before

L1_BRIDGE = "0xDf8755334ce7A73cCF6b581C02eA649AE3E864b3"
START = dt.date(2026, 5, 11)   # first Robinhood Chain block in our DB

w3 = Web3(Web3.HTTPProvider(ETH_CALL_RPC, request_kwargs={"timeout": 60}))

def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    with db() as conn:
        done = {r[0] for r in conn.execute("SELECT day FROM bridge_tvl")}
        known = dict(conn.execute("SELECT day, block_number FROM pool_state WHERE pool='syrupUSDG'").fetchall())
        day = START
        while day <= today:
            if day not in done or day == today:
                if day == today: blk = w3.eth.block_number
                elif day in known: blk = known[day]
                else: blk = block_before(int(dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), dt.timezone.utc).timestamp()))
                eth = w3.eth.get_balance(Web3.to_checksum_address(L1_BRIDGE), block_identifier=blk) / 1e18
                conn.execute("""INSERT INTO bridge_tvl VALUES (%s,%s,%s) ON CONFLICT (day) DO UPDATE SET block_number=EXCLUDED.block_number, eth_bridged=EXCLUDED.eth_bridged""",
                             (day, blk, eth))
                conn.commit(); print(f"{day} blk {blk} {eth:,.0f} ETH", end="\r")
            day += dt.timedelta(days=1)
        print(); print(conn.execute("SELECT count(*), max(day), max(eth_bridged) FROM bridge_tvl").fetchone())

if __name__ == "__main__":
    main()
