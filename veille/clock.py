from datetime import datetime, timedelta, timezone


def _last_sunday_at_one_utc(year, month):
    month_end = datetime(year, month, 31, 1, tzinfo=timezone.utc)
    days_since_sunday = (month_end.weekday() + 1) % 7
    return month_end - timedelta(days=days_since_sunday)


def paris_now():
    utc_now = datetime.now(timezone.utc).replace(microsecond=0)
    summer_time_starts = _last_sunday_at_one_utc(utc_now.year, 3)
    summer_time_ends = _last_sunday_at_one_utc(utc_now.year, 10)
    offset_hours = 2 if summer_time_starts <= utc_now < summer_time_ends else 1
    return (utc_now + timedelta(hours=offset_hours)).replace(tzinfo=None)
