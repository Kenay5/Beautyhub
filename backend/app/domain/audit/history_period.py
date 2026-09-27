"""Official local-date boundaries for administrative-history filters."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


ADMINISTRATIVE_HISTORY_TIMEZONE = ZoneInfo("America/Mexico_City")


def history_period_utc_bounds(
    *, start_date: date | None, end_date: date | None
) -> tuple[datetime | None, datetime | None]:
    """Map inclusive local calendar dates to a half-open UTC interval."""

    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("history period start must not follow its end")

    start = (
        datetime.combine(start_date, time.min, ADMINISTRATIVE_HISTORY_TIMEZONE)
        .astimezone(timezone.utc)
        if start_date is not None
        else None
    )
    if end_date is not None:
        try:
            day_after_end = end_date + timedelta(days=1)
        except OverflowError as error:
            raise ValueError("history period end date is out of range") from error
        end = datetime.combine(
            day_after_end, time.min, ADMINISTRATIVE_HISTORY_TIMEZONE
        ).astimezone(timezone.utc)
    else:
        end = None
    return start, end
