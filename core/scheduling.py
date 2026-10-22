"""Small, explicit schedule vocabulary. All persisted deadlines are UTC epochs."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from core.settings import AGENTS


def validate_schedule(spec):
    spec = dict(spec)
    if spec.get("agent") not in AGENTS:
        raise ValueError("Choose one of the seven agents.")
    objective = str(spec.get("objective", "")).strip()
    if not 1 <= len(objective) <= 2000:
        raise ValueError("A schedule needs an objective of 1–2,000 characters.")
    spec["objective"] = objective
    spec["title"] = str(spec.get("title") or objective)[:100]
    try:
        ZoneInfo(spec.get("timezone", "Europe/London"))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError("Use a valid IANA timezone, such as Europe/London.") from None
    spec.setdefault("timezone", "Europe/London")
    if spec.get("kind") not in ("once", "interval", "daily", "weekly"):
        raise ValueError("Choose once, interval, daily or weekly.")
    if spec["kind"] == "interval":
        minutes = int(spec.get("interval_minutes") or 0)
        if not 1 <= minutes <= 10080:
            raise ValueError("Recurring intervals must be 1–10,080 minutes.")
        spec["interval_minutes"] = minutes
    if spec["kind"] == "weekly":
        day = int(spec.get("weekday", -1))
        if not 0 <= day <= 6:
            raise ValueError("Select a weekday (Monday=0).")
        spec["weekday"] = day
    return spec


def local_instant(naive, tz):
    # Spring-forward gaps move to the first valid local minute. Fall-back uses
    # the first occurrence so a daily schedule never fires twice that day.
    for _ in range(181):
        aware = naive.replace(tzinfo=tz, fold=0)
        if aware.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == naive:
            return aware.timestamp()
        naive += timedelta(minutes=1)
    raise ValueError("That local time cannot be scheduled.")


def next_after(spec, after):
    tz = ZoneInfo(spec["timezone"])
    kind = spec["kind"]
    if kind == "interval":
        return after + spec["interval_minutes"] * 60
    if kind == "once":
        try:
            naive = datetime.fromisoformat(spec.get("when_local", ""))
        except ValueError:
            raise ValueError("Enter the one-off local date and time.") from None
        if naive.tzinfo:
            raise ValueError("Supply local time without an offset; choose the timezone separately.")
        result = local_instant(naive, tz)
        if result <= after:
            raise ValueError("The one-off time must be in the future.")
        return result
    try:
        hour, minute = map(int, str(spec.get("time_local", "09:00")).split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("Use a local time in HH:MM format.") from None
    today = datetime.fromtimestamp(after, tz).date()
    for offset in range(9):
        day = today + timedelta(days=offset)
        if kind == "weekly" and day.weekday() != spec["weekday"]:
            continue
        candidate = local_instant(datetime(day.year, day.month, day.day, hour, minute), tz)
        if candidate > after:
            return candidate
    raise ValueError("Cannot calculate the next run.")
