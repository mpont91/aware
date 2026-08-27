"""
Strategy P&L calculation.

Measures paper-trading performance per strategy from the simulator's own fills,
so we can tell whether a strategy actually makes money instead of guessing from
a snapshot of open positions.

Source of truth is polybot.user_trades filtered to the simulator account: the
paper exchange publishes a user trade on every fill, so those rows are the
positions we really hold (order placements are not, most are cancelled).

Positions are marked into three buckets:
  - RESOLVED -> payout of 1 or 0 per share. Definitive.
  - OPEN     -> current best bid, only if the quote is fresh. Unrealized.
  - STALE    -> unresolved but the last quote is older than MARK_MAX_AGE_MIN.
                Excluded from total P&L and ROI: an expired 15-minute market
                still quoting 0.99 from hours ago would otherwise book a large
                fake profit. Reported separately so the gap stays visible.

Attribution is by token_id: tokens traded by the fund mirror come from
aware_fund_executions, the rest of the strategy's tokens from
strategy_gabagool_orders. A token touched by both is attributed to MIRROR,
which is the more specific signal; that overlap is reported separately.

Environment Variables:
    CLICKHOUSE_HOST - ClickHouse host (default: localhost)
    CLICKHOUSE_PORT - ClickHouse HTTP port (default: 8123)
    CLICKHOUSE_DATABASE - Database name (default: polybot)
    SIM_PROXY_ADDRESS - Simulator account in user_trades (default: sim)
    MARK_MAX_AGE_MIN - Max quote age to mark an open position (default: 15)

Usage:
    python strategy_pnl.py            # calculate, store and print a report
    python strategy_pnl.py --dry-run  # print only, don't write to ClickHouse
"""

import argparse
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from clickhouse_client import ClickHouseClient

logger = logging.getLogger(__name__)

SIM_PROXY = os.getenv('SIM_PROXY_ADDRESS', 'sim')
MARK_MAX_AGE_MIN = float(os.getenv('MARK_MAX_AGE_MIN', '15'))

# One row per token we hold, marked to payout (resolved) or best bid (open).
POSITIONS_QUERY = """
WITH
    fills AS (
        SELECT
            token_id,
            any(condition_id)  AS condition_id,
            any(market_slug)   AS market_slug,
            any(title)         AS title,
            any(outcome)       AS outcome,
            any(outcome_index) AS outcome_index,
            count()            AS fills,
            sumIf(size, side = 'BUY') - sumIf(size, side = 'SELL')             AS net_shares,
            sumIf(size * price, side = 'BUY') - sumIf(size * price, side = 'SELL') AS cost_usd,
            sum(size * price)  AS volume_usd,
            min(ts)            AS first_fill_at,
            max(ts)            AS last_fill_at
        FROM polybot.user_trades
        WHERE proxy_address = %(sim_proxy)s
        GROUP BY token_id
    ),
    mirror_tokens AS (
        SELECT DISTINCT token_id FROM polybot.aware_fund_executions
    ),
    gabagool_tokens AS (
        SELECT DISTINCT token_id FROM polybot.strategy_gabagool_orders
    ),
    resolutions AS (
        SELECT
            condition_id,
            argMax(winning_outcome_index, resolution_time) AS winning_outcome_index,
            max(is_resolved)                               AS is_resolved
        FROM polybot.aware_market_resolutions
        GROUP BY condition_id
    ),
    marks AS (
        SELECT asset_id, best_bid_price, tob_ts
        FROM polybot.market_ws_tob_latest
    )
SELECT
    multiIf(
        f.token_id IN (SELECT token_id FROM mirror_tokens),   'MIRROR',
        f.token_id IN (SELECT token_id FROM gabagool_tokens), 'GABAGOOL',
        'UNATTRIBUTED'
    ) AS strategy,
    f.token_id     AS token_id,
    f.condition_id AS condition_id,
    f.market_slug  AS market_slug,
    f.title        AS title,
    f.outcome      AS outcome,
    f.fills        AS fills,
    f.net_shares   AS net_shares,
    f.cost_usd     AS cost_usd,
    f.volume_usd   AS volume_usd,
    if(f.net_shares != 0, f.cost_usd / f.net_shares, 0) AS avg_price,
    ifNull(r.is_resolved, 0) AS is_resolved,
    if(ifNull(r.is_resolved, 0) = 1 AND r.winning_outcome_index = f.outcome_index, 1, 0) AS won,
    -- resolved: 1 or 0 per share. open: best bid, falling back to entry price
    -- so a missing quote reads as flat rather than as a total loss.
    if(
        ifNull(r.is_resolved, 0) = 1,
        if(r.winning_outcome_index = f.outcome_index, 1.0, 0.0),
        ifNull(nullIf(m.best_bid_price, 0), if(f.net_shares != 0, f.cost_usd / f.net_shares, 0))
    ) AS mark_price,
    -- age of the quote behind mark_price; a missing quote counts as infinitely old
    if(m.tob_ts = toDateTime64(0, 3), 999999, dateDiff('second', m.tob_ts, now()) / 60.0) AS mark_age_min,
    f.first_fill_at AS first_fill_at,
    f.last_fill_at  AS last_fill_at
FROM fills AS f
LEFT JOIN resolutions AS r ON f.condition_id = r.condition_id
LEFT JOIN marks       AS m ON f.token_id = m.asset_id
WHERE f.net_shares > 0
ORDER BY strategy, f.cost_usd DESC
"""

