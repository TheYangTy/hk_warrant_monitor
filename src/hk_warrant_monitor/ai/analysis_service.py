from __future__ import annotations

from hk_warrant_monitor.core.enums import SignalAction
from hk_warrant_monitor.core.models import DerivativeProduct, MarketSnapshot, TradeSignal, TrendResult


class AnalysisService:
    def build_message(
        self,
        snapshot: MarketSnapshot,
        trend: TrendResult,
        signal: TradeSignal,
        products: list[DerivativeProduct],
    ) -> str:
        product_lines = []
        for product in products[:3]:
            product_lines.append(
                f"- {product.name or product.code} ({product.code}) "
                f"杠杆:{self._fmt(product.leverage)} 成交额:{self._fmt(product.turnover)} "
                f"街货:{self._fmt(product.street_ratio)} 到期:{product.expire_date or '未知'}"
            )
        product_text = "\n".join(product_lines) if product_lines else "- 暂无符合流动性和风险条件的窝轮/牛熊证"
        score_text = self._score_breakdown(trend)
        action_text = self._action_text(signal.action)
        return (
            f"**{snapshot.name or snapshot.code} ({snapshot.code}) 交易辅助提醒**\n"
            f"正股最新价: {snapshot.last_price:.3f}，涨跌幅: {snapshot.change_rate:.2f}%\n"
            f"趋势: {trend.trend.value}，评分: {trend.score}，强度: {trend.strength.value}\n"
            f"评分拆解: {score_text}\n"
            f"建议: {action_text}，置信度: {signal.confidence}\n"
            f"理由: {signal.reason}\n"
            f"风险等级: {signal.risk.value}\n"
            f"\n候选执行工具:\n{product_text}\n"
            f"\n说明: 本信号以正股走势为判断依据，窝轮/牛熊证仅作为执行工具筛选，不构成自动交易。"
        )

    def _action_text(self, action: SignalAction) -> str:
        return {
            SignalAction.WATCH_CALL: "观察买购/牛证机会",
            SignalAction.WATCH_PUT: "观察买沽/熊证机会",
            SignalAction.TRY_CALL: "小仓试探买购/牛证机会",
            SignalAction.TRY_PUT: "小仓试探买沽/熊证机会",
            SignalAction.BUY_CALL: "关注买购/牛证机会",
            SignalAction.BUY_PUT: "关注买沽/熊证机会",
            SignalAction.HOLD: "继续观察",
            SignalAction.TAKE_PROFIT: "止盈",
            SignalAction.STOP_LOSS: "止损",
            SignalAction.ADD_POSITION: "加仓",
        }[action]

    def _score_breakdown(self, trend: TrendResult) -> str:
        labels = {
            "ma_score": "均线",
            "momentum_score": "动量",
            "index_score": "指数",
            "price_score": "涨跌",
            "volume_score": "成交量",
            "vwap_score": "VWAP",
            "orderbook_score": "盘口",
            "breakout_score": "突破",
            "intraday_strength_score": "盘中强度",
            "volatility_score": "波动",
            "chase_penalty": "追高惩罚",
        }
        parts = []
        for key, label in labels.items():
            value = trend.details.get(key)
            if isinstance(value, (int, float)) and value:
                parts.append(f"{label}{value:+g}")
        return "，".join(parts) if parts else "暂无明显加减分项"

    def _fmt(self, value: float | None) -> str:
        if value is None:
            return "未知"
        if abs(value) >= 10000:
            return f"{value / 10000:.1f}万"
        return f"{value:.2f}"
