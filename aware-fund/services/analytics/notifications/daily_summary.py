"""
Daily summary: what the bot did, sent once a day.

The operational alerts only speak when something breaks, so silence means
nothing is on fire — it does not say whether the thing is making money. Over a
long observation period that leaves you opening the dashboard out of habit to
find out. This sends the numbers instead.

Deliberately short. It answers "how did yesterday go" and nothing else; the
detail lives in the dashboard for when the answer is interesting.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timezone
from typing import Optional

logger = logging.getLogger('daily-summary')

# Hour (UTC) to send at. 06:00 UTC is early morning in Madrid, so the summary
# is waiting rather than interrupting.
SEND_HOUR_UTC = int(os.getenv('DAILY_SUMMARY_HOUR_UTC', '6'))

# The paper account's starting capital, for stating exposure as a fraction.
STARTING_CAPITAL = float(os.getenv('TOTAL_CAPITAL_USD', '100000'))

# Last date a summary went out. In memory, so a restart during the send hour
# can repeat one — preferable to the alternative of missing one.
_last_sent: Optional[date] = None


def _money(v: float) -> str:
    sign = '+' if v >= 0 else '−'
    return f"{sign}${abs(v):,.2f}"


def build_summary(ch_client) -> Optional[str]:
    """The message, or None if there is nothing to report yet."""
    rows = ch_client.query("""
        SELECT strategy,
               argMax(total_pnl, calculated_at) AS pnl_now,
               argMaxIf(total_pnl, calculated_at,
                        calculated_at <= now() - INTERVAL 24 HOUR) AS pnl_before,
               countIf(calculated_at <= now() - INTERVAL 24 HOUR) AS prior_points
        FROM polybot.aware_strategy_pnl
        GROUP BY strategy
        ORDER BY strategy
    """).result_rows
    if not rows:
        return None

    # With less than a day of snapshots there is no 24h delta to report, so the
    # summary states the running total and says which it is rather than
    # implying a change from a baseline that does not exist.
    has_full_day = any(int(r[3]) > 0 for r in rows)
    total_now = sum(float(r[1]) for r in rows)
    total_delta = sum(float(r[1]) - float(r[2]) for r in rows if int(r[3]) > 0)

    lines = [f"<b>AWARE — daily summary</b>", ""]
    if has_full_day:
        lines.append(f"<b>Last 24h: {_money(total_delta)}</b>")
        lines.append(f"Running total: {_money(total_now)}")
    else:
        lines.append(f"<b>Since the book opened: {_money(total_now)}</b>")
        lines.append("<i>(less than a day of history, so no 24h figure yet)</i>")
    lines.append("")

    for strategy, pnl_now, pnl_before, prior in rows:
        if has_full_day and int(prior) > 0:
            lines.append(
                f"{strategy}: {_money(float(pnl_now) - float(pnl_before))} "
                f"(total {_money(float(pnl_now))})")
        else:
            lines.append(f"{strategy}: {_money(float(pnl_now))}")

    # What is actually at risk. STALE positions are excluded for the same
    # reason the dashboard excludes them: no recent print means no value.
    exposure = ch_client.query("""
        SELECT round(sumIf(cost_usd, is_resolved = 0 AND mark_status != 'STALE'), 2),
               countIf(is_resolved = 0 AND mark_status != 'STALE')
        FROM polybot.aware_strategy_pnl_positions
        WHERE calculated_at = (
            SELECT max(calculated_at) FROM polybot.aware_strategy_pnl_positions)
    """).result_rows
    open_cost, open_count = (float(exposure[0][0] or 0), int(exposure[0][1] or 0)) \
        if exposure else (0.0, 0)

    activity = ch_client.query("""
        SELECT
            (SELECT count() FROM polybot.aware_fund_executions
             WHERE executed_at > now() - INTERVAL 24 HOUR),
            (SELECT count() FROM polybot.user_trades
             WHERE ts > now() - INTERVAL 24 HOUR)
    """).result_rows
    orders, fills = (int(activity[0][0]), int(activity[0][1])) if activity else (0, 0)

    pct = 100 * open_cost / STARTING_CAPITAL if STARTING_CAPITAL else 0
    lines += [
        "",
        f"In market: ${open_cost:,.2f} ({pct:.1f}% of capital), "
        f"{open_count} position{'' if open_count == 1 else 's'}",
        f"Last 24h: {orders:,} orders, {fills:,} fills",
    ]
    return "\n".join(lines)


async def _send(text: str) -> bool:
    try:
        from notifications.telegram import TelegramNotifier
        notifier = TelegramNotifier()
        if not notifier.is_configured:
            logger.info("Daily summary ready but Telegram is not configured")
            return False
        return bool(await notifier._send_message(text, parse_mode="HTML"))
    except Exception as e:
        logger.error(f"Daily summary send failed: {e}")
        return False


def maybe_send(ch_client, force: bool = False) -> bool:
    """Send today's summary if it is the hour and it has not gone out yet."""
    global _last_sent
    now = datetime.now(timezone.utc)

    if not force:
        if now.hour != SEND_HOUR_UTC or _last_sent == now.date():
            return False

    text = build_summary(ch_client)
    if not text:
        logger.info("No P&L snapshots yet; nothing to summarise")
        return False

    sent = asyncio.run(_send(text))
    if sent and not force:
        _last_sent = now.date()
    if sent:
        logger.info("Daily summary sent")
    return sent
