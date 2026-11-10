-- maple-pipeline: Neon Postgres schema (Robinhood dashboard scope)

CREATE TABLE IF NOT EXISTS raw_logs (
  chain        text    NOT NULL,
  address      text    NOT NULL,
  topic0       text    NOT NULL,
  topics       text[]  NOT NULL,
  data         text    NOT NULL,
  block_number bigint  NOT NULL,
  tx_hash      text    NOT NULL,
  log_index    integer NOT NULL,
  PRIMARY KEY (chain, tx_hash, log_index)
);
CREATE INDEX IF NOT EXISTS raw_logs_topic ON raw_logs (chain, topic0, address);

CREATE TABLE IF NOT EXISTS checkpoint (
  event_key  text PRIMARY KEY,
  last_block bigint NOT NULL
);

CREATE TABLE IF NOT EXISTS blocks (
  chain        text   NOT NULL,
  block_number bigint NOT NULL,
  block_time   timestamptz NOT NULL,
  PRIMARY KEY (chain, block_number)
);

-- decoded ------------------------------------------------------------

-- Robinhood Chain syrup token mints/burns (CCIP pool)
CREATE TABLE IF NOT EXISTS rh_transfers (
  token        text NOT NULL,          -- 'syrupUSDG' | 'syrupUSDC'
  block_time   timestamptz NOT NULL,
  block_number bigint NOT NULL,
  tx_hash      text NOT NULL,
  log_index    integer NOT NULL,
  from_addr    text NOT NULL,
  to_addr      text NOT NULL,
  amount       numeric NOT NULL,       -- token units (6 dec applied)
  PRIMARY KEY (tx_hash, log_index)
);

-- Morpho Blue Supply/Withdraw on Robinhood (all suppliers; filter on_behalf = vault in SQL)
CREATE TABLE IF NOT EXISTS morpho_flows (
  block_time   timestamptz NOT NULL,
  block_number bigint NOT NULL,
  tx_hash      text NOT NULL,
  log_index    integer NOT NULL,
  kind         text NOT NULL,          -- 'supply' | 'withdraw'
  market_id    text NOT NULL,
  on_behalf    text NOT NULL,
  assets       numeric NOT NULL,       -- USDG units (6 dec applied)
  PRIMARY KEY (tx_hash, log_index)
);

CREATE TABLE IF NOT EXISTS morpho_markets (
  market_id        text PRIMARY KEY,
  created_at       timestamptz NOT NULL,
  loan_token       text NOT NULL,
  collateral_token text NOT NULL,
  collateral       text,               -- symbol, filled from a small lookup
  lltv             numeric NOT NULL
);

-- Ethereum: OpenTermLoanManager.ClaimedFundsDistributed (all OTLMs)
CREATE TABLE IF NOT EXISTS claimed_funds (
  block_time            timestamptz NOT NULL,
  block_number          bigint NOT NULL,
  tx_hash               text NOT NULL,
  log_index             integer NOT NULL,
  otlm                  text NOT NULL,
  loan                  text NOT NULL,
  principal             numeric NOT NULL,
  net_interest          numeric NOT NULL,
  delegate_mgmt_fee     numeric NOT NULL,
  delegate_service_fee  numeric NOT NULL,
  platform_mgmt_fee     numeric NOT NULL,
  platform_service_fee  numeric NOT NULL,
  PRIMARY KEY (tx_hash, log_index)
);

-- Ethereum: OpenTermLoan.Initialized + OTLM.PrincipalOutUpdated
CREATE TABLE IF NOT EXISTS loan_events (
  block_time     timestamptz NOT NULL,
  block_number   bigint NOT NULL,
  tx_hash        text NOT NULL,
  log_index      integer NOT NULL,
  kind           text NOT NULL,        -- 'initialized' | 'principal_out'
  otlm           text NOT NULL,        -- lender_ for initialized; emitter for principal_out
  loan           text,
  borrower       text,
  principal      numeric,              -- principalRequested_ (initialized)
  rate           numeric,              -- rates_[1] interestRate / 1e18 (initialized)
  principal_out  numeric,              -- principalOut_ (principal_out)
  PRIMARY KEY (tx_hash, log_index)
);

-- daily eth_call snapshots
CREATE TABLE IF NOT EXISTS pool_state (
  day           date NOT NULL,
  pool          text NOT NULL,         -- 'syrupUSDG'
  block_number  bigint NOT NULL,
  total_assets  numeric NOT NULL,
  total_supply  numeric NOT NULL,
  exch_rate     numeric NOT NULL,
  PRIMARY KEY (day, pool)
);

