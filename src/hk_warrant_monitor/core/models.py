from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from hk_warrant_monitor.core.enums import Direction, ProductType, RiskLevel, SignalAction, Strength, Trend


@dataclass(frozen=True)
class WatchItem:
    code: str
    name: str
    direction: Direction
    risk_level: RiskLevel
    allow_overnight: bool
    enable: bool = True


@dataclass(frozen=True)
class MarketSnapshot:
    code: str
    name: str = ""
    last_price: float = 0.0
    change_rate: float = 0.0
    volume: float = 0.0
    turnover: float = 0.0
    amplitude: float = 0.0
    turnover_rate: float = 0.0
    bid_price: float = 0.0
    ask_price: float = 0.0
    bid_volume: float = 0.0
    ask_volume: float = 0.0
    snapshot_time: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class IndicatorSnapshot:
    code: str
    ktype: str
    ma5: float | None
    ma10: float | None
    ma20: float | None
    ma60: float | None
    vwap: float | None
    rsi: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    boll_mid: float | None
    boll_upper: float | None
    boll_lower: float | None
    calculated_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class DerivativeProduct:
    underlying_code: str
    code: str
    name: str
    product_type: ProductType
    issuer: str = ""
    leverage: float | None = None
    strike_price: float | None = None
    expire_date: str | None = None
    iv: float | None = None
    street_ratio: float | None = None
    spread: float | None = None
    volume: float | None = None
    turnover: float | None = None
    last_price: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TrendResult:
    trend: Trend
    score: int
    strength: Strength
    details: dict[str, Any]


@dataclass(frozen=True)
class TradeSignal:
    action: SignalAction
    confidence: int
    reason: str
    risk: RiskLevel
    underlying_code: str
    product_code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Position:
    product_code: str
    buy_price: float
    quantity: int
    buy_time: str
    status: str = "OPEN"
    id: int | None = None


@dataclass(frozen=True)
class PositionAnalysis:
    position: Position
    current_price: float
    pnl_amount: float
    pnl_ratio: float
    drawdown: float
    risk_level: RiskLevel
    action: SignalAction
    reason: str
