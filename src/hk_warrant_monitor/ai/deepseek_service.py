from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from hk_warrant_monitor.core.enums import SignalAction
from hk_warrant_monitor.core.models import DerivativeProduct, MarketSnapshot, TradeSignal, TrendResult
from hk_warrant_monitor.infra.database import Database, dumps_json


class DeepSeekAnalysisService:
    def __init__(self, settings: dict, db: Database, logger: logging.Logger):
        self.settings = settings.get("ai", {})
        self.db = db
        self.logger = logger

    def maybe_build_message(
        self,
        snapshot: MarketSnapshot,
        trend: TrendResult,
        signal: TradeSignal,
        products: list[DerivativeProduct],
        fallback_message: str,
    ) -> str:
        if not self._should_call(signal, products):
            return fallback_message

        payload = self._build_payload(snapshot, trend, signal, products)
        try:
            content, usage = self._call_deepseek(payload)
            self._record_call(signal, usage, success=True, error="")
            return content.strip() or fallback_message
        except Exception as exc:
            self.logger.warning("DeepSeek analysis failed for %s: %s", signal.underlying_code, exc)
            self._record_call(signal, {}, success=False, error=str(exc)[:500])
            return fallback_message

    def maybe_build_intraday_summary(self, payload: dict[str, Any], fallback_message: str) -> str:
        if not self._should_call_summary():
            return fallback_message
        try:
            content, usage = self._call_deepseek_summary(payload)
            self._record_usage(
                target_code="SYSTEM",
                action="INTRADAY_SUMMARY",
                usage=usage,
                success=True,
                error="",
            )
            return content.strip() or fallback_message
        except Exception as exc:
            self.logger.warning("DeepSeek intraday summary failed: %s", exc)
            self._record_usage(
                target_code="SYSTEM",
                action="INTRADAY_SUMMARY",
                usage={},
                success=False,
                error=str(exc)[:500],
            )
            return fallback_message

    def _should_call(self, signal: TradeSignal, products: list[DerivativeProduct]) -> bool:
        if not self.settings.get("enabled", False):
            return False
        api_key = self.settings.get("api_key", "")
        if not api_key or api_key.startswith("请替换"):
            return False
        if self.settings.get("provider") != "deepseek":
            return False
        if signal.action not in (
            SignalAction.BUY_CALL,
            SignalAction.BUY_PUT,
            SignalAction.TRY_CALL,
            SignalAction.TRY_PUT,
            SignalAction.TAKE_PROFIT,
            SignalAction.STOP_LOSS,
        ):
            return False
        min_confidence = int(self.settings.get("min_confidence", 72))
        if signal.action in (SignalAction.TRY_CALL, SignalAction.TRY_PUT):
            min_confidence = int(self.settings.get("try_min_confidence", 62))
        if signal.confidence < min_confidence:
            return False
        if signal.action in (SignalAction.BUY_CALL, SignalAction.BUY_PUT, SignalAction.TRY_CALL, SignalAction.TRY_PUT) and not products:
            return False
        if self._daily_count() >= int(self.settings.get("daily_limit", 50)):
            return False
        if self._in_cooldown(signal.underlying_code):
            return False
        return True

    def _should_call_summary(self) -> bool:
        if not self.settings.get("enabled", False):
            return False
        api_key = self.settings.get("api_key", "")
        if not api_key or api_key.startswith("请替换"):
            return False
        if self.settings.get("provider") != "deepseek":
            return False
        if self._daily_count() >= int(self.settings.get("daily_limit", 50)):
            return False
        return True

    def _daily_count(self) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) AS count FROM ai_call_record WHERE date(created_at, 'localtime') = date('now', 'localtime') AND success = 1"
        )
        return int(row["count"]) if row else 0

    def _in_cooldown(self, target_code: str) -> bool:
        minutes = int(self.settings.get("cooldown_minutes", 15))
        row = self.db.fetchone(
            "SELECT created_at FROM ai_call_record WHERE target_code = ? AND success = 1 ORDER BY id DESC LIMIT 1",
            (target_code,),
        )
        if row is None:
            return False
        try:
            last = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False
        return datetime.now() - last < timedelta(minutes=minutes)

    def _build_payload(
        self,
        snapshot: MarketSnapshot,
        trend: TrendResult,
        signal: TradeSignal,
        products: list[DerivativeProduct],
    ) -> dict[str, Any]:
        return {
            "style": self.settings.get("style", "TRADER_BRIEF"),
            "underlying": {
                "code": snapshot.code,
                "name": snapshot.name,
                "lastPrice": snapshot.last_price,
                "changeRate": snapshot.change_rate,
                "volume": snapshot.volume,
                "turnover": snapshot.turnover,
                "amplitude": snapshot.amplitude,
                "bidPrice": snapshot.bid_price,
                "askPrice": snapshot.ask_price,
                "bidVolume": snapshot.bid_volume,
                "askVolume": snapshot.ask_volume,
            },
            "trend": {
                "trend": trend.trend.value,
                "score": trend.score,
                "strength": trend.strength.value,
                "scoreBreakdown": trend.details,
            },
            "signal": {
                "action": signal.action.value,
                "confidence": signal.confidence,
                "reason": signal.reason,
                "risk": signal.risk.value,
                "selectedProduct": signal.product_code,
            },
            "candidateProducts": [self._product_payload(product) for product in products[:3]],
            "rules": [
                "不要重新计算技术指标，只解释输入中的结构化结果。",
                "判断依据必须以正股为主，窝轮/牛熊证只是执行工具。",
                "不要承诺收益，不要写成自动交易指令。",
                "输出简洁中文 Markdown。",
            ],
        }

    def _product_payload(self, product: DerivativeProduct) -> dict[str, Any]:
        spread_pct = None
        if product.spread is not None and product.last_price:
            spread_pct = product.spread / product.last_price * 100
        return {
            "code": product.code,
            "name": product.name,
            "type": product.product_type.value,
            "issuer": product.issuer,
            "leverage": product.leverage,
            "strikePrice": product.strike_price,
            "expireDate": product.expire_date,
            "iv": product.iv,
            "streetRatio": product.street_ratio,
            "spreadPct": spread_pct,
            "turnover": product.turnover,
            "lastPrice": product.last_price,
        }

    def _call_deepseek(self, payload: dict[str, Any]) -> tuple[str, dict[str, int]]:
        import requests

        api_key = self.settings["api_key"]
        model = self.settings.get("model", "deepseek-v4-flash")
        messages = [
            {
                "role": "system",
                "content": (
                    "你是港股窝轮/牛熊证交易辅助系统的盘中分析助手。"
                    "你只解读系统已经计算好的信号，不重新计算指标。"
                    "输出必须包含：触发原因、执行工具、操作建议、止损参考、止盈参考、风险提示。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            },
        ]
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 700,
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return content, {
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        }

    def _call_deepseek_summary(self, payload: dict[str, Any]) -> tuple[str, dict[str, int]]:
        import requests

        api_key = self.settings["api_key"]
        model = self.settings.get("model", "deepseek-v4-flash")
        messages = [
            {
                "role": "system",
                "content": (
                    "你是港股窝轮/牛熊证交易辅助系统的盘中值班分析员。"
                    "用户没有收到交易信号时，你需要基于最近半小时结构化数据解释为什么暂未出手，"
                    "给出下一步观察位、可执行方向、风险提示。"
                    "必须强调正股决定方向，窝轮/牛熊证只是执行工具；不要承诺收益。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            },
        ]
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 900,
            },
            timeout=25,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return content, {
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        }

    def _record_call(self, signal: TradeSignal, usage: dict[str, int], success: bool, error: str) -> None:
        self._record_usage(signal.underlying_code, signal.action.value, usage, success, error)

    def _record_usage(
        self,
        target_code: str,
        action: str,
        usage: dict[str, int],
        success: bool,
        error: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO ai_call_record
            (target_code, action, model, prompt_tokens, completion_tokens, total_tokens, success, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_code,
                action,
                self.settings.get("model", ""),
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                usage.get("total_tokens", 0),
                int(success),
                error,
            ),
        )
