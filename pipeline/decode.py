"""
Decode raw_logs -> rh_transfers, morpho_flows, morpho_markets, claimed_funds, loan_events.
Idempotent (ON CONFLICT DO NOTHING). Rows without a block timestamp yet are skipped and picked up next run.
"""
import csv, math
from eth_abi import decode as abi_decode
from web3 import Web3
from common import (db, ROOT, load_contracts, RH_TOKENS, RH_USDG, RH_EARN_VAULT_V2, RH_MORPHO_BLUE, RH_COLLATERAL_SYMBOLS, RH_EARN_VAULT, ZERO, WETH_OTLM, FEE_MANAGER)

T = lambda s: "0x" + Web3.keccak(text=s).hex()
TOPIC = {
    "transfer":  T("Transfer(address,address,uint256)"),
    "supply":    T("Supply(bytes32,address,address,uint256,uint256)"),
    "withdraw":  T("Withdraw(bytes32,address,address,address,uint256,uint256)"),
    "create":    T("CreateMarket(bytes32,(address,address,address,address,uint256))"),
    "e_dep":     T("Deposit(address,address,uint256,uint256)"),
    "e_wd":      T("Withdraw(address,address,address,uint256,uint256)"),
    "borrow":    T("Borrow(bytes32,address,address,address,uint256,uint256)"),
    "repay":     T("Repay(bytes32,address,address,uint256,uint256)"),
    "sc":        T("SupplyCollateral(bytes32,address,address,uint256)"),
    "wc":        T("WithdrawCollateral(bytes32,address,address,address,uint256)"),
    "claimed":   T("ClaimedFundsDistributed(address,uint256,uint256,uint256,uint256,uint256,uint256)"),
    "pout":      T("PrincipalOutUpdated(uint128)"),
    "init":      T("Initialized(address,address,address,uint256,uint32[3],uint64[4])"),
    "ft_mgmt":   T("ManagementFeesPaid(address,uint256,uint256)"),
    "ft_service": T("ServiceFeesPaid(address,uint256,uint256,uint256,uint256)"),
    "ft_orig":   T("OriginationFeesPaid(address,uint256,uint256)"),
    "strategy":  T("StrategyFeesCollected(uint256)"),
    "deployed":  T("InstanceDeployed(uint256,address,bytes)"),
    "p_dep":     T("Deposit(address,address,uint256,uint256)"),
    "r_dep":     T("DepositData(address,uint256,bytes32)"),
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

        # Earn vault: handled by decode_earn_chunked.py (memory-decode, delete raw, insert) — Neon 512MB cap
        # Earn vault (ERC-4626): Deposit(sender idx, owner idx, assets, shares) / Withdraw(sender idx, receiver idx, owner idx, assets, shares)
        out = []
        for a, topics, data, bn, tx, li, bt in [] and rows(conn, "robinhood", TOPIC["e_dep"], RH_EARN_VAULT_V2):
            assets, shares = data_words(data, 2)
            out.append((bt, bn, tx, li, "deposit", addr(topics[2]), assets / 1e6, shares / 1e18))
        for a, topics, data, bn, tx, li, bt in [] and rows(conn, "robinhood", TOPIC["e_wd"], RH_EARN_VAULT_V2):
            assets, shares = data_words(data, 2)
            out.append((bt, bn, tx, li, "withdraw", addr(topics[3]), assets / 1e6, shares / 1e18))
        cur.executemany("INSERT INTO earn_flows VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", out)
        print("earn_flows", len(out))

        # Morpho credit side. Borrow(id idx, caller, onBehalf idx, receiver idx, assets, shares); Repay(id idx, caller, onBehalf idx, assets, shares)
        # SupplyCollateral(id idx, caller, onBehalf idx, assets); WithdrawCollateral(id idx, caller, onBehalf idx, receiver idx, assets)
        dec = {r[0]: (r[1] or 18) for r in conn.execute("SELECT m.market_id, t.decimals FROM morpho_markets m LEFT JOIN rh_tokens t ON t.address = m.collateral_token")}
        out = []
        for a, topics, data, bn, tx, li, bt in rows(conn, "robinhood", TOPIC["borrow"], RH_MORPHO_BLUE):
            caller, assets, shares = abi_decode(["address", "uint256", "uint256"], bytes.fromhex(data[2:]))
            out.append((bt, bn, tx, li, "borrow", topics[1], addr(topics[2]), assets / 1e6))
        for a, topics, data, bn, tx, li, bt in rows(conn, "robinhood", TOPIC["repay"], RH_MORPHO_BLUE):   # topics: id, caller, onBehalf; data: assets, shares
            assets, shares = data_words(data, 2)
            out.append((bt, bn, tx, li, "repay", topics[1], addr(topics[3]), assets / 1e6))
        for a, topics, data, bn, tx, li, bt in rows(conn, "robinhood", TOPIC["sc"], RH_MORPHO_BLUE):      # topics: id, caller, onBehalf; data: assets
            (assets,) = data_words(data, 1)
            out.append((bt, bn, tx, li, "supply_collateral", topics[1], addr(topics[3]), assets / 10 ** dec.get(topics[1], 18)))
        for a, topics, data, bn, tx, li, bt in rows(conn, "robinhood", TOPIC["wc"], RH_MORPHO_BLUE):
            caller, assets = abi_decode(["address", "uint256"], bytes.fromhex(data[2:]))
            out.append((bt, bn, tx, li, "withdraw_collateral", topics[1], addr(topics[2]), assets / 10 ** dec.get(topics[1], 18)))
        cur.executemany("INSERT INTO morpho_credit VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", out)
        print("morpho_credit", len(out))

        # Robinhood stock tokens: mints/burns
        stocks = {r[0] for r in conn.execute("SELECT address FROM rh_tokens WHERE name LIKE '%• Robinhood Token'")}
        out = []
        for a, topics, data, bn, tx, li, bt in rows(conn, "robinhood", TOPIC["transfer"]):
            if a not in stocks: continue
            f, t = addr(topics[1]), addr(topics[2])
            if f == ZERO:   out.append((a, bt, bn, tx, li, "mint", data_words(data, 1)[0] / 1e18))
            elif t == ZERO: out.append((a, bt, bn, tx, li, "burn", data_words(data, 1)[0] / 1e18))
        cur.executemany("INSERT INTO stock_token_flows VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", out)
        print("stock_token_flows", len(out))

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

        # ethereum: every other Maple fee (fixed-term mgmt/service/origination, strategy fees)
        reg = load_contracts()
        loan_dec = {r["address"].lower(): int(r["decimals"] or 6) for r in csv.DictReader(open(ROOT / "config" / "fixed_term_loans.csv"))}
        loan_dec.update({r[0]: r[1] for r in conn.execute("SELECT loan, decimals FROM loan_assets")})   # eth_call fundsAsset(), wins over the CSV
        dec_of = lambda a: 10 ** int(reg.get(a, {}).get("decimals") or 6)
        out = []
        for a, topics, data, bn, tx, li, bt in rows(conn, "ethereum", TOPIC["ft_mgmt"]):
            dm, pm = data_words(data, 2); d = dec_of(a)
            out.append((bt, bn, tx, li, "ft_mgmt", a, addr(topics[1]), int(math.log10(d)), pm / d, dm / d))
        for a, topics, data, bn, tx, li, bt in rows(conn, "ethereum", TOPIC["ft_service"], FEE_MANAGER):
            loan, d1, d2, p1, p2 = abi_decode(["address", "uint256", "uint256", "uint256", "uint256"], bytes.fromhex(data[2:]))
            d = 10 ** loan_dec.get(loan.lower(), 6)
            out.append((bt, bn, tx, li, "ft_service", a, loan.lower(), int(math.log10(d)), (p1 + p2) / d, (d1 + d2) / d))
        for a, topics, data, bn, tx, li, bt in rows(conn, "ethereum", TOPIC["ft_orig"], FEE_MANAGER):
            loan, do, po = abi_decode(["address", "uint256", "uint256"], bytes.fromhex(data[2:]))
            d = 10 ** loan_dec.get(loan.lower(), 6)
            out.append((bt, bn, tx, li, "ft_origination", a, loan.lower(), int(math.log10(d)), po / d, do / d))
        for a, topics, data, bn, tx, li, bt in rows(conn, "ethereum", TOPIC["strategy"]):
            (fees,) = data_words(data, 1); d = dec_of(a)
            out.append((bt, bn, tx, li, "strategy", a, None, int(math.log10(d)), fees / d, 0))
        cur.executemany("""INSERT INTO protocol_fees VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (tx_hash, log_index) DO UPDATE
            SET decimals=EXCLUDED.decimals, platform_fee=EXCLUDED.platform_fee, delegate_fee=EXCLUDED.delegate_fee""", out)
        print("protocol_fees", len(out))

        # lenders: deposits into every USD pool (owner = the account that receives pool shares)
        usd_pools = {a for a, r in reg.items() if r["contract_type"] == "MaplePool" and int(r["decimals"] or 6) == 6}
        out = []
        for a, topics, data, bn, tx, li, bt in rows(conn, "ethereum", TOPIC["p_dep"]):
            if a not in usd_pools: continue
            assets, shares = data_words(data, 2)
            out.append((bt, bn, tx, li, a, addr(topics[1]), addr(topics[2]), assets / 1e6))
        cur.executemany("INSERT INTO pool_deposits VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", out)
        print("pool_deposits", len(out))
        out = []
        for a, topics, data, bn, tx, li, bt in rows(conn, "ethereum", TOPIC["r_dep"]):
            amount, _ = abi_decode(["uint256", "bytes32"], bytes.fromhex(data[2:]))
            out.append((bt, bn, tx, li, a, addr(topics[1]), amount / 1e6))
        cur.executemany("INSERT INTO router_deposits VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", out)
        print("router_deposits", len(out))

        # factory deployments: audit trail for contracts that appear after the registry was built
        out = []
        for a, topics, data, bn, tx, li, bt in rows(conn, "ethereum", TOPIC["deployed"]):
            out.append((a, addr(topics[2]), int(topics[1], 16), bt, bn, tx, addr(topics[2]) in reg))
        cur.executemany("INSERT INTO factory_instances VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", out)
        print("factory_instances", len(out))
        conn.commit()

if __name__ == "__main__":
    run()
