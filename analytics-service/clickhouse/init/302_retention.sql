-- =============================================================================
-- RETENTION
-- =============================================================================
-- The operational firehoses are kept for a rolling week; the observation data
-- is kept forever.
--
-- Nothing expired before this, and the split matters because the two grow at
-- very different rates. Measured over the first 1.4 days of the production
-- deployment, ClickHouse grew 533 MB/day:
--
--   analytics_events       277 MB/day   52%
--   market_ws_tob          103 MB/day   19%
--   aware_global_trades     54 MB/day   10%   <- the part with lasting value
--   market_ws_trades        33 MB/day    6%
--   executor_order_status   15 MB/day    3%
--
-- At that rate the 25 GB free on the host lasts about seven weeks, and nine
-- tenths of what fills it is raw event plumbing that is only useful for
-- debugging something happening now. The trades we observe, the resolutions
-- and the score history are what the project is actually accumulating, and
-- they are deliberately absent from this file.
--
-- Every table below is partitioned by toDate(ts), so expiry drops whole
-- partitions rather than rewriting parts: the trim costs almost nothing.
--
-- materialize_ttl_after_modify is off. Left on, MODIFY TTL rewrites every
-- existing part the moment it runs, which on analytics_events asked for 1.56
-- GiB against a 1.32 GiB server limit and failed the mutation. The rule only
-- needs to hold from here on: expiry is applied during ordinary merges, and
-- anything already past the window is dropped a partition at a time.
-- =============================================================================

SET materialize_ttl_after_modify = 0;

-- Raw Kafka event log. Materialized views read it on insert, so nothing
-- downstream needs yesterday's rows, let alone last month's.
ALTER TABLE polybot.analytics_events
    MODIFY TTL toDateTime(ts) + INTERVAL 7 DAY;

-- Order book snapshots. Marks older than fifteen minutes are already treated
-- as stale by the P&L job, so a week is generous.
ALTER TABLE polybot.market_ws_tob
    MODIFY TTL toDateTime(ts) + INTERVAL 7 DAY;

-- Public trade tape from the websocket. The trades we care about keeping are
-- in aware_global_trades, which this does not touch.
ALTER TABLE polybot.market_ws_trades
    MODIFY TTL toDateTime(ts) + INTERVAL 7 DAY;

-- Our own order lifecycle. Worth a week for working out why a fill behaved
-- the way it did; worth nothing after that.
ALTER TABLE polybot.executor_order_status
    MODIFY TTL toDateTime(ts) + INTERVAL 7 DAY;

ALTER TABLE polybot.executor_order_limit
    MODIFY TTL toDateTime(ts) + INTERVAL 7 DAY;

ALTER TABLE polybot.executor_order_cancel
    MODIFY TTL toDateTime(ts) + INTERVAL 7 DAY;

ALTER TABLE polybot.executor_order_market
    MODIFY TTL toDateTime(ts) + INTERVAL 7 DAY;
