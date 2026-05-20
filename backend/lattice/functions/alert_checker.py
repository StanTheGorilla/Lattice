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
from lattice.integrations.discord_dm import send_dm
from lattice.models.alert import AlertEvent, AlertRule

logger = logging.getLogger(__name__)

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

    return fired


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
