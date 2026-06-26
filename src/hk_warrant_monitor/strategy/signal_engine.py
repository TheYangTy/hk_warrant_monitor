from __future__ import annotations

from hk_warrant_monitor.core.enums import Direction, RiskLevel, SignalAction, Trend
from hk_warrant_monitor.core.models import TradeSignal, TrendResult, WatchItem


class SignalEngine:
    def __init__(self, settings: dict):
        self.threshold = int(settings["signals"]["buy_confidence_threshold"])

    def generate(self, watch_item: WatchItem, trend: TrendResult) -> TradeSignal:
        if trend.trend == Trend.BULLISH and watch_item.direction in (Direction.LONG, Direction.BOTH):
            confidence = trend.score
            action = SignalAction.BUY_CALL if confidence >= self.threshold else SignalAction.HOLD
            reason = "正股趋势转强，适合用认购证或牛证表达方向" if action == SignalAction.BUY_CALL else "正股趋势偏强但置信度不足"
            return TradeSignal(action, confidence, reason, watch_item.risk_level, watch_item.code, details=trend.details)

        if trend.trend == Trend.BEARISH and watch_item.direction in (Direction.SHORT, Direction.BOTH):
            confidence = 100 - trend.score
            action = SignalAction.BUY_PUT if confidence >= self.threshold else SignalAction.HOLD
            reason = "正股趋势转弱，适合用认沽证或熊证表达方向" if action == SignalAction.BUY_PUT else "正股趋势偏弱但置信度不足"
            return TradeSignal(action, confidence, reason, watch_item.risk_level, watch_item.code, details=trend.details)

        return TradeSignal(
            SignalAction.HOLD,
            abs(trend.score - 50),
            "正股方向与用户偏好不匹配或趋势不明确，继续观察",
            RiskLevel.MEDIUM if watch_item.risk_level == RiskLevel.HIGH else watch_item.risk_level,
            watch_item.code,
            details=trend.details,
        )

