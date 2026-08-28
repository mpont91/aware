-- =============================================================================
-- HIDDEN ALPHA: key the table on the trader
-- =============================================================================
-- The sort key was (discovery_type, discovered_at, username), and on a
-- ReplacingMergeTree the sort key is the identity. Two of those three columns
-- do not identify anything here: username is empty for nearly every Polymarket
-- wallet, and discovered_at is the moment the scan ran, shared by everything it
-- found. So a scan returning ten hidden gems collapsed into a single row.
--
-- Keyed on the wallet and the discovery type instead: one row per trader per
-- kind of discovery, replaced when a later scan finds them again, which is the
-- behaviour a ReplacingMergeTree is for.
--
-- Recreated rather than altered because ClickHouse cannot change a sort key in
-- place. Nothing is lost: the job that fills this never inserted a row until
-- now, so the table holds at most the handful written while testing.
-- =============================================================================

DROP TABLE IF EXISTS polybot.aware_hidden_alpha;

CREATE TABLE polybot.aware_hidden_alpha (
    id String,
    username String,
    proxy_address String,
    discovery_type String,
    discovery_score Float64,
    reason String,
    total_pnl Decimal(18, 6),
    sharpe_ratio Float64,
    win_rate Float64,
    total_trades UInt32,
    days_active UInt32,
    upside_estimate Float64,
    risk_level String,
    discovered_at DateTime64(3),
    _version UInt64 DEFAULT toUnixTimestamp64Milli(now64(3))
)
ENGINE = ReplacingMergeTree(_version)
ORDER BY (discovery_type, proxy_address)
SETTINGS index_granularity = 8192;
