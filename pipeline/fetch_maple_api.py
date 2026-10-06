"""
Maple's public GraphQL API (api.maple.finance/v2/graphql) -> maple_pool_state, one snapshot per day.
Same source as Maple's Dune dataset maple-finance.maple_pools_historical (used by the Dune exports through 2026-09-10):
tvl includes borrower collateral held at custodians, which is not in any contract. deposits = tvl - collateral.
Onchain cross-check: deposits ~= pool totalAssets() in pool_state.
"""
import datetime as dt, requests
from common import db

URL = "https://api.maple.finance/v2/graphql"
Q = "{ poolV2S(first: 100) { id name tvl collateralValue principalOut } }"

def main():
    pools = requests.post(URL, json={"query": Q}, timeout=60).json()["data"]["poolV2S"]
    day = dt.datetime.now(dt.timezone.utc).date()
    rows = [(day, p["name"], p["id"].lower(), int(p["tvl"]) / 1e6, int(p["collateralValue"]) / 1e6, int(p["principalOut"]) / 1e6)
            for p in pools if "WETH" not in p["name"]]                       # USD pools only (6 decimals)
    with db() as conn:
        conn.cursor().executemany("""INSERT INTO maple_pool_state VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (day, pool) DO UPDATE
            SET tvl_usd=EXCLUDED.tvl_usd, collateral_usd=EXCLUDED.collateral_usd, principal_out_usd=EXCLUDED.principal_out_usd""", rows)
        conn.commit()
        print("maple_pool_state", conn.execute("SELECT day, round(sum(tvl_usd)/1e6), round(sum(collateral_usd)/1e6) FROM maple_pool_state WHERE day=%s GROUP BY 1", (day,)).fetchone())

if __name__ == "__main__":
    main()
