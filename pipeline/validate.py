"""
Tie the decoded tables out against the Dune CSV exports.
Prints ours vs Dune side by side; no asserts — eyeball the deltas.

usage: python pipeline/validate.py
"""
import duckdb
from common import DB_PATH, CSV_DIR

db = duckdb.connect(str(DB_PATH), read_only=True)
def csv(name): return f"read_csv_auto('{CSV_DIR / (name + '.csv')}')"

print("\n== 1. deposits per pool  (ours vs Supply_Side_Overview_Per_Pool) ==")
print(db.sql(f"""
  WITH ours AS (SELECT pool_group, count(*) n, count(DISTINCT owner_) lenders FROM pool_v2_evt_deposit GROUP BY 1)
  SELECT d.pool, d.deposits AS dune_deposits, o.n AS our_deposits, d.unique_lenders AS dune_lenders, o.lenders AS our_lenders
  FROM {csv("Maple_Finance_Supply_Side_Overview_Per_Pool")} d
  LEFT JOIN ours o ON lower(o.pool_group) LIKE '%' || lower(replace(d.pool,' ','')) || '%'
  ORDER BY d.deposits DESC"""))

print("\n== 2. strategy fees all-time  (ours vs Strategy_Fees_Total) ==")
print(db.sql(f"""
  SELECT contract_type, sum(fees)/1e6 AS ours_usd
  FROM (SELECT contract_type, fees FROM mapleskystrategy_evt_strategyfeescollected
        UNION ALL SELECT contract_type, fees FROM mapleaavestrategy_evt_strategyfeescollected)
  GROUP BY 1"""))
print(db.sql(f"SELECT sky_all_time, aave_all_time, total_strategy_fees FROM {csv('Maple_V2_Strategy_Fees_Total')}"))

print("\n== 3. loan counts  (ours vs Borrower_Totals: loans=514, unique_borrowers=136) ==")
print(db.sql("""
  SELECT 'open_term' k, count(DISTINCT loan_) loans FROM opentermloanmanager_evt_claimedfundsdistributed
  UNION ALL SELECT 'fixed_term_lm', count(DISTINCT loan_) FROM loanmanager_evt_fundsdistributed
  UNION ALL SELECT 'fixed_term_loan_contracts', count(DISTINCT contract_address) FROM fixedtermloan_evt_paymentmade"""))

print("\n== 4. monthly mgmt + service fees  (ours vs Fees_Breakdown, last 6 months) ==")
print(db.sql(f"""
  WITH m AS (
    SELECT date_trunc('month', evt_block_time) mo, sum(delegateManagementFee_ + platformManagementFee_)/1e6 mgmt, 0 svc
    FROM loanmanager_evt_managementfeespaid GROUP BY 1
    UNION ALL
    SELECT date_trunc('month', evt_block_time), 0, sum(delegateServiceFee_ + partialRefinanceDelegateServiceFee_ + platformServiceFee_ + partialRefinancePlatformServiceFee_)/1e6
    FROM mapleloanfeemanager_evt_servicefeespaid GROUP BY 1)
  SELECT d.month, d.loan_mgmt_fee AS dune_mgmt, sum(m.mgmt) AS ours_mgmt, d.loan_service_fee AS dune_svc, sum(m.svc) AS ours_svc
  FROM {csv("Maple_Finance_Fees_Breakdown")} d LEFT JOIN m ON m.mo = CAST(d.month AS TIMESTAMP)
  GROUP BY 1,2,4 ORDER BY 1 DESC LIMIT 6"""))