CREATE TABLE IF NOT EXISTS chain_tvl (
  day     date PRIMARY KEY,
  tvl_usd numeric NOT NULL
);

-- Robinhood Earn user-facing vault (Steakhouse USDG, ERC-4626) deposits/withdrawals
CREATE TABLE IF NOT EXISTS earn_flows (
  block_time   timestamptz NOT NULL,
  block_number bigint NOT NULL,
  tx_hash      text NOT NULL,
  log_index    integer NOT NULL,
  kind         text NOT NULL,          -- 'deposit' | 'withdraw'
  owner        text NOT NULL,          -- share owner (the user)
  assets       numeric NOT NULL,       -- USDG
  shares       numeric NOT NULL,
  PRIMARY KEY (tx_hash, log_index)
);

-- SYRUP token (CoinGecko daily) + buybacks (Maple transparency page, hand-maintained CSV)
CREATE TABLE IF NOT EXISTS syrup_price (
  day        date PRIMARY KEY,
  price_usd  numeric NOT NULL,
  mcap_usd   numeric,
  volume_usd numeric
);
CREATE TABLE IF NOT EXISTS syrup_buybacks (
  month        date PRIMARY KEY,
  amount_usd   numeric NOT NULL,
  syrup_bought numeric NOT NULL,
  avg_price    numeric
);