# Tokens claimed by both strategies; reported so the attribution stays honest.
OVERLAP_QUERY = """
SELECT count()
FROM (
    SELECT DISTINCT token_id FROM polybot.aware_fund_executions
    INTERSECT
    SELECT DISTINCT token_id FROM polybot.strategy_gabagool_orders
)
"""

# Per-fund split of the mirror's P&L, prorated by requested shares. Funds copy
# the same token, so fills cannot be attributed exactly; this apportions each
# token's P&L by how many shares each fund asked for.
FUND_SPLIT_QUERY = """
SELECT
    fund_id,
    token_id,
    sum(fund_shares) AS requested_shares
FROM polybot.aware_fund_executions
GROUP BY fund_id, token_id
"""


def _rows_to_dicts(result) -> List[Dict[str, Any]]:
    cols = result.column_names
    return [dict(zip(cols, row)) for row in result.result_rows]


def calculate_positions(client: ClickHouseClient) -> List[Dict[str, Any]]:
    """Return one marked position per token held by the simulator."""
    result = client.client.query(POSITIONS_QUERY, parameters={'sim_proxy': SIM_PROXY})
    positions = _rows_to_dicts(result)

    for p in positions:
        p['value_usd'] = float(p['net_shares']) * float(p['mark_price'])
        p['pnl_usd'] = p['value_usd'] - float(p['cost_usd'])
        if int(p['is_resolved']) == 1:
            p['mark_status'] = 'RESOLVED'
            p['mark_age_min'] = 0.0
        elif float(p['mark_age_min']) <= MARK_MAX_AGE_MIN:
            p['mark_status'] = 'OPEN'
        else:
            p['mark_status'] = 'STALE'

    return positions


