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
