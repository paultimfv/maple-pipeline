-- Maple Finance Loan Book
-- old query id 8254314
WITH latest AS (
  SELECT pool_id, MAX(date) AS d
  FROM dune."maple-finance".maple_pools_historical
  GROUP BY pool_id
),
snapshot AS (
  SELECT p.*
  FROM dune."maple-finance".maple_pools_historical p
  JOIN latest l
    ON p.pool_id = l.pool_id
   AND p.date    = l.d
  WHERE p.tvl > 1000
)
SELECT
  SUM(loan_value_usd)                          AS total_loans_outstanding_usd,
  SUM(tvl)                                     AS total_tvl_usd,
  SUM(loan_value_usd) / NULLIF(SUM(tvl), 0)    AS total_utilization,
  MAX(date)                                    AS as_of
FROM snapshot