"""Hourly proactive alert checker.

Loads all active AlertRule rows, fetches the most-recent metric value for
each, evaluates the threshold condition, and fires a Discord DM if the
condition is met and the cooldown window has elapsed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.functions.data_freshness import get_data_freshness
from lattice.integrations.discord_dm import send_dm
from lattice.models.alert import AlertEvent, AlertRule

logger = logging.getLogger(__name__)

# P3-3: the Garmin-staleness watchdog reuses the AlertEvent log for its
# cooldown, but it isn't backed by a user-editable AlertRule row. A reserved
# negative sentinel rule_id keeps its events out of real rules' cooldown
# windows while still recording when we last warned.
_STALE_WATCHDOG_RULE_ID = -1
# Only DM once per day for a persistent staleness condition.
_STALE_COOLDOWN_HOURS = 24
# Staleness severity that warrants a DM (matches data_freshness statuses where
# a whole night / >36h of data is missing — auth breakage or unsynced watch).
_STALE_ALERTING_STATUSES = frozenset({"stale_today", "stale_severe"})

_OPS = {
    "lt": lambda v, t: v < t,
    "lte": lambda v, t: v <= t,
    "gt": lambda v, t: v > t,
    "gte": lambda v, t: v >= t,
}
_OP_SYMBOLS = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥"}


async def run_alert_check(session: AsyncSession) -> int:
    """Evaluate all active rules. Returns the number of alerts fired."""
    zone = ZoneInfo(settings.timezone)
    now = datetime.now(zone)
    now_iso = now.isoformat()
    fired = 0

    rules_result = await session.execute(
        select(AlertRule).where(AlertRule.active.is_(True))
    )
    rules = rules_result.scalars().all()

    for rule in rules:
        try:
            fired += await _check_rule(session, rule, now, now_iso)
        except Exception:  # noqa: BLE001
            logger.exception("alert check failed for rule %d (%s)", rule.id, rule.label)

    try:
        fired += await _check_staleness_watchdog(session, now, now_iso)
    except Exception:  # noqa: BLE001
        logger.exception("staleness watchdog failed")

    return fired


async def _check_staleness_watchdog(
    session: AsyncSession,
    now: datetime,
    now_iso: str,
) -> int:
    """Default watchdog (P3-3): DM when Garmin data is meaningfully stale.

    Fires when `data_freshness` reports `stale_today` or `stale_severe`
    (≥1 missing night / >36h with no data — i.e. the watch hasn't synced or
    Garmin auth is broken). Rate-limited to once per `_STALE_COOLDOWN_HOURS`
    via a sentinel-rule AlertEvent so a persistent outage doesn't spam DMs.
    """
    freshness = await get_data_freshness(session)
    status = freshness.get("status")
    if status not in _STALE_ALERTING_STATUSES:
        return 0

    cutoff = (now - timedelta(hours=_STALE_COOLDOWN_HOURS)).isoformat()
    recent = await session.execute(
        select(AlertEvent).where(
            AlertEvent.rule_id == _STALE_WATCHDOG_RULE_ID,
            AlertEvent.fired_at >= cutoff,
        ).limit(1),
    )
    if recent.first() is not None:
        return 0

    hours = freshness.get("hours_since_latest_metric")
    msg = (
        "⚠ **Lattice alert** — Garmin data is stale\n"
        f"{freshness.get('advisory', 'No fresh Garmin data.')}"
    )
    await send_dm(msg)

    session.add(
        AlertEvent(
            rule_id=_STALE_WATCHDOG_RULE_ID,
            fired_at=now_iso,
            value=float(hours) if isinstance(hours, (int, float)) else 0.0,
        ),
    )
    await session.commit()
    logger.info("staleness watchdog fired: status=%s", status)
    return 1


async def _check_rule(
    session: AsyncSession,
    rule: AlertRule,
    now: datetime,
    now_iso: str,
) -> int:
    # Fetch latest metric value
    row = await session.execute(
        text(
            "SELECT value FROM metrics WHERE metric_name = :name "
            "ORDER BY timestamp DESC LIMIT 1"
        ),
        {"name": rule.metric_name},
    )
    result = row.first()
    if result is None:
        return 0

    value: float = result[0]
    op_fn = _OPS.get(rule.operator)
    if op_fn is None or not op_fn(value, rule.threshold):
        return 0

    # Cooldown check: was this rule already fired within cooldown_hours?
    cutoff = (now - timedelta(hours=rule.cooldown_hours)).isoformat()
    recent = await session.execute(
        select(AlertEvent).where(
            AlertEvent.rule_id == rule.id,
            AlertEvent.fired_at >= cutoff,
        ).limit(1)
    )
    if recent.first() is not None:
        return 0

    # Fire the alert
    op_sym = _OP_SYMBOLS.get(rule.operator, rule.operator)
    msg = (
        f"⚠ **Lattice alert** — {rule.label}\n"
        f"{rule.metric_name} {op_sym} {rule.threshold} "
        f"(current: {value:.1f})"
    )
    await send_dm(msg)

    event = AlertEvent(rule_id=rule.id, fired_at=now_iso, value=value)
    session.add(event)
    await session.commit()
    logger.info("alert fired: rule %d (%s) value=%.2f", rule.id, rule.label, value)
    return 1
