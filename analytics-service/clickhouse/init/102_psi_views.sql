-- ============================================================================
-- AWARE PSI Index Views
-- ============================================================================
-- Provides denormalized views for PSI index construction.
-- These views join scores with profiles and P&L for index eligibility queries.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- PSI ELIGIBLE TRADERS VIEW
-- ----------------------------------------------------------------------------
-- Joins smart_money_scores with trader_profiles, trader_pnl, and ml_scores
-- to provide all columns needed by psi_index.py for index construction.
--
-- Usage:
--   SELECT username, total_score, sharpe_ratio, strategy_type, ...
--   FROM polybot.aware_psi_eligible_traders
--   WHERE total_score >= 70 AND total_trades >= 100
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW polybot.aware_psi_eligible_traders AS
SELECT
    -- Identity
    s.proxy_address AS proxy_address,
    s.username AS username,

    -- Score data (from smart_money_scores)
    s.total_score AS total_score,
    s.tier AS tier,
    s.profitability_score AS profitability_score,
    s.risk_adjusted_score AS risk_adjusted_score,
    s.consistency_score AS consistency_score,
    s.track_record_score AS track_record_score,
    s.strategy_type AS strategy_type,
    s.strategy_confidence AS strategy_confidence,
    s.rank AS rank,
    s.rank_change AS rank_change,
    s.calculated_at AS calculated_at,
    s.model_version AS model_version,

    -- Profile metrics (from trader_profiles)
    coalesce(p.total_trades, 0) AS total_trades,
    coalesce(p.total_volume_usd, 0.0) AS total_volume_usd,
    coalesce(p.days_active, 0) AS days_active,
    coalesce(p.unique_markets, 0) AS unique_markets,
    p.first_trade_at,
    p.last_trade_at,
    coalesce(p.avg_trade_size, 0.0) AS avg_trade_size,

    -- P&L data (prefer trader_pnl, fallback to profiles)
    if(pnl.proxy_address != '', pnl.total_realized_pnl, coalesce(p.total_pnl, 0.0)) AS total_pnl,
    if(pnl.proxy_address != '', pnl.win_rate, 0.0) AS win_rate,
    if(pnl.proxy_address != '', pnl.total_positions_closed, 0) AS positions_closed,
    if(pnl.proxy_address != '', pnl.winning_positions, 0) AS winning_positions,
    if(pnl.proxy_address != '', pnl.losing_positions, 0) AS losing_positions,

    -- Risk metrics (from ML scores if available, else 0)
    -- TODO: Calculate Sharpe from P&L variance in Phase 2
    if(ml.proxy_address != '', ml.sharpe_ratio, 0.0) AS sharpe_ratio,
    if(ml.proxy_address != '', ml.max_drawdown, 0.0) AS max_drawdown,
    if(ml.proxy_address != '', ml.maker_ratio, 0.0) AS maker_ratio

FROM (SELECT * FROM polybot.aware_smart_money_scores FINAL) AS s
LEFT JOIN (SELECT * FROM polybot.aware_trader_profiles FINAL) AS p
    ON s.proxy_address = p.proxy_address
LEFT JOIN (SELECT * FROM polybot.aware_trader_pnl FINAL) AS pnl
    ON s.proxy_address = pnl.proxy_address
LEFT JOIN (SELECT * FROM polybot.aware_ml_scores FINAL) AS ml
    ON s.proxy_address = ml.proxy_address;

-- ----------------------------------------------------------------------------
-- AWARE LEADERBOARD VIEW
-- ----------------------------------------------------------------------------
-- The rule-based scorer decides rank, score and tier. It used to be the other
-- way round -- ML preferred, rules as fallback -- and that is what broke the
-- leaderboard:
--
--                        rank 1    rank 2    rank 3    tiers
--   rule-based scorer    88 DIA    87 DIA    87 DIA    155 Diamond, 3545 Gold
--   aware_ml_scores      33 SIL    33 SIL    33 SIL    0 Diamond, 120 Gold
--
-- aware_ml_scores is not a model. sharpe_calculator.py fills it by bucketing
-- an annualised Sharpe into 30/45/60/75/90 and discounting by confidence, so
-- 60 * (0.5 + 0.5*0.1) = 33 -- which is why almost every trader scored 33 and
-- the page looked randomly ordered. It also renumbers rank by Sharpe, so the
-- two numbering schemes were interleaved and the visible ranks had holes in
-- them (3, 4, 14, 19...). The Sharpe underneath is itself noise: it is
-- annualised from as few as three daily observations.
--
-- win_rate comes from the P&L, which actually has it: 32,089 traders with a
-- real figure averaging 49%. The ML table hardcodes the column to 0.0 with a
-- "calculated elsewhere" comment, and preferring it is what made every row
-- show 0%.
--
-- The ML columns are still selected so the shape of the view does not change,
-- and so the day a real model lands there is somewhere to put it.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW polybot.aware_leaderboard_ml AS
SELECT
  s.rank AS rank,
  s.username AS username,
  p.pseudonym AS pseudonym,
  s.proxy_address AS proxy_address,
  toFloat32(s.total_score) AS smart_money_score,
  s.tier AS tier,
  -- Kept for the ML column in the UI; not what ranks anyone.
  if(ml.proxy_address = '', 0.0, ml.ml_score) AS ml_score,
  if(ml.proxy_address = '', 0.0, ml.tier_confidence) AS tier_confidence,
  if(ml.proxy_address = '', 0.0, ml.predicted_sharpe_30d) AS predicted_sharpe_30d,
  if(ml.proxy_address = '', 0.0, ml.sharpe_ratio) AS sharpe_ratio,
  -- Measured, not predicted.
  if(pnl.proxy_address = '', 0.0, pnl.win_rate) AS win_rate,
  if(ml.proxy_address = '', 0.0, ml.max_drawdown) AS max_drawdown,
  if(ml.proxy_address = '', 0.0, ml.maker_ratio) AS maker_ratio,
  -- Profile data
  p.total_pnl AS total_pnl,
  p.total_volume_usd AS total_volume,
  s.strategy_type AS strategy_type,
  s.strategy_confidence AS strategy_confidence,
  -- Metadata
  if(ml.proxy_address = '', 'rule-based', ml.model_version) AS model_version,
  s.calculated_at AS calculated_at
FROM (SELECT * FROM polybot.aware_smart_money_scores FINAL) AS s
LEFT JOIN (SELECT * FROM polybot.aware_trader_profiles FINAL) AS p
  ON s.proxy_address = p.proxy_address
LEFT JOIN (SELECT * FROM polybot.aware_ml_scores FINAL) AS ml
  ON s.proxy_address = ml.proxy_address
LEFT JOIN (SELECT * FROM polybot.aware_trader_pnl FINAL) AS pnl
  ON s.proxy_address = pnl.proxy_address
ORDER BY rank ASC;
