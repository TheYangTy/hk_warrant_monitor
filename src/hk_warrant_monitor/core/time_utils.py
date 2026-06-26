from datetime import datetime, time


def parse_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M:%S").time()


def is_hk_trading_time(settings: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    market = settings["market"]
    current = now.time()
    start = parse_time(market["trading_start"])
    end = parse_time(market["trading_end"])
    break_start = parse_time(market["midday_break_start"])
    break_end = parse_time(market["midday_break_end"])
    return start <= current <= end and not (break_start <= current < break_end)

