"""Shared config for the maple pipeline (Postgres + two chains)."""
import csv, json, os
from pathlib import Path
from dotenv import load_dotenv
import psycopg
from web3 import Web3

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")   # optional; CI passes env vars directly

DATABASE_URL = os.environ["DATABASE_URL"]

# Ethereum: Infura for eth_getLogs (no range cap on free tier), Alchemy for eth_call.
RPC = {
    "ethereum":  os.environ.get("INFURA_URL") or os.environ["RPC_URL"],
    "robinhood": os.environ["RH_RPC_URL"],
}
ETH_CALL_RPC = os.environ.get("RPC_URL") or RPC["ethereum"]
# Alchemy key works across networks: derive a Robinhood endpoint for batched block lookups
import re as _re
_m = _re.match(r"https://[a-z0-9-]+\.g\.alchemy\.com/v2/(.+)", os.environ.get("RPC_URL", ""))
BATCH_RPC = {
    "ethereum":  os.environ.get("INFURA_URL") or os.environ.get("RPC_URL"),   # Infura: higher limits for block lookups
    "robinhood": f"https://robinhood-mainnet.g.alchemy.com/v2/{_m.group(1)}" if _m else RPC["robinhood"],
}

_w3 = {}
def w3(chain):
    if chain not in _w3:
        _w3[chain] = Web3(Web3.HTTPProvider(RPC[chain], request_kwargs={"timeout": 60}))
    return _w3[chain]

def db():
    return psycopg.connect(DATABASE_URL)

def load_abis():
    return json.load(open(ROOT / "config" / "abis.json"))

def load_contracts():
    rows = list(csv.DictReader(open(ROOT / "config" / "contracts.csv")))
    return {r["address"].lower(): r for r in rows}

# --- addresses -----------------------------------------------------------
SYRUPUSDG_POOL   = "0x87b65c4aaffa76881f9e96f3e7ed945ddfc3cd7a"
SYRUPUSDG_OTLM   = "0x7be9a1fa4cd69f7a077692d4afa52bd09531920a"
WETH_OTLM        = "0xe3aac29001c769fafcef0df072ca396e310ed13b"   # 18 dec, excluded from $ sums

RH_TOKENS = {  # robinhood chain
    "syrupUSDG": "0x40858070814a57fdf33a613ae84fe0a8b4a874f7",
    "syrupUSDC": "0xc6a4854eeb493224d5f9485e12dd3a81f22eee14",
}
RH_MORPHO_BLUE   = "0x9d53d5e3bd5e8d4cbfa6db1ca238aea02e651010"
RH_EARN_VAULT    = "0x44abc1d6ccff2696d98890b92e2157af242179c2"   # Morpho V2 adapter (allocates into Blue markets)
RH_EARN_VAULT_V2 = "0xbeeff033f34c046626b8d0a041844c5d1a5409dd"   # Steakhouse USDG (steakUSDG) — user-facing ERC-4626 vault
RH_USDG          = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
RH_MARKET_SYRUPUSDG = "0x919a9b6b94dae7c86620eaf7a08e597aae8a4c3a9e9c7671771fbaf62b6b61c7"

RH_COLLATERAL_SYMBOLS = {
    "0x40858070814a57fdf33a613ae84fe0a8b4a874f7": "syrupUSDG",
    "0xde770c84fe66e063336b31737cfe9790f18c4087": "spUSDG",
    "0x5d3a1ff2b6bab83b63cd9ad0787074081a52ef34": "USDe",
}

ZERO = "0x0000000000000000000000000000000000000000"

