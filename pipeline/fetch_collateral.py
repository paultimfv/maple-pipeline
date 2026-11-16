"""Margin calls, tracked from Maple's public GraphQL API (api.maple.finance/v2/graphql), every run (hourly).

Each active open-term loan carries its collateral (asset, amount, USD price) and three levels set in the loan terms,
as collateral ÷ principal: initial, margin call, liquidation. A loan is in margin call when collateral ÷ principal
falls below its margin call level. Maple's own call history needs a borrower login, so calls are found by comparing
each run with the last one:
- call: a loan's level drops below its margin call level
- cured: it is back above (more collateral, a repayment, or the price recovering); hours_to_cure = time since the call
- top_up: the collateral amount goes up (during a call or not); usd = added amount × today's price
- closed_in_call: a loan in call disappears from the active list (repaid or liquidated)
Collateral sits with custodians, so none of this is onchain (no PrincipalCalled / Impaired / Repossessed event has been
emitted by any Maple open-term loan). Hourly runs miss calls opened and cured inside the same hour.

Tables: loan_collateral (latest state per loan), loan_collateral_daily (one snapshot a day), margin_events.
"""
import datetime as dt, requests
from common import db

URL = "https://api.maple.finance/v2/graphql"
Q = """{ openTermLoans(first: 1000, where: {state: Active}) { id principalOwed fundingPool { name asset { decimals } }
  collateral { asset decimals assetAmount assetValueUsd initialLevel marginCallLevel liquidationLevel } } }"""

def loans():
    out = {}
    for l in requests.post(URL, json={"query": Q}, timeout=60).json()["data"]["openTermLoans"]:
        c, fp = l.get("collateral"), l.get("fundingPool")
        if not c or not fp or not c.get("assetAmount") or not c.get("marginCallLevel"): continue
        principal = int(l["principalOwed"]) / 10 ** fp["asset"]["decimals"]
        if principal <= 0: continue
        amount = int(c["assetAmount"]) / 10 ** c["decimals"]; price = int(c["assetValueUsd"] or 0) / 1e8
        out[l["id"].lower()] = dict(pool=fp["name"], asset=c["asset"], principal=principal, amount=amount, price=price,
            collateral=amount * price, level=amount * price / principal, initial=c["initialLevel"] / 1e6,
            call=c["marginCallLevel"] / 1e6, liq=c["liquidationLevel"] / 1e6)
    return out

def main():
    now = dt.datetime.now(dt.timezone.utc); day = now.date()
    cur = loans()
    with db() as conn:
        prev = {r[0]: dict(amount=float(r[1]), in_call=r[2], call_since=r[3], pool=r[4], asset=r[5], principal=float(r[6]), level=float(r[7]), call=float(r[8]))
                for r in conn.execute("SELECT loan, collateral_amount, in_call, call_since, pool, asset, principal_usd, level, call_level FROM loan_collateral")}
        ev = []
        for loan, x in cur.items():
            p = prev.get(loan); in_call = x["level"] < x["call"]; since = p["call_since"] if p and p["in_call"] else None
            if p:
                if in_call and not p["in_call"]:
                    since = now; ev.append((now, loan, x["pool"], x["asset"], "call", x["principal"], x["level"], x["call"], x["level"] < x["liq"], None, None))
                elif p["in_call"] and not in_call:
                    hrs = (now - p["call_since"]).total_seconds() / 3600 if p["call_since"] else None
                    ev.append((now, loan, x["pool"], x["asset"], "cured", x["principal"], x["level"], x["call"], False, None, hrs)); since = None
                if x["amount"] > p["amount"] * 1.0001:
                    ev.append((now, loan, x["pool"], x["asset"], "top_up", x["principal"], x["level"], x["call"], p["in_call"], (x["amount"] - p["amount"]) * x["price"], None))
            conn.execute("""INSERT INTO loan_collateral VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (loan) DO UPDATE SET
                pool=EXCLUDED.pool, asset=EXCLUDED.asset, principal_usd=EXCLUDED.principal_usd, collateral_amount=EXCLUDED.collateral_amount,
                collateral_usd=EXCLUDED.collateral_usd, level=EXCLUDED.level, initial_level=EXCLUDED.initial_level, call_level=EXCLUDED.call_level,
                liq_level=EXCLUDED.liq_level, in_call=EXCLUDED.in_call, call_since=EXCLUDED.call_since, updated_at=EXCLUDED.updated_at""",
                (loan, x["pool"], x["asset"], x["principal"], x["amount"], x["collateral"], x["level"], x["initial"], x["call"], x["liq"], in_call, since, now))
            conn.execute("""INSERT INTO loan_collateral_daily VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (day, loan) DO UPDATE SET
                principal_usd=EXCLUDED.principal_usd, collateral_usd=EXCLUDED.collateral_usd, level=EXCLUDED.level, call_level=EXCLUDED.call_level,
                liq_level=EXCLUDED.liq_level, in_call=EXCLUDED.in_call OR loan_collateral_daily.in_call""",
                (day, loan, x["pool"], x["asset"], x["principal"], x["collateral"], x["level"], x["call"], x["liq"], in_call))
        for loan, p in prev.items():
            if loan not in cur:
                if p["in_call"]: ev.append((now, loan, p["pool"], p["asset"], "closed_in_call", p["principal"], p["level"], p["call"], False, None, None))
                conn.execute("DELETE FROM loan_collateral WHERE loan=%s", (loan,))
        conn.cursor().executemany("INSERT INTO margin_events VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", ev)
        conn.commit()
        n_call = sum(1 for x in cur.values() if x["level"] < x["call"])
        print(f"loan_collateral: {len(cur)} loans, {n_call} in margin call, {len(ev)} new events")

if __name__ == "__main__":
    main()
