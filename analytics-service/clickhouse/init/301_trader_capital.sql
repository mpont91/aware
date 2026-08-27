-- =============================================================================
-- TRADER WORKING CAPITAL
-- =============================================================================
-- Position sizing for the mirror funds is capital-proportional: the fund copies
-- a trader's trade scaled by (fundCapital / traderCapital) * weight. With a
-- correct per-trader estimate the arithmetic closes — a fully deployed index
-- means a fully deployed fund, since summing traderCapital * (fundCapital /
-- traderCapital) * weight over the constituents gives fundCapital.
--
-- That only holds if traderCapital is what the trader actually has at risk.
-- The mirror previously used aware_trader_profiles.total_volume_usd, which is
-- lifetime turnover: these traders churn small positions, so volume overstated
-- their working capital by 6x to 11x. The funds sized every copy at a fraction
-- of what they should and most orders then fell under min-trade-usd and were
-- dropped, which is why the mirror funds looked idle while holding five figures.
--
-- Estimated here as peak concurrent deployed cost: sweep the open and close of
-- every resolved position and take the running maximum. That is the most money
-- the trader had working at any one moment, which is the quantity the sizing
-- ratio is asking for.
-- =============================================================================

CREATE TABLE IF NOT EXISTS polybot.aware_trader_capital (
    proxy_address String,
    -- Peak simultaneous cost basis across the lookback window, floored.
    estimated_capital_usd Float64,
    -- Unfloored, so the floor's effect stays visible.
    peak_concurrent_usd Float64,
    positions_counted UInt32,
    lookback_days UInt16,
    calculated_at DateTime64(3) DEFAULT now64(3),
    _version UInt64 DEFAULT toUnixTimestamp64Milli(now64(3))
)
ENGINE = ReplacingMergeTree(_version)
ORDER BY (proxy_address)
SETTINGS index_granularity = 8192;