SYRUP_TOKEN      = "0x643c4e15d7d62ad0abec4a9bd4b001aa3ef52d66"
MAPLE_TREASURY   = "0xa9466eabd096449d650d5aeb0dd3da6f52fd0b19"   # globals.mapleTreasury()
DAO_MULTISIG     = "0xd6d4bcde6c816f17889f1dd3000af0261b03a196"
FEE_MANAGER      = "0xfeaca6a5703e6f9de0ebe0975c93ae34c00523f2"
# SYRUP held by Maple-controlled wallets = not circulating (circulating = totalSupply - these)
SYRUP_NONCIRC = {
    "daoMultisig": DAO_MULTISIG,
}   # MapleLoanFeeManager (fixed-term service/origination fees)
FACTORIES = {
    "openTermLoanManager":  "0x90b14505221a24039a2d11ad5862339db97cc160",
    "fixedTermLoanManager": "0x1551717ae4fdcb65ed028f7fb7aba39908f6a7a6",
    "poolManager":          "0xe463cd473ecc1d1a4ecf20b62624d84dd20a8339",
    "skyStrategy":          "0x27327e08de810c687687f95bfce92088089b56db",
    "aaveStrategy":         "0x01ab799f77f9a9f4dd0d2b6e7c83dcf3f48d5650",
    "basicStrategy":        "0x876d54dbf61473ca169b89b95344a14e81f37afe",
}

def by_type(*types):
    return [a for a, r in load_contracts().items() if r["contract_type"] in types]

def otlm_addresses():
    """All OpenTermLoanManager proxies from the registry (13 on mainnet)."""
    return by_type("OpenTermLoanManager")

def pools():
    """MaplePool proxies -> (name, pool_group, decimals)."""
    return {a: (r["official_name"] or r["pool_group"], r["pool_group"], int(r["decimals"] or 6))
            for a, r in load_contracts().items() if r["contract_type"] == "MaplePool"}