-- Robinhood Chain activity: sampled blocks (N per UTC day, evenly spaced) with receipts
CREATE TABLE IF NOT EXISTS rh_day_blocks (
  day          date PRIMARY KEY,
  first_block  bigint NOT NULL,
  last_block   bigint NOT NULL,
  n_blocks     bigint NOT NULL,
  sampled      integer NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS rh_block_samples (
  block_number bigint PRIMARY KEY,
  day          date NOT NULL,
  block_time   timestamptz NOT NULL,
  txs          integer NOT NULL,
  unique_from  integer NOT NULL,
  gas_used     bigint NOT NULL,
  base_fee     numeric NOT NULL,       -- wei
  fees_eth     numeric NOT NULL,       -- Σ gasUsed×effectiveGasPrice
  l1_gas       bigint NOT NULL         -- Σ gasUsedForL1 (L1 posting portion)
);
CREATE TABLE IF NOT EXISTS rh_block_to (
  block_number bigint NOT NULL,
  to_addr      text NOT NULL,
  txs          integer NOT NULL,
  gas_used     bigint NOT NULL,
  fees_eth     numeric NOT NULL,
  PRIMARY KEY (block_number, to_addr)
);
CREATE TABLE IF NOT EXISTS rh_labels (
  address text PRIMARY KEY,
  label   text NOT NULL,
  kind    text NOT NULL
);

-- Robinhood Chain L1 posting cost: every tx to the SequencerInbox on Ethereum (batch poster)
CREATE TABLE IF NOT EXISTS rh_l1_batches (
  tx_hash      text PRIMARY KEY,
  block_number bigint NOT NULL,
  block_time   timestamptz NOT NULL,
  gas_used     bigint NOT NULL,
  fee_eth      numeric NOT NULL,   -- gasUsed × effectiveGasPrice (+ blob fee)
  blob_fee_eth numeric NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS eth_price (day date PRIMARY KEY, price_usd numeric NOT NULL);

-- DeFiLlama: Robinhood Chain macro (source-labeled, not self-indexed)
CREATE TABLE IF NOT EXISTS llama_chain_daily (
  day              date PRIMARY KEY,
  tvl_usd          numeric,
  fees_usd         numeric,      -- all protocols on the chain (overview/fees)
  revenue_usd      numeric,      -- all protocols (dailyRevenue)
  dex_volume_usd   numeric,      -- overview/dexs
  sequencer_fees_usd numeric     -- 'Robinhood Chain' protocol = gas fees paid to the chain
);
CREATE TABLE IF NOT EXISTS llama_protocol_daily (
  day        date NOT NULL,
  protocol   text NOT NULL,
  category   text,
  metric     text NOT NULL,      -- 'fees' | 'revenue' | 'dex_volume'
  value_usd  numeric NOT NULL,
  PRIMARY KEY (day, protocol, metric)
);

-- Morpho Blue credit side (all markets): borrows/repays + collateral in/out. Joined to morpho_markets for collateral symbol.
CREATE TABLE IF NOT EXISTS morpho_credit (
  block_time   timestamptz NOT NULL,
  block_number bigint NOT NULL,
  tx_hash      text NOT NULL,
  log_index    integer NOT NULL,
  kind         text NOT NULL,     -- borrow | repay | supply_collateral | withdraw_collateral
  market_id    text NOT NULL,
  on_behalf    text NOT NULL,
  amount       numeric NOT NULL,  -- raw / 10^dec (USDG 6 for borrow/repay; collateral token decimals for collateral)
  PRIMARY KEY (tx_hash, log_index)
);
-- Robinhood stock tokens ("• Robinhood Token"): mints/burns -> supply
CREATE TABLE IF NOT EXISTS stock_token_flows (
  token        text NOT NULL,
  block_time   timestamptz NOT NULL,
  block_number bigint NOT NULL,
  tx_hash      text NOT NULL,
  log_index    integer NOT NULL,
  kind         text NOT NULL,     -- mint | burn
  amount       numeric NOT NULL,  -- shares (18 dec applied)
  PRIMARY KEY (tx_hash, log_index)
);

-- Blockscout raw chain activity (stats-service, no key)
CREATE TABLE IF NOT EXISTS bs_chain_daily (
  day date PRIMARY KEY, txns numeric, active_accounts numeric, new_accounts numeric, fees_eth numeric, avg_fee_eth numeric,
  new_contracts numeric, user_ops numeric, new_aa_wallets numeric, success_rate numeric);
-- token holder counts from Blockscout REST (daily snapshot)
CREATE TABLE IF NOT EXISTS bs_holders (day date, token text, address text, holders bigint, transfers bigint, PRIMARY KEY (day, token));
-- ETH locked in the canonical L1 bridge (Arbitrum Orbit), daily
CREATE TABLE IF NOT EXISTS bridge_tvl (day date PRIMARY KEY, block_number bigint, eth_bridged numeric);
-- stablecoin totalSupply on Robinhood Chain, daily (eth_call)
CREATE TABLE IF NOT EXISTS rh_stable_supply (day date, token text, kind text, block_number bigint, supply numeric, PRIMARY KEY (day, token));

-- ===================================================================
-- Maple protocol economics (thesis rebuild, Oct 2026)
-- ===================================================================

-- every onchain Maple fee that is NOT an open-term ClaimedFundsDistributed (those live in claimed_funds)
CREATE TABLE IF NOT EXISTS protocol_fees (
  block_time    timestamptz NOT NULL,
  block_number  bigint NOT NULL,
  tx_hash       text NOT NULL,
  log_index     integer NOT NULL,
  source        text NOT NULL,      -- ft_mgmt | ft_service | ft_origination | strategy
  contract      text NOT NULL,      -- emitter (FixedTermLoanManager / MapleLoanFeeManager / strategy)
  loan          text,
  decimals      integer NOT NULL,   -- 6 = USDC/USDT (USD), 18 = WETH (excluded from USD sums)
  platform_fee  numeric NOT NULL,   -- to MapleTreasury
  delegate_fee  numeric NOT NULL,   -- to the pool delegate
  PRIMARY KEY (tx_hash, log_index)
);

-- every contract Maple's factories have deployed; in_registry = false flags anything newer than the registry
CREATE TABLE IF NOT EXISTS factory_instances (
  factory      text NOT NULL,
  instance     text PRIMARY KEY,
  version      integer,
  block_time   timestamptz NOT NULL,
  block_number bigint NOT NULL,
  tx_hash      text NOT NULL,
  in_registry  boolean NOT NULL
);

-- OTC desk revenue: offchain, only ever published by Maple (Dune dataset maple-finance.dataset_dune_monthly_historical,
-- exported 2026-09). Loaded from config/otc_revenue_monthly.csv. Frozen: Maple stopped publishing it.
CREATE TABLE IF NOT EXISTS otc_revenue (
  month       date PRIMARY KEY,
  amount_usd  numeric NOT NULL
);

-- Maple revenue by month, every line traceable to a contract event or a sourced offchain file.
-- onchain = open-term fees (claimed_funds) + fixed-term fees + strategy fees, platform + delegate share
--           (Maple is the delegate on its own pools; in Sep 2026 it moved the delegate share into the platform fee).
-- WETH-denominated pools are excluded from USD sums (no ETH price before the trailing year; immaterial).
-- offchain = OTC desk (Maple-published, to May 2026); from Jul 2026 implied from onchain MIP-021 buybacks.
CREATE OR REPLACE VIEW monthly_revenue AS
WITH ot AS (
  SELECT date_trunc('month', block_time)::date AS month,
         sum(platform_mgmt_fee + platform_service_fee) AS platform,
         sum(delegate_mgmt_fee + delegate_service_fee) AS delegate,
         sum(platform_mgmt_fee + platform_service_fee + delegate_mgmt_fee + delegate_service_fee)
           FILTER (WHERE k.pool_group LIKE 'syrup%') AS syrup
  FROM claimed_funds f LEFT JOIN contracts k ON k.address = lower(f.otlm)
  WHERE otlm <> '0xe3aac29001c769fafcef0df072ca396e310ed13b'
  GROUP BY 1),
ft AS (
  SELECT date_trunc('month', block_time)::date AS month,
         sum(platform_fee + delegate_fee) FILTER (WHERE source <> 'strategy') AS fixed_term,
         sum(platform_fee) FILTER (WHERE source = 'strategy') AS strategy,
         sum(CASE WHEN source = 'strategy' THEN platform_fee ELSE platform_fee + delegate_fee END)
           FILTER (WHERE k.pool_group LIKE 'syrup%') AS syrup
  FROM protocol_fees f LEFT JOIN contracts k ON k.address = lower(f.contract)
  WHERE f.decimals = 6
  GROUP BY 1),
months AS (SELECT month FROM ot UNION SELECT month FROM ft UNION SELECT month FROM otc_revenue UNION SELECT month FROM maple_reported_revenue),
base AS (
  SELECT m.month,
         coalesce(ot.platform, 0)   AS open_term_platform,
         coalesce(ot.delegate, 0)   AS open_term_delegate,
         coalesce(ft.fixed_term, 0) AS fixed_term,
         coalesce(ft.strategy, 0)   AS strategy,
         coalesce(ot.platform, 0) + coalesce(ot.delegate, 0) + coalesce(ft.fixed_term, 0) + coalesce(ft.strategy, 0) AS onchain_revenue,
         coalesce(ot.syrup, 0) + coalesce(ft.syrup, 0) AS syrup_revenue,
         o.amount_usd AS otc_published,
         b.amount_usd AS buyback_usd,
         r.revenue_usd AS reported
  FROM months m LEFT JOIN ot USING (month) LEFT JOIN ft USING (month)
  LEFT JOIN otc_revenue o USING (month) LEFT JOIN syrup_buybacks b USING (month)
  LEFT JOIN maple_reported_revenue r USING (month)),
rep AS (   -- Maple-reported revenue: transparency page; fallback = MIP-021 buyback / tier (from Jul 2026)
  SELECT month, coalesce(reported,
           CASE WHEN month < '2026-07-01' OR buyback_usd IS NULL THEN NULL
                WHEN buyback_usd / 0.10 < 1500000 THEN buyback_usd / 0.10
                WHEN buyback_usd / 0.20 <= 2000000 THEN buyback_usd / 0.20
                ELSE buyback_usd / 0.30 END) AS maple_reported_revenue
  FROM base)
-- Total revenue = Maple-reported (it is what Maple publishes and what MIP-021 buybacks are set on).
-- Revenue split: syrupUSD (syrupUSDC/USDT/USDG loan managers + strategies) + other pools (every other onchain pool) + offchain.
-- Offchain = Maple-reported - onchain fees. When onchain fees exceed Maple's number (Sep-Oct 2026) offchain can't be
-- separated: it is NULL ("not separable"), never 0. Before Maple published totals, offchain = its published OTC revenue.
SELECT b.month, b.open_term_platform, b.open_term_delegate, b.fixed_term, b.strategy, b.onchain_revenue,
       b.otc_published, b.buyback_usd, r.maple_reported_revenue,
       CASE WHEN r.maple_reported_revenue IS NOT NULL THEN greatest(r.maple_reported_revenue - b.onchain_revenue, 0) END AS offchain_implied,
       CASE WHEN r.maple_reported_revenue IS NULL THEN coalesce(b.otc_published, 0)
            WHEN r.maple_reported_revenue >= b.onchain_revenue THEN r.maple_reported_revenue - b.onchain_revenue END AS offchain_revenue,
       coalesce(r.maple_reported_revenue, b.onchain_revenue + coalesce(b.otc_published, 0)) AS total_revenue,
       (b.otc_published IS NULL AND r.maple_reported_revenue IS NULL AND b.month >= '2026-06-01') AS offchain_unknown,
       b.syrup_revenue,
       b.onchain_revenue - b.syrup_revenue AS pool_revenue,
       (r.maple_reported_revenue IS NULL OR r.maple_reported_revenue >= b.onchain_revenue) AS offchain_separable
FROM base b JOIN rep r USING (month)
ORDER BY month;

-- SYRUP totalSupply and the amount held by Maple-controlled wallets (common.SYRUP_NONCIRC)
CREATE TABLE IF NOT EXISTS syrup_supply (
  day           date PRIMARY KEY,
  block_number  bigint NOT NULL,
  total_supply  numeric NOT NULL,
  maple_held    numeric NOT NULL     -- circulating = total_supply - maple_held
);

-- Maple AUM at each month-end, USD pools only (WETH pools are denominated in ETH; excluded)
CREATE OR REPLACE VIEW aum_monthly AS
SELECT day AS month_end, pool, total_assets AS aum_usd
FROM pool_state
WHERE (day + 1) = date_trunc('month', day + 1)::date
  AND pool NOT IN ('High Yield Corporate Loan WETH', 'Maven11 WETH')
  AND total_assets > 1000;

-- one row per month: revenue, trailing-12m revenue, AUM, market cap, P/S, buyback tier
CREATE OR REPLACE VIEW monthly_model AS
WITH a AS (SELECT date_trunc('month', month_end)::date AS month, sum(aum_usd) AS aum_usd FROM aum_monthly GROUP BY 1),
     p AS (SELECT DISTINCT ON (date_trunc('month', day)) date_trunc('month', day)::date AS month, price_usd, mcap_usd
           FROM syrup_price ORDER BY date_trunc('month', day), day DESC),
     r AS (SELECT month, onchain_revenue, offchain_revenue, total_revenue, buyback_usd, maple_reported_revenue, offchain_unknown,
                  sum(total_revenue) OVER (ORDER BY month ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS ttm_revenue,
                  count(*) OVER (ORDER BY month ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS ttm_months
           FROM monthly_revenue)
SELECT r.month, r.onchain_revenue, r.offchain_revenue, r.total_revenue, r.offchain_unknown,
       CASE WHEN ttm_months = 12 THEN r.ttm_revenue END AS ttm_revenue,
       a.aum_usd, r.total_revenue * 12 / NULLIF(a.aum_usd, 0) AS revenue_yield_on_aum,
       p.price_usd, p.mcap_usd,
       CASE WHEN ttm_months = 12 THEN p.mcap_usd / NULLIF(r.ttm_revenue, 0) END AS ps_ttm,
       r.buyback_usd, r.maple_reported_revenue,
       CASE WHEN r.month < '2025-01-01' THEN 0 WHEN r.month < '2025-07-01' THEN 0.20 WHEN r.month < '2026-07-01' THEN 0.25
            WHEN r.total_revenue > 2000000 THEN 0.30 WHEN r.total_revenue >= 1500000 THEN 0.20 ELSE 0.10 END AS mip021_tier
FROM r LEFT JOIN a USING (month) LEFT JOIN p USING (month)
ORDER BY r.month;

-- the model's history columns: one row per calendar year
CREATE OR REPLACE VIEW annual_model_inputs AS
SELECT extract(year FROM month)::int AS year,
       count(*) AS months,
       sum(onchain_revenue) AS onchain_revenue, sum(offchain_revenue) AS offchain_revenue, sum(total_revenue) AS total_revenue,
       (array_agg(aum_usd ORDER BY month DESC) FILTER (WHERE aum_usd IS NOT NULL))[1] AS aum_year_end,
       (array_agg(mcap_usd ORDER BY month DESC) FILTER (WHERE mcap_usd IS NOT NULL))[1] AS mcap_year_end,
       (array_agg(price_usd ORDER BY month DESC) FILTER (WHERE price_usd IS NOT NULL))[1] AS price_year_end,
       sum(buyback_usd) AS buybacks
FROM monthly_model
GROUP BY 1 ORDER BY 1;

-- global USD stablecoin supply, all chains (DeFiLlama; macro context, cited)
CREATE TABLE IF NOT EXISTS stablecoin_supply (day date PRIMARY KEY, supply_usd numeric NOT NULL);

-- lenders: every deposit into a USD Maple pool (Dune 8714452 / 8714443 used tx.from; here owner = share recipient)
CREATE TABLE IF NOT EXISTS pool_deposits (
  block_time timestamptz NOT NULL, block_number bigint NOT NULL, tx_hash text NOT NULL, log_index integer NOT NULL,
  pool text NOT NULL, sender text NOT NULL, owner text NOT NULL, assets numeric NOT NULL,
  PRIMARY KEY (tx_hash, log_index));

-- borrowers: loan contract -> borrower (loan.borrower())
CREATE TABLE IF NOT EXISTS loan_borrowers (loan text PRIMARY KEY, borrower text NOT NULL);

CREATE OR REPLACE VIEW monthly_lenders AS
WITH d AS (SELECT date_trunc('month', block_time)::date AS month, owner, assets,
                  min(date_trunc('month', block_time)) OVER (PARTITION BY owner)::date AS cohort FROM pool_deposits)
SELECT month, count(DISTINCT owner) AS active_lenders,
       count(DISTINCT owner) FILTER (WHERE cohort = month) AS new_lenders,
       sum(count(DISTINCT owner) FILTER (WHERE cohort = month)) OVER (ORDER BY month) AS cumulative_lenders,
       count(*) AS deposits, sum(assets) AS deposited_usd
FROM d GROUP BY month ORDER BY month;

-- borrowers active = made at least one payment that month (open-term ClaimedFundsDistributed + fixed-term fees)
CREATE OR REPLACE VIEW monthly_borrowers AS
WITH p AS (SELECT date_trunc('month', block_time)::date AS month, loan, principal, net_interest + delegate_mgmt_fee + delegate_service_fee + platform_mgmt_fee + platform_service_fee AS interest
           FROM claimed_funds WHERE otlm <> '0xe3aac29001c769fafcef0df072ca396e310ed13b'
           UNION ALL SELECT date_trunc('month', block_time)::date, loan, 0, 0 FROM protocol_fees WHERE loan IS NOT NULL AND decimals = 6),
     b AS (SELECT p.*, lb.borrower, min(p.month) OVER (PARTITION BY lb.borrower) AS cohort FROM p JOIN loan_borrowers lb USING (loan))
SELECT month, count(DISTINCT borrower) AS active_borrowers,
       count(DISTINCT borrower) FILTER (WHERE cohort = month) AS new_borrowers,
       sum(count(DISTINCT borrower) FILTER (WHERE cohort = month)) OVER (ORDER BY month) AS cumulative_borrowers,
       count(DISTINCT loan) AS active_loans, sum(interest) AS interest_paid_usd, sum(principal) AS principal_repaid_usd
FROM b GROUP BY month ORDER BY month;

-- SyrupRouter DepositData: the actual depositor behind router deposits (pool Deposit shows the router as owner)
CREATE TABLE IF NOT EXISTS router_deposits (
  block_time timestamptz NOT NULL, block_number bigint NOT NULL, tx_hash text NOT NULL, log_index integer NOT NULL,
  router text NOT NULL, owner text NOT NULL, amount numeric NOT NULL, PRIMARY KEY (tx_hash, log_index));
CREATE TABLE IF NOT EXISTS loan_assets (loan text PRIMARY KEY, asset text NOT NULL, decimals integer NOT NULL);

-- lenders = router depositors + direct pool depositors (excluding deposits the router made on someone's behalf)
CREATE OR REPLACE VIEW monthly_lenders AS
WITH routers AS (SELECT DISTINCT router AS a FROM router_deposits),
     all_dep AS (SELECT block_time, owner, amount AS assets FROM router_deposits
                 UNION ALL SELECT block_time, owner, assets FROM pool_deposits WHERE owner NOT IN (SELECT a FROM routers)),
     d AS (SELECT date_trunc('month', block_time)::date AS month, owner, assets,
                  min(date_trunc('month', block_time)) OVER (PARTITION BY owner)::date AS cohort FROM all_dep)
SELECT month, count(DISTINCT owner) AS active_lenders,
       count(DISTINCT owner) FILTER (WHERE cohort = month) AS new_lenders,
       sum(count(DISTINCT owner) FILTER (WHERE cohort = month)) OVER (ORDER BY month) AS cumulative_lenders,
       count(*) AS deposits, sum(assets) AS deposited_usd
FROM d GROUP BY month ORDER BY month;

-- Maple-reported pool state (API), daily from 2026-10; earlier history from the Dune export of the same dataset
CREATE TABLE IF NOT EXISTS maple_pool_state (
  day date NOT NULL, pool text NOT NULL, pool_address text, tvl_usd numeric NOT NULL,
  collateral_usd numeric NOT NULL, principal_out_usd numeric NOT NULL, PRIMARY KEY (day, pool));

CREATE OR REPLACE VIEW aum_reported AS
SELECT date::date AS day, deposits_usd, collateral_usd, deposits_usd + collateral_usd AS aum_usd, 'dune export' AS source
FROM dune.pool_aum_vs_deposits_over_time_protocol_totals
WHERE date::date < coalesce((SELECT min(day) FROM maple_pool_state), '2999-01-01')
UNION ALL
SELECT day, sum(tvl_usd - collateral_usd), sum(collateral_usd), sum(tvl_usd), 'maple api' FROM maple_pool_state GROUP BY day;

-- ===== Maple-reported (maple.finance/transparency; see pipeline/fetch_maple_site.py) =====
CREATE TABLE IF NOT EXISTS maple_reported_revenue (month date PRIMARY KEY, revenue_usd numeric NOT NULL);
CREATE TABLE IF NOT EXISTS maple_reported_aum (
  day date NOT NULL, product text NOT NULL, aum_usd numeric NOT NULL, deposits_usd numeric NOT NULL, PRIMARY KEY (day, product));
CREATE TABLE IF NOT EXISTS ssf_daily (day date PRIMARY KEY, syrup_held numeric NOT NULL, liquid_assets_usd numeric NOT NULL);
CREATE TABLE IF NOT EXISTS maple_balance_sheet (
  day date PRIMARY KEY, syrup_amount numeric NOT NULL, syrup_usd numeric NOT NULL, liquid_assets_usd numeric NOT NULL);

-- AUM = deposits + collateral, daily since 2023 (Maple-reported; collateral is at custodians, not onchain)
CREATE OR REPLACE VIEW aum_reported AS
SELECT day, sum(deposits_usd) AS deposits_usd, sum(aum_usd - deposits_usd) AS collateral_usd, sum(aum_usd) AS aum_usd, 'maple site' AS source
FROM maple_reported_aum GROUP BY day;

-- Contract registry (config/contracts.csv, loaded by fetch_loans.load_registry) so views can map a fee to its pool
CREATE TABLE IF NOT EXISTS contracts (address text PRIMARY KEY, contract_type text, official_name text, pool_group text, decimals int);

-- Loans outstanding: principalOut() of every USD loan manager, at the blocks pool_state snapshots (fetch_loans.py)
CREATE TABLE IF NOT EXISTS loan_state (
  day date NOT NULL, pool text NOT NULL, manager text NOT NULL, kind text NOT NULL,
  block_number bigint NOT NULL, principal_out_usd numeric NOT NULL, PRIMARY KEY (day, manager));

-- One row per month with every line of the SYRUP model; the dashboard's /api/model export aggregates it to quarters/years.
-- Flows (revenue, buybacks) are monthly sums; stocks (deposits, loans, AUM, price, supply) are month-end values
-- (latest available day for the current month).
CREATE OR REPLACE VIEW model_ledger AS
WITH m AS (SELECT generate_series('2023-01-01'::date, date_trunc('month', now())::date, '1 month')::date AS month),
dep AS (   -- Maple-reported deposits and AUM per product, last day of each month
  SELECT DISTINCT ON (date_trunc('month', day), product) date_trunc('month', day)::date AS month, product, deposits_usd, aum_usd
  FROM maple_reported_aum ORDER BY date_trunc('month', day), product, day DESC),
d AS (
  SELECT month,
         sum(deposits_usd) AS deposits_total, sum(aum_usd) AS aum_total,
         sum(deposits_usd) FILTER (WHERE product = 'syrupUSDC') AS deposits_syrupusdc,
         sum(deposits_usd) FILTER (WHERE product = 'syrupUSDT') AS deposits_syrupusdt,
         sum(deposits_usd) FILTER (WHERE product = 'syrupUSDG') AS deposits_syrupusdg,
         sum(deposits_usd) FILTER (WHERE product NOT IN ('syrupUSDC', 'syrupUSDT', 'syrupUSDG')) AS deposits_other
  FROM dep GROUP BY 1),
lday AS (SELECT DISTINCT ON (date_trunc('month', day)) date_trunc('month', day)::date AS month, day FROM loan_state ORDER BY date_trunc('month', day), day DESC),
l AS (
  SELECT lday.month,
         sum(s.principal_out_usd) AS loans_total,
         sum(s.principal_out_usd) FILTER (WHERE s.pool = 'syrupUSDC') AS loans_syrupusdc,
         sum(s.principal_out_usd) FILTER (WHERE s.pool = 'syrupUSDT') AS loans_syrupusdt,
         sum(s.principal_out_usd) FILTER (WHERE s.pool = 'syrupUSDG') AS loans_syrupusdg,
         sum(s.principal_out_usd) FILTER (WHERE s.pool NOT IN ('syrupUSDC', 'syrupUSDT', 'syrupUSDG')) AS loans_other
  FROM lday JOIN loan_state s ON s.day = lday.day GROUP BY 1),
pa AS (   -- onchain pool assets (USD pools) on the same day as the loan snapshot: the denominator for utilization
  SELECT lday.month, sum(ps.total_assets) AS pool_assets
  FROM lday CROSS JOIN (SELECT DISTINCT pool_group FROM contracts WHERE contract_type = 'MaplePool' AND decimals = 6) g
  JOIN LATERAL (SELECT total_assets FROM pool_state WHERE pool = g.pool_group AND day <= lday.day ORDER BY day DESC LIMIT 1) ps ON true
  GROUP BY 1),
sc AS (SELECT DISTINCT ON (date_trunc('month', day)) date_trunc('month', day)::date AS month, supply_usd FROM stablecoin_supply ORDER BY date_trunc('month', day), day DESC),
px AS (SELECT DISTINCT ON (date_trunc('month', day)) date_trunc('month', day)::date AS month, price_usd, mcap_usd FROM syrup_price ORDER BY date_trunc('month', day), day DESC),
gi AS (   -- borrower interest on open-term loans (ClaimedFundsDistributed): to lenders + Maple fees. Fixed-term interest isn't in the events we index.
  SELECT date_trunc('month', block_time)::date AS month,
         sum(net_interest + delegate_mgmt_fee + delegate_service_fee + platform_mgmt_fee + platform_service_fee) AS gross_interest,
         sum(net_interest) AS interest_to_lenders,
         sum(delegate_mgmt_fee + delegate_service_fee + platform_mgmt_fee + platform_service_fee) AS interest_fees
  FROM claimed_funds WHERE otlm <> '0xe3aac29001c769fafcef0df072ca396e310ed13b' GROUP BY 1),
ts AS (SELECT DISTINCT ON (date_trunc('month', day)) date_trunc('month', day)::date AS month, total_supply FROM syrup_supply ORDER BY date_trunc('month', day), day DESC)
SELECT m.month,
       (m.month = date_trunc('month', now())::date) AS partial_month,
       sc.supply_usd AS stablecoin_supply,
       d.deposits_total, d.deposits_syrupusdc, d.deposits_syrupusdt, d.deposits_syrupusdg, d.deposits_other,
       l.loans_total, l.loans_syrupusdc, l.loans_syrupusdt, l.loans_syrupusdg, l.loans_other,
       l.loans_total / NULLIF(pa.pool_assets, 0) AS utilization, pa.pool_assets,
       d.aum_total AS aum, d.aum_total - d.deposits_total AS collateral,
       r.syrup_revenue, r.pool_revenue, r.offchain_revenue, r.offchain_separable, r.onchain_revenue, r.total_revenue,
       r.maple_reported_revenue,
       mm.mip021_tier AS buyback_rate, r.total_revenue * mm.mip021_tier AS buybacks_implied, r.buyback_usd AS buybacks_actual,
       px.price_usd AS syrup_price, px.mcap_usd AS syrup_mcap, ts.total_supply AS syrup_total_supply, px.price_usd * ts.total_supply AS syrup_fdv,
       gi.gross_interest, gi.interest_to_lenders, gi.interest_fees / NULLIF(gi.gross_interest, 0) AS maple_share_of_interest,
       r.total_revenue * 12 / NULLIF(pa.pool_assets, 0) AS nim
FROM m
LEFT JOIN d USING (month) LEFT JOIN l USING (month) LEFT JOIN pa USING (month) LEFT JOIN sc USING (month) LEFT JOIN px USING (month) LEFT JOIN ts USING (month)
LEFT JOIN monthly_revenue r USING (month) LEFT JOIN gi USING (month) LEFT JOIN monthly_model mm USING (month)
ORDER BY m.month;

-- Maple's "Key financials" box on /transparency/financials, snapshotted daily (fetch_maple_site.kpis)
CREATE TABLE IF NOT EXISTS maple_kpis (day date PRIMARY KEY, gross_revenue_ttm numeric, protocol_revenue_ttm numeric, nim numeric, treasury_total numeric);

-- lenders leaving USD pools (ERC-4626 Withdraw), same scope as pool_deposits
CREATE TABLE IF NOT EXISTS pool_withdrawals (
  block_time timestamptz NOT NULL, block_number bigint NOT NULL, tx_hash text NOT NULL, log_index integer NOT NULL,
  pool text NOT NULL, owner text NOT NULL, assets numeric NOT NULL, PRIMARY KEY (tx_hash, log_index));
-- SYRUP staked in stSYRUP, daily (eth_call)
CREATE TABLE IF NOT EXISTS syrup_staked (day date PRIMARY KEY, staked numeric NOT NULL, total_supply numeric NOT NULL);
-- top holders of SYRUP / syrupUSDC / syrupUSDT, daily snapshot
CREATE TABLE IF NOT EXISTS token_holders (day date NOT NULL, token text NOT NULL, rank integer NOT NULL, address text NOT NULL,
  balance numeric NOT NULL, name text, kind text NOT NULL, PRIMARY KEY (day, token, rank));
-- Maple's open loans, from each loan contract (eth_call), daily snapshot
CREATE TABLE IF NOT EXISTS loan_book (day date NOT NULL, loan text NOT NULL, pool text NOT NULL, borrower text, asset text NOT NULL,
  principal numeric NOT NULL, rate numeric NOT NULL, date_funded date, PRIMARY KEY (day, loan));
