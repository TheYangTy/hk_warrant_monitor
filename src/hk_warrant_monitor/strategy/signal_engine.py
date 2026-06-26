from __future__ import annotations

from hk_warrant_monitor.core.enums import Direction, RiskLevel, SignalAction, Trend
from hk_warrant_monitor.core.models import TradeSignal, TrendResult, WatchItem


class SignalEngine:
    def __init__(self, settings: dict):
        self.buy_threshold = int(settings["signals"]["buy_confidence_threshold"])
        strategy = settings.get("strategy", {})
        self.mode = str(strategy.get("mode", "BALANCED")).upper()
        self.try_threshold = int(strategy.get("try_confidence_threshold", self._default_try_threshold()))
        self.watch_threshold = int(strategy.get("watch_confidence_threshold", self._default_watch_threshold()))

    def generate(self, watch_item: WatchItem, trend: TrendResult) -> TradeSignal:
        if trend.trend == Trend.BULLISH and watch_item.direction in (Direction.LONG, Direction.BOTH):
            confidence = trend.score
            action = self._long_action(confidence)
            reason = self._long_reason(action)
            return TradeSignal(action, confidence, reason, watch_item.risk_level, watch_item.code, details=trend.details)

        if trend.trend == Trend.BEARISH and watch_item.direction in (Direction.SHORT, Direction.BOTH):
            confidence = 100 - trend.score
            action = self._short_action(confidence)
            reason = self._short_reason(action)
            return TradeSignal(action, confidence, reason, watch_item.risk_level, watch_item.code, details=trend.details)

        if trend.trend == Trend.NEUTRAL:
            if watch_item.direction in (Direction.LONG, Direction.BOTH) and trend.score >= self.watch_threshold:
                return TradeSignal(
                    SignalAction.WATCH_CALL,
                    trend.score,
                    "正股结构开始偏强，尚未确认买点，建议关注买购/牛证试探条件",
                    watch_item.risk_level,
                    watch_item.code,
                    details=trend.details,
                )
            bearish_confidence = 100 - trend.score
            if watch_item.direction in (Direction.SHORT, Direction.BOTH) and bearish_confidence >= self.watch_threshold:
                return TradeSignal(
                    SignalAction.WATCH_PUT,
                    bearish_confidence,
                    "正股结构开始偏弱，尚未确认买点，建议关注买沽/熊证试探条件",
                    watch_item.risk_level,
                    watch_item.code,
                    details=trend.details,
                )

        return TradeSignal(
            SignalAction.HOLD,
            abs(trend.score - 50),
            "正股方向与用户偏好不匹配或趋势不明确，继续观察",
            RiskLevel.MEDIUM if watch_item.risk_level == RiskLevel.HIGH else watch_item.risk_level,
            watch_item.code,
            details=trend.details,
        )

    def _default_try_threshold(self) -> int:
        return 66 if self.mode == "CONSERVATIVE" else 58 if self.mode == "AGGRESSIVE" else 62

    def _default_watch_threshold(self) -> int:
        return 60 if self.mode == "CONSERVATIVE" else 52 if self.mode == "AGGRESSIVE" else 55

    def _long_action(self, confidence: int) -> SignalAction:
        if confidence >= self.buy_threshold:
            return SignalAction.BUY_CALL
        if confidence >= self.try_threshold:
            return SignalAction.TRY_CALL
        if confidence >= self.watch_threshold:
            return SignalAction.WATCH_CALL
        return SignalAction.HOLD

    def _short_action(self, confidence: int) -> SignalAction:
        if confidence >= self.buy_threshold:
            return SignalAction.BUY_PUT
        if confidence >= self.try_threshold:
            return SignalAction.TRY_PUT
        if confidence >= self.watch_threshold:
            return SignalAction.WATCH_PUT
        return SignalAction.HOLD

    def _long_reason(self, action: SignalAction) -> str:
        return {
            SignalAction.BUY_CALL: "正股趋势转强，适合用认购证或牛证表达方向",
            SignalAction.TRY_CALL: "正股趋势偏强，适合小仓试探买购/牛证机会，等待突破确认后再加大仓位",
            SignalAction.WATCH_CALL: "正股结构开始偏强，建议关注买购/牛证机会，等待量价或盘口进一步确认",
            SignalAction.HOLD: "正股趋势偏强但置信度不足",
        }[action]

    def _short_reason(self, action: SignalAction) -> str:
        return {
            SignalAction.BUY_PUT: "正股趋势转弱，适合用认沽证或熊证表达方向",
            SignalAction.TRY_PUT: "正股趋势偏弱，适合小仓试探买沽/熊证机会，等待破位确认后再加大仓位",
            SignalAction.WATCH_PUT: "正股结构开始偏弱，建议关注买沽/熊证机会，等待量价或盘口进一步确认",
            SignalAction.HOLD: "正股趋势偏弱但置信度不足",
        }[action]
