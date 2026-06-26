from __future__ import annotations

import logging
from datetime import datetime, time

import pandas as pd

from hk_warrant_monitor.ai.analysis_service import AnalysisService
from hk_warrant_monitor.ai.deepseek_service import DeepSeekAnalysisService
from hk_warrant_monitor.core.enums import PushLevel, SignalAction
from hk_warrant_monitor.core.models import DerivativeProduct, IndicatorSnapshot, MarketSnapshot, TradeSignal
from hk_warrant_monitor.data_sources.futu_client import FutuQuoteClient
from hk_warrant_monitor.indicators.calculator import IndicatorCalculator
from hk_warrant_monitor.infra.database import Database, dumps_json
from hk_warrant_monitor.notifications.push_service import PushService
from hk_warrant_monitor.products.filter import ProductFilter
from hk_warrant_monitor.strategy.signal_engine import SignalEngine
from hk_warrant_monitor.strategy.trend_engine import TrendEngine
from hk_warrant_monitor.watchlist.service import WatchlistService


class IntradayScanJob:
    def __init__(
        self,
        settings: dict,
        db: Database,
        futu: FutuQuoteClient,
        watchlist: WatchlistService,
        push_service: PushService,
        logger: logging.Logger,
    ):
        self.settings = settings
        self.db = db
        self.futu = futu
        self.watchlist = watchlist
        self.push_service = push_service
        self.logger = logger
        self.indicators = IndicatorCalculator()
        self.trend_engine = TrendEngine(settings)
        self.signal_engine = SignalEngine(settings)
        self.product_filter = ProductFilter(settings)
        self.analysis = AnalysisService()
        self.ai_analysis = DeepSeekAnalysisService(settings, db, logger)

    def run_once(self) -> list[TradeSignal]:
        self._set_runtime_state("last_scan_started_at", datetime.now().isoformat(timespec="seconds"))
        try:
            watch_items = self.watchlist.list(enabled_only=True)
            if not watch_items:
                self.logger.info("Watchlist is empty. Add symbols with `watchlist add` first.")
                self._set_runtime_state("last_scan_status", "ok: empty_watchlist")
                return []

            signals: list[TradeSignal] = []
            codes = [item.code for item in watch_items]
            snapshots = {snapshot.code: snapshot for snapshot in self.futu.get_market_snapshots(codes)}
            index_snapshots = self._load_index_snapshots()

            for item in watch_items:
                snapshot = snapshots.get(item.code)
                if snapshot is None:
                    self.logger.warning("Missing snapshot for %s", item.code)
                    continue
                self._save_snapshot(snapshot)

                indicator_map, kline_frames = self._load_market_analysis(item.code)
                trend = self.trend_engine.analyze(snapshot, indicator_map, index_snapshots, kline_frames)
                signal = self.signal_engine.generate(item, trend)
                products = self._select_products(snapshot, signal)
                signal = self._downgrade_if_no_execution_tool(signal, products)
                signal = self._attach_product(signal, products)
                self._save_signal(signal)

                if self._should_push_signal(signal):
                    fallback_message = self.analysis.build_message(snapshot, trend, signal, products)
                    message = self.ai_analysis.maybe_build_message(snapshot, trend, signal, products, fallback_message)
                    pushed = self.push_service.push(
                        self._push_level_for_signal(signal),
                        "trade_signal",
                        item.code,
                        f"{snapshot.name or item.name or item.code} {signal.action.value}",
                        message,
                    )
                    if pushed:
                        self._mark_signal_pushed(signal)
                signals.append(signal)
            self._maybe_push_quiet_intraday_summary(watch_items)
            self._set_runtime_state("last_scan_status", f"ok: signals={len(signals)}")
            return signals
        except Exception as exc:
            self._set_runtime_state("last_scan_status", f"error: {exc}")
            raise
        finally:
            self._set_runtime_state("last_scan_finished_at", datetime.now().isoformat(timespec="seconds"))

    def enabled_watch_items(self):
        return self.watchlist.list(enabled_only=True)

    def _downgrade_if_no_execution_tool(
        self,
        signal: TradeSignal,
        products: list[DerivativeProduct],
    ) -> TradeSignal:
        if signal.action not in (SignalAction.BUY_CALL, SignalAction.BUY_PUT, SignalAction.TRY_CALL, SignalAction.TRY_PUT):
            return signal
        if products:
            return signal
        if signal.action == SignalAction.TRY_CALL:
            return TradeSignal(
                action=SignalAction.WATCH_CALL,
                confidence=signal.confidence,
                reason=f"{signal.reason}，但暂无符合流动性和风险条件的窝轮/牛熊证执行工具，先列为观察",
                risk=signal.risk,
                underlying_code=signal.underlying_code,
                product_code=None,
                details={**signal.details, "blocked_reason": "no_qualified_execution_product"},
            )
        if signal.action == SignalAction.TRY_PUT:
            return TradeSignal(
                action=SignalAction.WATCH_PUT,
                confidence=signal.confidence,
                reason=f"{signal.reason}，但暂无符合流动性和风险条件的窝轮/牛熊证执行工具，先列为观察",
                risk=signal.risk,
                underlying_code=signal.underlying_code,
                product_code=None,
                details={**signal.details, "blocked_reason": "no_qualified_execution_product"},
            )
        return TradeSignal(
            action=SignalAction.HOLD,
            confidence=signal.confidence,
            reason=f"{signal.reason}，但暂无符合流动性和风险条件的窝轮/牛熊证执行工具，暂不发出买入建议",
            risk=signal.risk,
            underlying_code=signal.underlying_code,
            product_code=None,
            details={**signal.details, "blocked_reason": "no_qualified_execution_product"},
        )

    def _load_index_snapshots(self) -> dict[str, MarketSnapshot]:
        index_codes = list(self.settings.get("scan", {}).get("index_codes", {}).values())
        if not index_codes:
            return {}
        try:
            return {s.code: s for s in self.futu.get_market_snapshots(index_codes)}
        except Exception as exc:
            self.logger.warning("Index snapshot loading failed: %s", exc)
            return {}

    def _load_market_analysis(self, code: str) -> tuple[dict[str, IndicatorSnapshot], dict[str, pd.DataFrame]]:
        indicators = {}
        frames = {}
        scan = self.settings["scan"]
        for ktype in scan["kline_types"]:
            try:
                kline = self.futu.get_kline(code, ktype, int(scan["kline_count"]))
                frames[ktype] = kline
                indicator = self.indicators.calculate(code, ktype, kline)
                indicators[ktype] = indicator
                self._save_indicator(indicator)
            except Exception as exc:
                self.logger.warning("Indicator loading failed for %s %s: %s", code, ktype, exc)
        return indicators, frames

    def _select_products(self, snapshot: MarketSnapshot, signal: TradeSignal) -> list[DerivativeProduct]:
        if signal.action not in (
            SignalAction.BUY_CALL,
            SignalAction.BUY_PUT,
            SignalAction.TRY_CALL,
            SignalAction.TRY_PUT,
            SignalAction.WATCH_CALL,
            SignalAction.WATCH_PUT,
        ):
            return []
        products = self.futu.discover_related_products(snapshot.code)
        for product in products:
            self._save_product(product)
        return self.product_filter.rank_for_signal(products, signal.action, snapshot)

    def _attach_product(self, signal: TradeSignal, products: list[DerivativeProduct]) -> TradeSignal:
        if not products:
            return signal
        top = products[0]
        return TradeSignal(
            action=signal.action,
            confidence=signal.confidence,
            reason=signal.reason,
            risk=signal.risk,
            underlying_code=signal.underlying_code,
            product_code=top.code,
            details={**signal.details, "selected_product": top.code},
        )

    def _save_snapshot(self, snapshot: MarketSnapshot) -> None:
        self.db.execute(
            """
            INSERT INTO market_snapshot
            (code, name, last_price, change_rate, volume, turnover, amplitude, turnover_rate,
             bid_price, ask_price, bid_volume, ask_volume, snapshot_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.code,
                snapshot.name,
                snapshot.last_price,
                snapshot.change_rate,
                snapshot.volume,
                snapshot.turnover,
                snapshot.amplitude,
                snapshot.turnover_rate,
                snapshot.bid_price,
                snapshot.ask_price,
                snapshot.bid_volume,
                snapshot.ask_volume,
                snapshot.snapshot_time.isoformat(),
            ),
        )

    def _save_indicator(self, indicator: IndicatorSnapshot) -> None:
        self.db.execute(
            """
            INSERT INTO indicator_snapshot
            (code, ktype, ma5, ma10, ma20, ma60, vwap, rsi, macd, macd_signal,
             macd_hist, boll_mid, boll_upper, boll_lower, calculated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                indicator.code,
                indicator.ktype,
                indicator.ma5,
                indicator.ma10,
                indicator.ma20,
                indicator.ma60,
                indicator.vwap,
                indicator.rsi,
                indicator.macd,
                indicator.macd_signal,
                indicator.macd_hist,
                indicator.boll_mid,
                indicator.boll_upper,
                indicator.boll_lower,
                indicator.calculated_at.isoformat(),
            ),
        )

    def _save_product(self, product: DerivativeProduct) -> None:
        self.db.execute(
            """
            INSERT INTO derivative_product
            (underlying_code, product_code, name, product_type, issuer, leverage, strike_price,
             expire_date, iv, street_ratio, spread, volume, turnover, last_price, extra_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_code) DO UPDATE SET
              name=excluded.name,
              product_type=excluded.product_type,
              issuer=excluded.issuer,
              leverage=excluded.leverage,
              strike_price=excluded.strike_price,
              expire_date=excluded.expire_date,
              iv=excluded.iv,
              street_ratio=excluded.street_ratio,
              spread=excluded.spread,
              volume=excluded.volume,
              turnover=excluded.turnover,
              last_price=excluded.last_price,
              extra_json=excluded.extra_json,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                product.underlying_code,
                product.code,
                product.name,
                product.product_type.value,
                product.issuer,
                product.leverage,
                product.strike_price,
                product.expire_date,
                product.iv,
                product.street_ratio,
                product.spread,
                product.volume,
                product.turnover,
                product.last_price,
                dumps_json(product.extra),
            ),
        )

    def _save_signal(self, signal: TradeSignal) -> None:
        self.db.execute(
            """
            INSERT INTO trade_signal
            (underlying_code, product_code, action, confidence, reason, risk, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.underlying_code,
                signal.product_code,
                signal.action.value,
                signal.confidence,
                signal.reason,
                signal.risk.value,
                dumps_json(signal.details),
            ),
        )

    def _should_push_signal(self, signal: TradeSignal) -> bool:
        if signal.action == SignalAction.HOLD:
            return False
        return not self._signal_in_cooldown(signal)

    def _push_level_for_signal(self, signal: TradeSignal) -> PushLevel:
        if signal.action in (SignalAction.STOP_LOSS,):
            return PushLevel.URGENT
        if signal.action in (
            SignalAction.BUY_CALL,
            SignalAction.BUY_PUT,
            SignalAction.TRY_CALL,
            SignalAction.TRY_PUT,
            SignalAction.TAKE_PROFIT,
            SignalAction.ADD_POSITION,
        ):
            return PushLevel.IMPORTANT
        return PushLevel.INFO

    def _signal_in_cooldown(self, signal: TradeSignal) -> bool:
        minutes = self._cooldown_minutes_for_signal(signal.action)
        if minutes <= 0:
            return False
        key = self._signal_push_state_key(signal)
        row = self.db.fetchone("SELECT value FROM runtime_state WHERE key = ?", (key,))
        if row is None or not row["value"]:
            return False
        try:
            last = datetime.fromisoformat(row["value"])
        except ValueError:
            return False
        return (datetime.now() - last).total_seconds() < minutes * 60

    def _mark_signal_pushed(self, signal: TradeSignal) -> None:
        self._set_runtime_state(self._signal_push_state_key(signal), datetime.now().isoformat(timespec="seconds"))

    def _signal_push_state_key(self, signal: TradeSignal) -> str:
        safe_code = signal.underlying_code.replace(".", "_")
        return f"last_push_{safe_code}_{signal.action.value}"

    def _cooldown_minutes_for_signal(self, action: SignalAction) -> int:
        strategy = self.settings.get("strategy", {})
        if action in (SignalAction.WATCH_CALL, SignalAction.WATCH_PUT):
            return int(strategy.get("watch_push_cooldown_minutes", 15))
        if action in (SignalAction.TRY_CALL, SignalAction.TRY_PUT):
            return int(strategy.get("try_push_cooldown_minutes", 10))
        return int(strategy.get("buy_push_cooldown_minutes", 15))

    def _set_runtime_state(self, key: str, value: str) -> None:
        try:
            self.db.set_state(key, value)
        except Exception as exc:
            self.logger.warning("Runtime state update failed: %s", exc)

    def _maybe_push_quiet_intraday_summary(self, watch_items) -> None:
        summary_settings = self.settings.get("summary", {})
        if not summary_settings.get("enabled", True):
            return
        if not self._is_trading_time():
            return

        quiet_minutes = int(summary_settings.get("quiet_minutes", 30))
        if self._recent_summary_related_push_count(quiet_minutes) > 0:
            return

        lookback_minutes = int(summary_settings.get("lookback_minutes", quiet_minutes))
        payload = self._build_intraday_summary_payload(watch_items, lookback_minutes)
        if not payload["underlyings"]:
            return

        fallback = self._build_intraday_summary_fallback(payload)
        message = self.ai_analysis.maybe_build_intraday_summary(payload, fallback)
        message = f"{message}\n\n生成时间: {payload['generatedAt']}"
        pushed = self.push_service.push(
            PushLevel.INFO,
            "intraday_summary",
            "SYSTEM",
            f"港股窝轮/牛熊证 {lookback_minutes}分钟盘中总结",
            message,
        )
        if pushed:
            self._set_runtime_state("last_intraday_summary_at", datetime.now().isoformat(timespec="seconds"))

    def _is_trading_time(self) -> bool:
        market = self.settings.get("market", {})
        now = datetime.now().time()
        start = self._parse_time(market.get("trading_start", "09:30:00"))
        end = self._parse_time(market.get("trading_end", "16:00:00"))
        break_start = self._parse_time(market.get("midday_break_start", "12:00:00"))
        break_end = self._parse_time(market.get("midday_break_end", "13:00:00"))
        if now < start or now > end:
            return False
        return not (break_start <= now < break_end)

    def _parse_time(self, value: str) -> time:
        return datetime.strptime(value, "%H:%M:%S").time()

    def _recent_summary_related_push_count(self, minutes: int) -> int:
        scenes = self.settings.get("summary", {}).get("include_scenes", ["trade_signal", "intraday_summary"])
        placeholders = ",".join("?" for _ in scenes)
        row = self.db.fetchone(
            f"""
            SELECT COUNT(*) AS count
            FROM push_record
            WHERE scene IN ({placeholders})
              AND pushed_at >= datetime('now', ?)
            """,
            (*scenes, f"-{minutes} minutes"),
        )
        return int(row["count"]) if row else 0

    def _build_intraday_summary_payload(self, watch_items, lookback_minutes: int) -> dict:
        min_snapshots = int(self.settings.get("summary", {}).get("min_snapshots", 2))
        underlyings = []
        for item in watch_items:
            snapshots = self.db.fetchall(
                """
                SELECT last_price, change_rate, volume, turnover, bid_price, ask_price,
                       bid_volume, ask_volume, snapshot_time, created_at
                FROM market_snapshot
                WHERE code = ? AND created_at >= datetime('now', ?)
                ORDER BY id ASC
                """,
                (item.code, f"-{lookback_minutes} minutes"),
            )
            if len(snapshots) < min_snapshots:
                continue

            signals = self.db.fetchall(
                """
                SELECT action, confidence, reason, risk, payload_json, created_at
                FROM trade_signal
                WHERE underlying_code = ? AND created_at >= datetime('now', ?)
                ORDER BY id ASC
                """,
                (item.code, f"-{lookback_minutes} minutes"),
            )
            first = snapshots[0]
            last = snapshots[-1]
            price_change = None
            first_price = float(first["last_price"] or 0)
            last_price = float(last["last_price"] or 0)
            if first_price:
                price_change = (last_price - first_price) / first_price * 100
            underlyings.append(
                {
                    "code": item.code,
                    "name": item.name,
                    "directionPreference": item.direction.value,
                    "riskLevel": item.risk_level.value,
                    "allowOvernight": item.allow_overnight,
                    "snapshotCount": len(snapshots),
                    "firstSnapshot": dict(first),
                    "lastSnapshot": dict(last),
                    "halfHourPriceChangePct": price_change,
                    "turnoverChange": float(last["turnover"] or 0) - float(first["turnover"] or 0),
                    "latestSignals": [dict(signal) for signal in signals[-6:]],
                }
            )
        return {
            "scene": "intraday_quiet_summary",
            "lookbackMinutes": lookback_minutes,
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "rules": [
                "这是没有交易推送后的盘中总结，不是强制交易信号。",
                "必须以正股走势和市场环境为主要判断依据。",
                "窝轮/牛熊证只作为表达方向的执行工具，若趋势不明应建议等待。",
                "输出中文 Markdown，简洁但要有可执行观察点。",
            ],
            "underlyings": underlyings,
        }

    def _build_intraday_summary_fallback(self, payload: dict) -> str:
        lines = [
            f"**港股窝轮/牛熊证 {payload['lookbackMinutes']}分钟盘中总结**",
            "",
            "过去半小时没有出现新的高置信度交易推送，系统进入静默复盘。",
        ]
        for item in payload["underlyings"]:
            signal = item["latestSignals"][-1] if item["latestSignals"] else {}
            change = item["halfHourPriceChangePct"]
            change_text = "未知" if change is None else f"{change:.2f}%"
            lines.extend(
                [
                    "",
                    f"**{item['name'] or item['code']} ({item['code']})**",
                    f"- 半小时正股变化: {change_text}",
                    f"- 最新价: {float(item['lastSnapshot']['last_price'] or 0):.3f}",
                    f"- 最近系统动作: {signal.get('action', '暂无')}，置信度: {signal.get('confidence', '-')}",
                    f"- 建议: 暂未出现清晰买购/买沽执行条件，继续等待正股方向确认。",
                ]
            )
        lines.append("")
        lines.append("说明: 本总结以正股走势为依据，窝轮/牛熊证仅作为执行工具，不构成自动交易。")
        return "\n".join(lines)
