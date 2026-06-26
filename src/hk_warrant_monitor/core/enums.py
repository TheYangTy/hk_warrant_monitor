from enum import StrEnum


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    BOTH = "BOTH"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ProductType(StrEnum):
    CALL_WARRANT = "CALL_WARRANT"
    PUT_WARRANT = "PUT_WARRANT"
    BULL_CBBC = "BULL_CBBC"
    BEAR_CBBC = "BEAR_CBBC"
    UNKNOWN = "UNKNOWN"


class Trend(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Strength(StrEnum):
    WEAK = "WEAK"
    MEDIUM = "MEDIUM"
    STRONG = "STRONG"


class SignalAction(StrEnum):
    WATCH_CALL = "WATCH_CALL"
    WATCH_PUT = "WATCH_PUT"
    TRY_CALL = "TRY_CALL"
    TRY_PUT = "TRY_PUT"
    BUY_CALL = "BUY_CALL"
    BUY_PUT = "BUY_PUT"
    HOLD = "HOLD"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    ADD_POSITION = "ADD_POSITION"


class PushLevel(StrEnum):
    INFO = "INFO"
    IMPORTANT = "IMPORTANT"
    URGENT = "URGENT"
