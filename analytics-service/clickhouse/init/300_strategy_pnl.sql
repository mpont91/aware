-- ═══════════════════════════════════════════════════════════════════════════
-- Strategy P&L instrumentation
-- ═══════════════════════════════════════════════════════════════════════════
-- Tracks realised and unrealised P&L per strategy from simulator fills, so
-- paper trading performance can be measured over time instead of inferred
-- from a point-in-time snapshot of open positions.
-- ═══════════════════════════════════════════════════════════════════════════

-- Per-position snapshot: one row per (run, strategy, token).
CREATE TABLE IF NOT EXISTS polybot.aware_strategy_pnl_positions
(
    calculated_at   DateTime64(3),
    strategy        LowCardinality(String),
    token_id        String,
    condition_id    String,
    market_slug     LowCardinality(String),
    title           String,
    outcome         LowCardinality(String),
    fills           UInt32,
    net_shares      Float64,
    cost_usd        Float64,      -- net cash out (BUY - SELL)
    avg_price       Float64,
    is_resolved     UInt8,
    won             UInt8,        -- only meaningful when is_resolved = 1
    mark_status     LowCardinality(String),  -- RESOLVED | OPEN | STALE
    mark_age_min    Float64,      -- age of the quote used as mark, 0 if resolved
    mark_price      Float64,      -- payout if resolved, else best bid
    value_usd       Float64,      -- net_shares * mark_price
    pnl_usd         Float64,      -- value_usd - cost_usd
    first_fill_at   DateTime64(3),
    last_fill_at    DateTime64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(calculated_at)
ORDER BY (calculated_at, strategy, token_id);

-- Aggregated snapshot: one row per (run, strategy).
CREATE TABLE IF NOT EXISTS polybot.aware_strategy_pnl
(
    calculated_at       DateTime64(3),
    strategy            LowCardinality(String),
    positions           UInt32,
    positions_resolved  UInt32,
    fills               UInt64,
    volume_usd          Float64,   -- gross traded notional
    cost_usd            Float64,   -- net cash out on open + resolved
    realized_pnl        Float64,   -- resolved markets only: definitive
    unrealized_pnl      Float64,   -- open markets with a fresh quote
    stale_positions     UInt32,    -- unresolved, quote too old to trust
    stale_cost_usd      Float64,   -- excluded from total_pnl and roi_pct
    total_pnl           Float64,   -- realized + unrealized (excludes stale)
    roi_pct             Float64,   -- total_pnl / cost_usd (excludes stale)
    win_rate            Float64    -- resolved positions with pnl > 0
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(calculated_at)
ORDER BY (calculated_at, strategy);

-- Per-fund breakdown of the mirror strategy.
--
-- Kept separate from aware_strategy_pnl because the numbers are of a different
-- quality: several funds copy the same token, so a fill cannot be attributed
-- to one fund exactly. Each token's P&L is apportioned by how many shares each
-- fund asked for. Good enough to compare funds against each other, not an
-- exact ledger.
CREATE TABLE IF NOT EXISTS polybot.aware_fund_pnl
(
    calculated_at   DateTime64(3),
    fund_id         LowCardinality(String),
    positions       UInt32,
    cost_usd        Float64,
    realized_pnl    Float64,
    unrealized_pnl  Float64,
    total_pnl       Float64,
    roi_pct         Float64
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(calculated_at)
ORDER BY (calculated_at, fund_id);
