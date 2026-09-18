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