# --- tracked events (dashboard scope) -----------------------------------
def tracked_events():
    k = Web3.keccak
    t = lambda s: k(text=s).hex()
    otlms = otlm_addresses()
    return [
        # robinhood
        {"key": "rh.Transfer.syrup", "chain": "robinhood", "topic0": t("Transfer(address,address,uint256)"),
         "addresses": list(RH_TOKENS.values()), "from_block": 1},
        # USDG: mints and burns only (all transfers = millions of rows)
        {"key": "rh.Transfer.usdg.mint", "chain": "robinhood", "topic0": t("Transfer(address,address,uint256)"),
         "addresses": [RH_USDG], "extra_topics": ["0x" + "0"*64], "from_block": 1},
        {"key": "rh.Transfer.usdg.burn", "chain": "robinhood", "topic0": t("Transfer(address,address,uint256)"),
         "addresses": [RH_USDG], "extra_topics": [None, "0x" + "0"*64], "from_block": 1},
        {"key": "rh.Earn.Deposit", "chain": "robinhood", "topic0": t("Deposit(address,address,uint256,uint256)"),
         "addresses": [RH_EARN_VAULT_V2], "from_block": 1},
        {"key": "rh.Earn.Withdraw", "chain": "robinhood", "topic0": t("Withdraw(address,address,address,uint256,uint256)"),
         "addresses": [RH_EARN_VAULT_V2], "from_block": 1},
        {"key": "rh.Morpho.Supply", "chain": "robinhood", "topic0": t("Supply(bytes32,address,address,uint256,uint256)"),
         "addresses": [RH_MORPHO_BLUE], "from_block": 1},
        {"key": "rh.Morpho.Withdraw", "chain": "robinhood", "topic0": t("Withdraw(bytes32,address,address,address,uint256,uint256)"),
         "addresses": [RH_MORPHO_BLUE], "from_block": 1},
        {"key": "rh.Morpho.CreateMarket", "chain": "robinhood", "topic0": t("CreateMarket(bytes32,(address,address,address,address,uint256))"),
         "addresses": [RH_MORPHO_BLUE], "from_block": 1},
        # Morpho credit side (all markets)
        {"key": "rh.Morpho.Borrow", "chain": "robinhood", "topic0": t("Borrow(bytes32,address,address,address,uint256,uint256)"),
         "addresses": [RH_MORPHO_BLUE], "from_block": 1},
        {"key": "rh.Morpho.Repay", "chain": "robinhood", "topic0": t("Repay(bytes32,address,address,uint256,uint256)"),
         "addresses": [RH_MORPHO_BLUE], "from_block": 1},
        {"key": "rh.Morpho.SupplyCollateral", "chain": "robinhood", "topic0": t("SupplyCollateral(bytes32,address,address,uint256)"),
         "addresses": [RH_MORPHO_BLUE], "from_block": 1},
        {"key": "rh.Morpho.WithdrawCollateral", "chain": "robinhood", "topic0": t("WithdrawCollateral(bytes32,address,address,address,uint256)"),
         "addresses": [RH_MORPHO_BLUE], "from_block": 1},
        # ethereum
        {"key": "eth.OTLM.ClaimedFundsDistributed", "chain": "ethereum",
         "topic0": t("ClaimedFundsDistributed(address,uint256,uint256,uint256,uint256,uint256,uint256)"),
         "addresses": otlms, "from_block": 17_000_000},
        # every other fee Maple earns onchain, in one sweep (topic0 is OR-ed):
        # fixed-term management fees, fixed-term service + origination fees, strategy fees,
        # and factory deployments (audit: any loan manager or strategy not in the registry)
        {"key": "eth.Maple.Fees", "chain": "ethereum",
         "topic0": [t("ManagementFeesPaid(address,uint256,uint256)"),
                    t("ServiceFeesPaid(address,uint256,uint256,uint256,uint256)"),
                    t("OriginationFeesPaid(address,uint256,uint256)"),
                    t("StrategyFeesCollected(uint256)"),
                    t("InstanceDeployed(uint256,address,bytes)")],
         "addresses": by_type("FixedTermLoanManager", "MapleSkyStrategy", "MapleAaveStrategy")
                      + [FEE_MANAGER] + list(FACTORIES.values()),
         # which emitter emits which event (lets a per-address backfill skip empty combinations)
         "blockscout_pairs": [(a, t("ManagementFeesPaid(address,uint256,uint256)")) for a in by_type("FixedTermLoanManager")]
                      + [(FEE_MANAGER, t("ServiceFeesPaid(address,uint256,uint256,uint256,uint256)")),
                         (FEE_MANAGER, t("OriginationFeesPaid(address,uint256,uint256)"))]
                      + [(a, t("StrategyFeesCollected(uint256)")) for a in by_type("MapleSkyStrategy", "MapleAaveStrategy")]
                      + [(a, t("InstanceDeployed(uint256,address,bytes)")) for a in FACTORIES.values()],
         "from_block": 16_000_000},
        # lenders: ERC-4626 Deposit(sender idx, owner idx, assets, shares) on every USD pool
        {"key": "eth.Pool.Deposit", "chain": "ethereum", "topic0": t("Deposit(address,address,uint256,uint256)"),
         "addresses": [a for a, (_, _, dec) in pools().items() if dec == 6],
         "blockscout_pairs": [(a, t("Deposit(address,address,uint256,uint256)")) for a, (_, _, dec) in pools().items() if dec == 6],
         "from_block": 16_000_000},
        # lenders behind the SyrupRouters (pool Deposit shows the router as owner): DepositData(owner idx, amount, depositData)
        {"key": "eth.Router.DepositData", "chain": "ethereum", "topic0": t("DepositData(address,uint256,bytes32)"),
         "addresses": by_type("SyrupRouter"),
         "blockscout_pairs": [(a, t("DepositData(address,uint256,bytes32)")) for a in by_type("SyrupRouter")],
         "from_block": 19_000_000},
        {"key": "eth.OTLM.PrincipalOutUpdated", "chain": "ethereum", "topic0": t("PrincipalOutUpdated(uint128)"),
         "addresses": [SYRUPUSDG_OTLM], "from_block": 22_500_000},
        # loan Initialized has no fixed emitter (each loan is its own contract) -> filter by indexed lender_ = OTLM
        {"key": "eth.OTL.Initialized", "chain": "ethereum",
         "topic0": t("Initialized(address,address,address,uint256,uint32[3],uint64[4])"),
         "addresses": None, "extra_topics": [None, "0x" + "0"*24 + SYRUPUSDG_OTLM[2:]], "from_block": 22_500_000},
    ]

def stock_tokens():
    with db() as c:
        return [r[0] for r in c.execute("SELECT address FROM rh_tokens WHERE name LIKE '%• Robinhood Token'")]
