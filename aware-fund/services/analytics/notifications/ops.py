"""
Operational alerting: tell someone when the machine stops working.

The alerting that already existed is about the market — insider signals,
consensus, edge decay. Nothing watched the system itself, and the system fails
quietly. The analytics pipeline collects a status for each of its twelve jobs
and then discards the dict; underneath, 134 exception handlers log a line and
carry on. A job can fail on every cycle for days and the only trace is a line
in a container log nobody reads.

That is not hypothetical. The pipeline crash-looped for hours at a job seven
steps in, and separately the strategy service spent a night unable to reach
ClickHouse — no order placed, no fill recorded — while every container reported
"Up" and the dashboard reported healthy.

This checks two things after each cycle: whether any job failed, and whether
the engine is still trading. Both go out over whatever channels are
configured, and go out again when they clear.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger('ops-alerts')

# How long a problem stays quiet after being reported, so a job that fails
# every cycle does not send an hourly message forever.
REPEAT_AFTER = timedelta(hours=int(os.getenv('OPS_ALERT_REPEAT_HOURS', '6')))

# Past this, the engine is not merely between trades. The mirror funds place
# orders within seconds of a constituent trading and GABAGOOL quotes
# continuously on 5- and 15-minute markets.
STALL_MINUTES = int(os.getenv('OPS_ALERT_STALL_MINUTES', '60'))

# The disk filled to 100% once and took the stack down with it: ClickHouse
# could not write a temp file, Redpanda could not write a segment and restarted
# 238 times, and the ingestor went unhealthy behind it. The alerts that fired
# reported the failing job, never the reason, so the cause had to be found by
# hand. 85% leaves roughly a day of headroom at the rate this host writes.
DISK_WARN_PCT = int(os.getenv('OPS_ALERT_DISK_PCT', '85'))

# Jobs whose failure is known, understood and not actionable, so alerting on
# them is noise rather than news. Both of these fail on "No module named
# 'ml.models'": the package is simply not in the repository, so nothing can be
# done about it from here and every cycle would otherwise report it forever.
# Drop a name from this list the day the cause is fixed — a muted failure that
# nobody remembers muting is worse than no alerting at all.
IGNORED_JOBS = {
    name.strip()
    for name in os.getenv('OPS_ALERT_IGNORE_JOBS',
                          'ml_enrichment,drift_monitoring').split(',')
    if name.strip()
}

# Problem key -> when it was last reported. Lives for the life of the process,
# which in continuous mode is the life of the container; a restart re-reports
# anything still broken, which is the right side to err on.
_last_reported: dict[str, datetime] = {}


def _fmt_age(minutes: float) -> str:
    if minutes < 90:
        return f"{minutes:.0f} min"
    return f"{minutes / 60:.1f} h"


def _collect_failed_jobs(results: dict) -> list[tuple[str, str]]:
    """Jobs the pipeline itself reported as failed."""
    problems = []
    for name, outcome in (results or {}).items():
        if name in IGNORED_JOBS:
            continue
        if isinstance(outcome, dict) and outcome.get('status') == 'error':
            reason = str(outcome.get('error') or 'no reason given')[:200]
            problems.append((f'job:{name}', f'Job "{name}" failed: {reason}'))
    return problems


# Below this many copyable constituent trades in the window, silence from the
# funds is the market being quiet rather than the engine being stuck. Polymarket
# volume is event-driven and swings hard: the platform went from 5,800 trades an
# hour overnight to 340 by the morning, and in one 90-minute stretch the traders
# we mirror made five trades between them. Alerting on that is crying wolf.
MIN_COPYABLE_TO_ALERT = int(os.getenv('OPS_ALERT_MIN_COPYABLE', '10'))

# Roughly the size a constituent trade needs for a fund's share of it to clear
# min-trade-usd once it has been scaled down.
COPYABLE_NOTIONAL_USD = 30


def _copyable_trades(ch_client, minutes: float) -> Optional[int]:
    """
    Constituent trades big enough to act on, over the given window.

    Counted on ingested_at rather than ts, because that is when the engine
    could first have seen them. Mirrored indices only: PSI-ALL exists for the
    leaderboard and no fund copies it, so counting it overstates what the funds
    ever had the chance to do.
    """
    try:
        rows = ch_client.query("""
            WITH mirrored AS (
                SELECT DISTINCT proxy_address
                FROM polybot.aware_psi_index FINAL
                WHERE index_type IN ('PSI-10','PSI-25','PSI-CRYPTO',
                                     'PSI-POLITICS','PSI-SPORTS','PSI-ALPHA')
            )
            SELECT count()
            FROM polybot.aware_global_trades t
            INNER JOIN mirrored m ON t.proxy_address = m.proxy_address
            WHERE t.ingested_at > now() - INTERVAL %(minutes)s MINUTE
              AND t.notional >= %(floor)s
        """, parameters={'minutes': int(minutes),
                         'floor': COPYABLE_NOTIONAL_USD}).result_rows
        return int(rows[0][0]) if rows else None
    except Exception as e:
        logger.error(f"Could not count copyable trades: {e}")
        return None


def _collect_engine_stalls(ch_client) -> list[tuple[str, str]]:
    """Whether orders and fills are still happening, when they should be."""
    problems = []

    def age_minutes(query: str) -> Optional[float]:
        try:
            rows = ch_client.query(query).result_rows
        except Exception as e:
            logger.error(f"Health query failed: {e}")
            return None
        if not rows or rows[0][0] is None:
            return None
        when = rows[0][0]
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - when).total_seconds() / 60

    execution_age = age_minutes(
        "SELECT max(executed_at) FROM polybot.aware_fund_executions")
    fill_age = age_minutes("SELECT max(ts) FROM polybot.user_trades")

    stalled = [
        ('engine:executions', 'No fund order recorded', execution_age),
        ('engine:fills', 'No simulated fill', fill_age),
    ]
    stalled = [(k, m, a) for k, m, a in stalled
               if a is not None and a > STALL_MINUTES]
    if not stalled:
        return problems

    # Only a fault if there was something to act on. Asked once, over the
    # longest stalled window, so a quiet market costs one query.
    window = max(age for _, _, age in stalled)
    copyable = _copyable_trades(ch_client, window)
    if copyable is not None and copyable < MIN_COPYABLE_TO_ALERT:
        logger.info(
            "Funds quiet for %s but only %d copyable trades in that window; "
            "market is idle, not the engine", _fmt_age(window), copyable)
        return problems

    detail = "" if copyable is None else f", {copyable} trades were copyable"
    for key, message, age in stalled:
        problems.append((key, f'{message} for {_fmt_age(age)}{detail}'))
    return problems


def _collect_disk_pressure(ch_client) -> list[tuple[str, str]]:
    """
    Whether the host is running out of disk.

    ClickHouse's data directory sits on the same filesystem as everything
    else here, so system.disks reports the host's own free space and no
    extra plumbing is needed to see it.
    """
    try:
        rows = ch_client.query(
            "SELECT total_space, free_space FROM system.disks "
            "WHERE name = 'default'").result_rows
    except Exception as e:
        logger.error(f"Disk check failed: {e}")
        return []
    if not rows or not rows[0][0]:
        return []

    total, free = int(rows[0][0]), int(rows[0][1])
    used_pct = 100 * (1 - free / total)
    if used_pct < DISK_WARN_PCT:
        return []

    free_gb = free / 1024 ** 3
    return [('host:disk',
             f'Disk {used_pct:.0f}% full, {free_gb:.1f} GB left')]


async def _send(text: str) -> None:
    """
    Push one message to Telegram.

    Telegram only, for now: it is the one channel with a plain-text send.
    Discord's notifier is built around InsiderAlert embeds, and an operational
    failure is not an insider alert.
    """
    try:
        from notifications.telegram import TelegramNotifier
        notifier = TelegramNotifier()
        if not notifier.is_configured:
            logger.info("Operational alert raised but Telegram is not configured")
            return
        await notifier._send_message(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Telegram operational alert failed: {e}")


def check_and_notify(results: dict, ch_client) -> dict:
    """
    Report anything wrong, and report when it stops being wrong.

    Returns a summary so the caller can log what was found.
    """
    problems = (_collect_failed_jobs(results)
                + _collect_engine_stalls(ch_client)
                + _collect_disk_pressure(ch_client))
    current = {key: message for key, message in problems}
    now = datetime.now(timezone.utc)

    # New, or quiet long enough to say again.
    # Keys, not messages. This kept the pair as (key, message) because the
    # bookkeeping below matched a key against a list of messages, which is never
    # true — so the timestamp was written once and never refreshed, and past the
    # repeat interval every cycle reported again. The engine being down produced
    # an hourly message for two days instead of one every six hours.
    due = [
        (key, message) for key, message in current.items()
        if key not in _last_reported or now - _last_reported[key] >= REPEAT_AFTER
    ]
    recovered = [key for key in list(_last_reported) if key not in current]

    for key, _ in due:
        _last_reported[key] = now
    for key in recovered:
        _last_reported.pop(key, None)

    to_report = [message for _, message in due]

    if to_report:
        body = "\n".join(f"• {m}" for m in to_report)
        asyncio.run(_send(f"<b>AWARE — something is wrong</b>\n\n{body}"))
        logger.warning("Operational alert sent: %s", "; ".join(to_report))

    if recovered:
        names = ", ".join(recovered)
        asyncio.run(_send(f"<b>AWARE — recovered</b>\n\nBack to normal: {names}"))
        logger.info("Operational recovery sent: %s", names)

    return {
        'problems': list(current.values()),
        'reported': to_report,
        'recovered': recovered,
    }
