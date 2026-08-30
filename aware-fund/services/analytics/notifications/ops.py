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


def _collect_engine_stalls(ch_client) -> list[tuple[str, str]]:
    """Whether orders and fills are still happening."""
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

    if execution_age is not None and execution_age > STALL_MINUTES:
        problems.append((
            'engine:executions',
            f'No fund order recorded for {_fmt_age(execution_age)}',
        ))
    if fill_age is not None and fill_age > STALL_MINUTES:
        problems.append((
            'engine:fills',
            f'No simulated fill for {_fmt_age(fill_age)}',
        ))
    return problems


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
    problems = _collect_failed_jobs(results) + _collect_engine_stalls(ch_client)
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
