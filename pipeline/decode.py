"""
Decode raw_logs -> rh_transfers, morpho_flows, morpho_markets, claimed_funds, loan_events.
Idempotent (ON CONFLICT DO NOTHING). Rows without a block timestamp yet are skipped and picked up next run.
"""
from eth_abi import decode as abi_decode
from web3 import Web3
from common import (db, RH_TOKENS, RH_USDG, RH_EARN_VAULT_V2, RH_MORPHO_BLUE, RH_COLLATERAL_SYMBOLS, RH_EARN_VAULT, ZERO, WETH_OTLM)

T = lambda s: "0x" + Web3.keccak(text=s).hex()
TOPIC = {
    "transfer":  T("Transfer(address,address,uint256)"),
    "supply":    T("Supply(bytes32,address,address,uint256,uint256)"),
    "withdraw":  T("Withdraw(bytes32,address,address,address,uint256,uint256)"),
    "create":    T("CreateMarket(bytes32,(address,address,address,address,uint256))"),
    "e_dep":     T("Deposit(address,address,uint256,uint256)"),
    "e_wd":      T("Withdraw(address,address,address,uint256,uint256)"),
    "claimed":   T("ClaimedFundsDistributed(address,uint256,uint256,uint256,uint256,uint256,uint256)"),
    "pout":      T("PrincipalOutUpdated(uint128)"),
    "init":      T("Initialized(address,address,address,uint256,uint32[3],uint64[4])"),
}
addr = lambda topic: "0x" + topic[-40:]
TOKEN_BY_ADDR = {v: k for k, v in RH_TOKENS.items()}
TOKEN_BY_ADDR[RH_USDG] = "USDG"

def rows(conn, chain, topic0, address=None):
    q = """SELECT r.address, r.topics, r.data, r.block_number, r.tx_hash, r.log_index, b.block_time
           FROM raw_logs r JOIN blocks b ON b.chain=r.chain AND b.block_number=r.block_number
           WHERE r.chain=%s AND r.topic0=%s""" + (" AND r.address=%s" if address else "")
    return conn.execute(q, (chain, topic0) + ((address,) if address else ())).fetchall()

def data_words(data, n):
    return abi_decode(["uint256"] * n, bytes.fromhex(data[2:]))

def run():
    with db() as conn:
        cur = conn.cursor()

        # syrup tokens on robinhood: mints/burns only
        out = []
        for a, topics, data, bn, tx, li, bt in rows(conn, "robinhood", TOPIC["transfer"]):
            if a not in TOKEN_BY_ADDR: continue
            f, t = addr(topics[1]), addr(topics[2])
            if f != ZERO and t != ZERO: continue
            out.append((TOKEN_BY_ADDR[a], bt, bn, tx, li, f, t, data_words(data, 1)[0] / 1e6))
        cur.executemany("INSERT INTO rh_transfers VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", out)
        print("rh_transfers", len(out))

        # morpho markets
        out = []
        for a, topics, data, bn, tx, li, bt in rows(conn, "robinhood", TOPIC["create"], RH_MORPHO_BLUE):
            loan, coll, oracle, irm, lltv = abi_decode(["address", "address", "address", "address", "uint256"], bytes.fromhex(data[2:]))
            out.append((topics[1], bt, loan.lower(), coll.lower(), RH_COLLATERAL_SYMBOLS.get(coll.lower()), lltv / 1e18))
        cur.executemany("INSERT INTO morpho_markets VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", out)
        print("morpho_markets", len(out))

        # morpho supply / withdraw — Earn vault only
        out = []
        for a, topics, data, bn, tx, li, bt in rows(conn, "robinhood", TOPIC["supply"], RH_MORPHO_BLUE):
            on_behalf = addr(topics[3])
            if on_behalf != RH_EARN_VAULT: continue
            assets, shares = data_words(data, 2)
            out.append((bt, bn, tx, li, "supply", topics[1], on_behalf, assets / 1e6))
        for a, topics, data, bn, tx, li, bt in rows(conn, "robinhood", TOPIC["withdraw"], RH_MORPHO_BLUE):
            on_behalf = addr(topics[2])
            if on_behalf != RH_EARN_VAULT: continue
            caller, assets, shares = abi_decode(["address", "uint256", "uint256"], bytes.fromhex(data[2:]))
            out.append((bt, bn, tx, li, "withdraw", topics[1], on_behalf, assets / 1e6))
        cur.executemany("INSERT INTO morpho_flows VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", out)
        print("morpho_flows", len(out))

        # Earn vault (ERC-4626): Deposit(sender idx, owner idx, assets, shares) / Withdraw(sender idx, receiver idx, owner idx, assets, shares)
        out = []
        for a, topics, data, bn, tx, li, bt in rows(conn, "robinhood", TOPIC["e_dep"], RH_EARN_VAULT_V2):
            assets, shares = data_words(data, 2)
            out.append((bt, bn, tx, li, "deposit", addr(topics[2]), assets / 1e6, shares / 1e18))
        for a, topics, data, bn, tx, li, bt in rows(conn, "robinhood", TOPIC["e_wd"], RH_EARN_VAULT_V2):
            assets, shares = data_words(data, 2)
            out.append((bt, bn, tx, li, "withdraw", addr(topics[3]), assets / 1e6, shares / 1e18))
        cur.executemany("INSERT INTO earn_flows VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", out)
        print("earn_flows", len(out))

        # ethereum: ClaimedFundsDistributed(address indexed loan_, uint256 x6)
        out = []
        for a, topics, data, bn, tx, li, bt in rows(conn, "ethereum", TOPIC["claimed"]):
            d = 1e18 if a == WETH_OTLM else 1e6
            p, ni, dm, ds, pm, ps = data_words(data, 6)
            out.append((bt, bn, tx, li, a, addr(topics[1]), p / d, ni / d, dm / d, ds / d, pm / d, ps / d))
        cur.executemany("INSERT INTO claimed_funds VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", out)
        print("claimed_funds", len(out))

        # ethereum: loan events
        out = []
        for a, topics, data, bn, tx, li, bt in rows(conn, "ethereum", TOPIC["pout"]):
            (po,) = abi_decode(["uint128"], bytes.fromhex(data[2:]))
            out.append((bt, bn, tx, li, "principal_out", a, None, None, None, None, po / 1e6))
        for a, topics, data, bn, tx, li, bt in rows(conn, "ethereum", TOPIC["init"]):
            principal, term, rates = abi_decode(["uint256", "uint32[3]", "uint64[4]"], bytes.fromhex(data[2:]))
            out.append((bt, bn, tx, li, "initialized", addr(topics[2]), a, addr(topics[1]), principal / 1e6, rates[1] / 1e18, None))
        cur.executemany("INSERT INTO loan_events VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", out)
        print("loan_events", len(out))
        conn.commit()

if __name__ == "__main__":
    run()