def aggregate(positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate marked positions into one row per strategy."""
    by_strategy: Dict[str, Dict[str, Any]] = {}

    for p in positions:
        s = by_strategy.setdefault(p['strategy'], {
            'strategy': p['strategy'],
            'positions': 0, 'positions_resolved': 0, 'fills': 0,
            'volume_usd': 0.0, 'cost_usd': 0.0,
            'realized_pnl': 0.0, 'unrealized_pnl': 0.0,
            'stale_positions': 0, 'stale_cost_usd': 0.0, '_stale_pnl': 0.0,
            '_wins': 0,
        })
        s['positions'] += 1
        s['fills'] += int(p['fills'])
        s['volume_usd'] += float(p['volume_usd'])
        s['cost_usd'] += float(p['cost_usd'])

        if p['mark_status'] == 'RESOLVED':
            s['positions_resolved'] += 1
            s['realized_pnl'] += p['pnl_usd']
            if p['pnl_usd'] > 0:
                s['_wins'] += 1
        elif p['mark_status'] == 'OPEN':
            s['unrealized_pnl'] += p['pnl_usd']
        else:
            # Excluded from total/ROI: the quote is too old to be a valid mark.
            s['stale_positions'] += 1
            s['stale_cost_usd'] += float(p['cost_usd'])
            s['_stale_pnl'] += p['pnl_usd']

    rows = []
    for s in by_strategy.values():
        s['total_pnl'] = s['realized_pnl'] + s['unrealized_pnl']
        priced_cost = s['cost_usd'] - s['stale_cost_usd']
        s['roi_pct'] = (s['total_pnl'] / priced_cost * 100) if priced_cost else 0.0
        s['win_rate'] = (s['_wins'] / s['positions_resolved']) if s['positions_resolved'] else 0.0
        s.pop('_wins')
        rows.append(s)

    return sorted(rows, key=lambda r: -abs(r['cost_usd']))


def split_mirror_by_fund(client: ClickHouseClient,
                         positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Prorate mirror P&L across funds by requested shares.

    Funds copy overlapping tokens, so this is an apportionment, not an exact
    attribution. Reported separately from the exact per-strategy numbers.
    """
    result = client.client.query(FUND_SPLIT_QUERY)
    weights: Dict[str, Dict[str, float]] = {}
    for row in _rows_to_dicts(result):
        weights.setdefault(row['token_id'], {})[row['fund_id']] = float(row['requested_shares'])

    by_fund: Dict[str, Dict[str, float]] = {}
    for p in positions:
        if p['strategy'] != 'MIRROR' or p['mark_status'] == 'STALE':
            continue
        shares = weights.get(p['token_id'], {})
        total = sum(shares.values())
        if not total:
            continue
        for fund_id, requested in shares.items():
            f = by_fund.setdefault(fund_id, {
                'fund_id': fund_id, 'cost_usd': 0.0, 'pnl_usd': 0.0,
                'realized_pnl': 0.0, 'unrealized_pnl': 0.0, 'positions': 0,
            })
            share = requested / total
            f['cost_usd'] += float(p['cost_usd']) * share
            f['pnl_usd'] += p['pnl_usd'] * share
            # Split the same way the per-strategy figures are, so a fund page
            # can distinguish settled losses from positions still in play.
            if p['mark_status'] == 'RESOLVED':
                f['realized_pnl'] += p['pnl_usd'] * share
            else:
                f['unrealized_pnl'] += p['pnl_usd'] * share
            f['positions'] += 1

    for f in by_fund.values():
        f['roi_pct'] = (f['pnl_usd'] / f['cost_usd'] * 100) if f['cost_usd'] else 0.0

    return sorted(by_fund.values(), key=lambda r: -r['cost_usd'])


def store_by_fund(client: ClickHouseClient, calculated_at: datetime,
                  by_fund: List[Dict[str, Any]]) -> None:
    """Persist the per-fund breakdown so the fund pages have something real."""
    if not by_fund:
        return
    client.client.insert(
        'polybot.aware_fund_pnl',
        [[
            calculated_at, f['fund_id'], int(f['positions']), float(f['cost_usd']),
            float(f['realized_pnl']), float(f['unrealized_pnl']),
            float(f['pnl_usd']), float(f['roi_pct']),
        ] for f in by_fund],
        column_names=[
            'calculated_at', 'fund_id', 'positions', 'cost_usd',
            'realized_pnl', 'unrealized_pnl', 'total_pnl', 'roi_pct',
        ],
    )


def store(client: ClickHouseClient, calculated_at: datetime,
          positions: List[Dict[str, Any]], totals: List[Dict[str, Any]]) -> None:
    """Persist this run's snapshot."""
    client.client.insert(
        'polybot.aware_strategy_pnl_positions',
        [[
            calculated_at, p['strategy'], p['token_id'], p['condition_id'],
            p['market_slug'], p['title'], p['outcome'], int(p['fills']),
            float(p['net_shares']), float(p['cost_usd']), float(p['avg_price']),
            int(p['is_resolved']), int(p['won']), p['mark_status'],
            float(p['mark_age_min']), float(p['mark_price']),
            p['value_usd'], p['pnl_usd'], p['first_fill_at'], p['last_fill_at'],
        ] for p in positions],
        column_names=[
            'calculated_at', 'strategy', 'token_id', 'condition_id', 'market_slug',
            'title', 'outcome', 'fills', 'net_shares', 'cost_usd', 'avg_price',
            'is_resolved', 'won', 'mark_status', 'mark_age_min', 'mark_price',
            'value_usd', 'pnl_usd', 'first_fill_at', 'last_fill_at',
        ],
    )

    client.client.insert(
        'polybot.aware_strategy_pnl',
        [[
            calculated_at, t['strategy'], int(t['positions']), int(t['positions_resolved']),
            int(t['fills']), float(t['volume_usd']), float(t['cost_usd']),
            float(t['realized_pnl']), float(t['unrealized_pnl']),
            int(t['stale_positions']), float(t['stale_cost_usd']),
            float(t['total_pnl']), float(t['roi_pct']), float(t['win_rate']),
        ] for t in totals],
        column_names=[
            'calculated_at', 'strategy', 'positions', 'positions_resolved', 'fills',
            'volume_usd', 'cost_usd', 'realized_pnl', 'unrealized_pnl',
            'stale_positions', 'stale_cost_usd', 'total_pnl', 'roi_pct', 'win_rate',
        ],
    )


def format_report(totals: List[Dict[str, Any]], positions: List[Dict[str, Any]],
                  by_fund: List[Dict[str, Any]], overlap: int) -> str:
    lines = []
    w = 92
    lines.append("=" * w)
    lines.append("STRATEGY P&L (paper trading)")
    lines.append("=" * w)
    lines.append(f"{'strategy':<14}{'pos':>5}{'resol':>7}{'fills':>7}"
                 f"{'priced cost':>13}{'realized':>12}{'unreal':>11}{'total':>12}{'ROI':>9}{'win':>7}")
    lines.append("-" * w)
    for t in totals:
        priced_cost = t['cost_usd'] - t['stale_cost_usd']
        lines.append(
            f"{t['strategy']:<14}{t['positions']:>5}{t['positions_resolved']:>7}{t['fills']:>7}"
            f"{priced_cost:>13,.2f}{t['realized_pnl']:>+12,.2f}{t['unrealized_pnl']:>+11,.2f}"
            f"{t['total_pnl']:>+12,.2f}{t['roi_pct']:>8.2f}%{t['win_rate'] * 100:>6.0f}%"
        )
    lines.append("-" * w)
    tot_cost = sum(t['cost_usd'] - t['stale_cost_usd'] for t in totals)
    tot_real = sum(t['realized_pnl'] for t in totals)
    tot_pnl = sum(t['total_pnl'] for t in totals)
    lines.append(f"{'TOTAL':<14}{'':>19}{tot_cost:>13,.2f}{tot_real:>+12,.2f}{'':>11}"
                 f"{tot_pnl:>+12,.2f}{(tot_pnl / tot_cost * 100) if tot_cost else 0:>8.2f}%")
    lines.append("")
    lines.append("Realized is definitive. Unrealized is marked to a quote at most "
                 f"{MARK_MAX_AGE_MIN:.0f} min old.")

    stale_cost = sum(t['stale_cost_usd'] for t in totals)
    stale_n = sum(t['stale_positions'] for t in totals)
    if stale_n:
        lines.append("")
        lines.append(f"EXCLUDED: {stale_n} position(s), ${stale_cost:,.2f} of cost, have no "
                     f"resolution and no fresh quote.")
        lines.append("  These are almost all expired markets whose result was never ingested, so "
                     "their true")
        lines.append("  P&L is unknown. Counting them at their last quote would inflate the "
                     "numbers above.")
        worst = sorted((p for p in positions if p['mark_status'] == 'STALE'),
                       key=lambda x: -float(x['cost_usd']))[:3]
        for p in worst:
            lines.append(f"    {p['strategy']:<9} {p['title'][:40]:<40} "
                         f"cost {float(p['cost_usd']):>9,.2f}  quote {float(p['mark_age_min']) / 60:.1f}h old")

    if by_fund:
        lines.append("")
        lines.append("Mirror split by fund (prorated by requested shares, not exact):")
        for f in by_fund:
            lines.append(f"  {f['fund_id']:<14} cost {f['cost_usd']:>10,.2f}   "
                         f"P&L {f['pnl_usd']:>+10,.2f}   ROI {f['roi_pct']:>7.2f}%")

    resolved = [p for p in positions if p['mark_status'] == 'RESOLVED']
    if resolved:
        lines.append("")
        lines.append("Biggest resolved moves:")
        for p in sorted(resolved, key=lambda x: -abs(x['pnl_usd']))[:5]:
            lines.append(f"  {p['strategy']:<9} {p['title'][:44]:<44} "
                         f"{p['pnl_usd']:>+10,.2f}  ({'won' if p['won'] else 'lost'})")

    if overlap:
        lines.append("")
        lines.append(f"Note: {overlap} token(s) traded by both strategies, counted under MIRROR.")

    unattributed = next((t for t in totals if t['strategy'] == 'UNATTRIBUTED'), None)
    if unattributed:
        lines.append(f"Note: {unattributed['positions']} position(s) could not be attributed "
                     f"to a strategy (${unattributed['cost_usd']:,.2f} cost).")

    lines.append("=" * w)
    return "\n".join(lines)


def run(dry_run: bool = False) -> Dict[str, Any]:
    """Calculate, optionally store, and return the P&L snapshot."""
    client = ClickHouseClient()
    calculated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    positions = calculate_positions(client)
    if not positions:
        logger.warning("No simulator fills found for proxy_address=%s", SIM_PROXY)
        return {'status': 'no_data', 'strategies': []}

    totals = aggregate(positions)
    by_fund = split_mirror_by_fund(client, positions)
    overlap = client.client.query(OVERLAP_QUERY).result_rows[0][0]

    if not dry_run:
        store(client, calculated_at, positions, totals)
        store_by_fund(client, calculated_at, by_fund)
        logger.info("Stored P&L snapshot for %d strategies, %d positions",
                    len(totals), len(positions))

    return {
        'status': 'success',
        'calculated_at': calculated_at.isoformat(),
        'strategies': totals,
        'positions': positions,
        'by_fund': by_fund,
        'overlap_tokens': overlap,
    }


def main():
    parser = argparse.ArgumentParser(description='Calculate paper-trading P&L per strategy')
    parser.add_argument('--dry-run', action='store_true', help="don't write to ClickHouse")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    result = run(dry_run=args.dry_run)
    if result['status'] == 'no_data':
        print("No simulator fills found. Is the paper exchange running?")
        return

    print(format_report(result['strategies'], result['positions'],
                        result['by_fund'], result['overlap_tokens']))


if __name__ == '__main__':
    main()
