#!/usr/bin/env python3
"""
AWARE Analytics - Trader working capital estimation.

The mirror funds size a copied trade as:

    fundShares = traderShares * (fundCapital / traderCapital) * weight

That arithmetic only closes if traderCapital is the money the trader actually
has at risk. Summed over an index whose weights total one, a fully deployed set
of constituents then produces a fully deployed fund.

The mirror used to read aware_trader_profiles.total_volume_usd for this, which
is lifetime turnover. The traders being copied churn small positions, so their
volume overstated their working capital by a factor of 6 to 11. Every copy came
out that many times too small, most then fell below min-trade-usd and were
dropped, and the funds sat almost entirely in cash while reporting five-figure
allocations.

This estimates it as peak concurrent deployed cost: walk every position's open
and close in time order and take the running maximum of what was outstanding.
That is the most the trader ever had working at one moment.

Usage:
    python trader_capital.py             # refresh estimates
    python trader_capital.py --show      # print a sample without writing
"""

import argparse
import logging
import os
import time

import clickhouse_connect

logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('trader-capital')

# Positions resolved longer ago than this say little about what a trader is
# working with now. A trader with nothing in the window gets no estimate at all
# rather than a stale one, and the mirror falls back to weight-only sizing,
# which errs small.
LOOKBACK_DAYS = 30

# Floor on the estimate. Below this the ratio grows extreme enough that the
# max-position cap would be deciding every size on its own, which is not sizing
# so much as clipping. A trader working with less than this is too small to
# copy proportionally.
MIN_CAPITAL_USD = 100.0


def _sweep_sql(lookback_days: int, min_capital: float) -> str:
    """Peak concurrent cost per trader, as a single pass inside ClickHouse."""
    return f"""
    WITH events AS (
        -- +cost when a position opens, -cost when it resolves. Net sellers
        -- (negative cost basis) contribute nothing to capital at risk.
        SELECT proxy_address, first_trade_at AS t, net_cost AS delta
        FROM (SELECT * FROM polybot.aware_position_pnl FINAL)
        WHERE net_cost > 0
          AND resolved_at >= now() - INTERVAL {lookback_days} DAY
        UNION ALL
        SELECT proxy_address, resolved_at AS t, -net_cost AS delta
        FROM (SELECT * FROM polybot.aware_position_pnl FINAL)
        WHERE net_cost > 0
          AND resolved_at >= now() - INTERVAL {lookback_days} DAY
    ),
    running AS (
        SELECT
            proxy_address,
            sum(delta) OVER (
                PARTITION BY proxy_address ORDER BY t
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS outstanding
        FROM events
    ),
    peak AS (
        SELECT proxy_address, max(outstanding) AS peak_concurrent_usd
        FROM running
        GROUP BY proxy_address
    ),
    counted AS (
        SELECT proxy_address, count() AS positions_counted
        FROM (SELECT * FROM polybot.aware_position_pnl FINAL)
        WHERE net_cost > 0
          AND resolved_at >= now() - INTERVAL {lookback_days} DAY
        GROUP BY proxy_address
    )
    SELECT
        p.proxy_address,
        greatest(p.peak_concurrent_usd, {min_capital}) AS estimated_capital_usd,
        p.peak_concurrent_usd,
        toUInt32(c.positions_counted) AS positions_counted,
        toUInt16({lookback_days}) AS lookback_days
    FROM peak p
    INNER JOIN counted c ON p.proxy_address = c.proxy_address
    WHERE p.peak_concurrent_usd > 0
    """


def refresh(client, lookback_days: int = LOOKBACK_DAYS,
            min_capital: float = MIN_CAPITAL_USD) -> dict:
    """Recompute every trader's capital estimate and store it."""
    start = time.time()

    client.command(f"""
        INSERT INTO polybot.aware_trader_capital
            (proxy_address, estimated_capital_usd, peak_concurrent_usd,
             positions_counted, lookback_days)
        {_sweep_sql(lookback_days, min_capital)}
    """)

    stats = client.query("""
        SELECT count(),
               median(estimated_capital_usd),
               countIf(peak_concurrent_usd < estimated_capital_usd)
        FROM (SELECT * FROM polybot.aware_trader_capital FINAL)
    """).result_rows[0]

    elapsed = time.time() - start
    logger.info(
        "Estimated capital for %d traders in %.1fs (median $%.0f, %d at the floor)",
        stats[0], elapsed, stats[1] or 0, stats[2],
    )
    return {
        'status': 'success',
        'traders': int(stats[0]),
        'median_capital_usd': round(float(stats[1] or 0), 2),
        'at_floor': int(stats[2]),
        'elapsed_seconds': elapsed,
    }


def show(client, limit: int = 15) -> None:
    """Print what the estimate would be, next to the value it replaces."""
    rows = client.query(f"""
        SELECT
            i.index_type,
            count() AS members,
            round(median(p.total_volume_usd)) AS volume_proxy,
            round(median(k.estimated_capital_usd)) AS estimated_capital
        FROM (SELECT * FROM polybot.aware_psi_index FINAL) i
        LEFT JOIN (SELECT * FROM polybot.aware_trader_profiles FINAL) p
            ON i.proxy_address = p.proxy_address
        LEFT JOIN (SELECT * FROM polybot.aware_trader_capital FINAL) k
            ON i.proxy_address = k.proxy_address
        GROUP BY i.index_type
        ORDER BY i.index_type
        LIMIT {limit}
    """).result_rows
    print(f"{'index':16}{'members':>9}{'volume proxy':>15}{'estimated':>12}")
    for index_type, members, volume, capital in rows:
        print(f"{index_type:16}{members:>9}{volume or 0:>15,.0f}{capital or 0:>12,.0f}")


def main() -> int:
    parser = argparse.ArgumentParser(description='Estimate trader working capital')
    parser.add_argument('--show', action='store_true',
                        help='print current estimates without recomputing')
    parser.add_argument('--lookback-days', type=int, default=LOOKBACK_DAYS)
    args = parser.parse_args()

    client = clickhouse_connect.get_client(
        host=os.getenv('CLICKHOUSE_HOST', 'localhost'),
        port=int(os.getenv('CLICKHOUSE_PORT', '8123')),
        username=os.getenv('CLICKHOUSE_USER', 'default'),
        password=os.getenv('CLICKHOUSE_PASSWORD', ''),
        database='polybot',
    )

    if args.show:
        show(client)
        return 0

    result = refresh(client, lookback_days=args.lookback_days)
    return 0 if result['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
