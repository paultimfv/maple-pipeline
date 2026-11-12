"""SYRUP and syrup pool token markets, read from Ethereum.

- syrup_staked: stSYRUP's SYRUP balance and SYRUP total supply, one row a day (eth_call).
- token_holders: the top holders of SYRUP, syrupUSDC and syrupUSDT today, with each address's public name tag
  and a type (staking, treasury, exchange, DEX, lending, bridge, contract, wallet). Holder lists come from the
  Ethereum Blockscout index of the chain (balances are the tokens' own balanceOf); no analytics provider.
"""
import datetime as dt, re, requests
from common import db, w3

SYRUP = "0x643c4e15d7d62ad0abec4a9bd4b001aa3ef52d66"
STSYRUP = "0xc7e8b36e0766d9b04c93de68a9d47dd11f260b45"
TOKENS = {  # token -> (address, decimals)
    "SYRUP": (SYRUP, 18),
    "syrupUSDC": ("0x80ac24aa929eaf5013f6436cda2a7ba190f5cc0b", 6),
    "syrupUSDT": ("0x356b8d89c1e1239cbbb9de4815c39a1474d5ba7d", 6),
}
MAPLE = {STSYRUP: "staking", "0xa9466eabd096449d650d5aeb0dd3da6f52fd0b19": "treasury"}
BS = "https://eth.blockscout.com/api/v2"

# name tag -> type; first match wins
KINDS = [
    (r"stsyrup|staked syrup|staking", "staking"),
    (r"maple|syrup strategic|treasury", "treasury"),
    (r"lockreleasetokenpool|ccip|bridge|layerzero|oft|wormhole|portal", "bridge"),
    (r"safeproxy|gnosis|multisig", "multisig"),
    (r"binance|coinbase|kraken|okx|bybit|gate|kucoin|mexc|bitget|bitvavo|htx|huobi|upbit|bithumb|crypto\.com|falcon|coinspot|bingx|wintermute|cumberland", "exchange"),
    (r"uniswap|curve|balancer|arrakis|poolmanager|aerodrome|velodrome|fluid|\bamm\b", "dex"),
    (r"morpho|spark|almproxy|aave|^a[a-z]{2,4}syrup|euler|pendle|kamino|vault|silo|compound", "lending"),
]
GENERIC = re.compile(r"proxy|^$", re.I)

def token_name(addr):
    """ERC-20 name() of a contract holder, for proxies Blockscout only knows by their proxy type (e.g. an Aave aToken)."""
    try:
        raw = w3("ethereum").eth.call({"to": w3("ethereum").to_checksum_address(addr), "data": "0x06fdde03"})
        n = int.from_bytes(raw[32:64], "big"); return raw[64:64 + n].decode("utf-8", "ignore") or None
    except Exception:
        return None

def call(to, sig, *args):
    sel = w3("ethereum").keccak(text=sig)[:4].hex().removeprefix("0x")
    data = "0x" + sel + "".join(a.lower().removeprefix("0x").rjust(64, "0") for a in args)
    return int(w3("ethereum").eth.call({"to": w3("ethereum").to_checksum_address(to), "data": data}).hex(), 16)

def kind_of(addr, name, is_contract):
    if addr in MAPLE: return MAPLE[addr]
    n = (name or "").lower()
    for pat, k in KINDS:
        if re.search(pat, n): return k
    return "contract" if is_contract else "wallet"

def main():
    conn = db(); day = dt.datetime.now(dt.timezone.utc).date()
    staked = call(SYRUP, "balanceOf(address)", STSYRUP) / 1e18
    supply = call(SYRUP, "totalSupply()") / 1e18
    conn.execute("""INSERT INTO syrup_staked VALUES (%s,%s,%s) ON CONFLICT (day) DO UPDATE
                    SET staked=EXCLUDED.staked, total_supply=EXCLUDED.total_supply""", (day, staked, supply))
    print(f"syrup_staked {day}: {staked/1e6:,.1f}M of {supply/1e6:,.1f}M")
    for token, (addr, dec) in TOKENS.items():
        r = requests.get(f"{BS}/tokens/{addr}/holders", timeout=60).json()
        if not isinstance(r, dict) or not r.get("items"):   # Blockscout sometimes answers with an error string
            print(f"token_holders {token}: skipped (bad response: {str(r)[:80]})"); continue
        rows = []
        for i, h in enumerate(r.get("items", [])[:50]):
            a = h["address"]; ha = a["hash"].lower()
            tags = (a.get("metadata") or {}).get("tags") or []
            name = (tags[0].get("name") if tags else None) or a.get("name")
            if a.get("is_contract") and GENERIC.search(name or "") and not re.search(r"safe", name or "", re.I):
                name = token_name(ha) or name
            rows.append((day, token, i + 1, ha, int(h["value"]) / 10 ** dec, name, kind_of(ha, name, a.get("is_contract"))))
        conn.execute("DELETE FROM token_holders WHERE day=%s AND token=%s", (day, token))
        conn.cursor().executemany("INSERT INTO token_holders VALUES (%s,%s,%s,%s,%s,%s,%s)", rows)
        print(f"token_holders {token}: {len(rows)}")
    conn.commit()

if __name__ == "__main__":
    main()
