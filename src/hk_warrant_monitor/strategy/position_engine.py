from __future__ import annotations

from hk_warrant_monitor.core.enums import RiskLevel, SignalAction
from hk_warrant_monitor.core.models import Position, PositionAnalysis


class PositionEngine:
    def __init__(self, settings: dict):
        signals = settings["signals"]
        self.take_profit_pct = float(signals["take_profit_pct"])
        self.stop_loss_pct = float(signals["stop_loss_pct"])

    def analyze(self, position: Position, current_price: float, high_watermark_price: float | None = None) -> PositionAnalysis:
        pnl_amount = (current_price - position.buy_price) * position.quantity
        pnl_ratio = ((current_price - position.buy_price) / position.buy_price * 100) if position.buy_price else 0.0
        high = high_watermark_price if high_watermark_price is not None else max(current_price, position.buy_price)
        drawdown = ((current_price - high) / high * 100) if high else 0.0

        if pnl_ratio <= self.stop_loss_pct:
            action = SignalAction.STOP_LOSS
            risk = RiskLevel.HIGH
            reason = f"持仓亏损 {pnl_ratio:.1f}%，触发预设止损线 {self.stop_loss_pct:.1f}%"
        elif pnl_ratio >= self.take_profit_pct:
            action = SignalAction.TAKE_PROFIT
            risk = RiskLevel.MEDIUM
            reason = f"持仓盈利 {pnl_ratio:.1f}%，达到预设止盈线 {self.take_profit_pct:.1f}%"
        else:
            action = SignalAction.HOLD
            risk = RiskLevel.LOW if pnl_ratio >= 0 else RiskLevel.MEDIUM
            reason = f"持仓盈亏 {pnl_ratio:.1f}%，未触发止盈止损"

        return PositionAnalysis(
            position=position,
            current_price=current_price,
            pnl_amount=pnl_amount,
            pnl_ratio=pnl_ratio,
            drawdown=drawdown,
            risk_level=risk,
            action=action,
            reason=reason,
        )

