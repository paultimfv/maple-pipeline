-- SYRUP live price (Ethereum)
-- token: 0x643C4E15d7d62Ad0aBeC4a9BD4b001aA3Ef52d66
WITH syrup_prices AS (
    SELECT timestamp, price
    FROM prices.minute
    WHERE blockchain = 'ethereum'
      AND contract_address = 0x643C4E15d7d62Ad0aBeC4a9BD4b001aA3Ef52d66
      AND timestamp >= now() - INTERVAL '2' day
),
snapshot AS (
    SELECT
        max_by(price, timestamp)                           AS price_usd,
        max(timestamp)                                     AS price_at,
        max_by(price, timestamp) FILTER (
            WHERE timestamp <= now() - INTERVAL '24' hour) AS price_usd_24h_ago
    FROM syrup_prices
)
SELECT
    'SYRUP'                                              AS symbol,
    price_usd,
    price_at,
    date_diff('minute', price_at, now())                 AS minutes_stale,
    price_usd_24h_ago,
    (price_usd / nullif(price_usd_24h_ago, 0) - 1) * 100 AS change_24h_pct
FROM snapshot
