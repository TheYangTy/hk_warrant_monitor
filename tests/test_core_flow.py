from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hk_warrant_monitor.core.enums import Direction, ProductType, RiskLevel, SignalAction, Strength, Trend
from hk_warrant_monitor.core.models import DerivativeProduct, MarketSnapshot, Position, TrendResult, WatchItem
from hk_warrant_monitor.data_sources.mock_client import MockQuoteClient
from hk_warrant_monitor.ai.deepseek_service import DeepSeekAnalysisService
from hk_warrant_monitor.infra.database import Database
from hk_warrant_monitor.jobs.intraday_scan_job import IntradayScanJob
from hk_warrant_monitor.notifications.feishu_client import FeishuClient
from hk_warrant_monitor.notifications.push_service import PushService
from hk_warrant_monitor.products.filter import ProductFilter
from hk_warrant_monitor.strategy.position_engine import PositionEngine
from hk_warrant_monitor.strategy.signal_engine import SignalEngine
from hk_warrant_monitor.watchlist.service import WatchlistService, normalize_hk_code


SETTINGS = {
    "database": {"path": "unused"},
    "scan": {
        "interval_seconds": 60,
        "kline_count": 120,
        "kline_types": ["K_1M", "K_5M", "K_15M"],
        "index_codes": {"hsi": "HK.800000", "hstech": "HK.800700"},
    },
    "products": {
        "min_turnover": 100000,
        "max_spread_pct": 8.0,
        "max_street_ratio": 60.0,
        "min_days_to_expiry": 30,
        "max_iv": 90.0,
        "min_leverage": 2.0,
        "max_leverage": 12.0,
        "max_moneyness_abs_pct": 12.0,
    },
    "signals": {
        "buy_confidence_threshold": 70,
        "take_profit_pct": 25.0,
        "stop_loss_pct": -12.0,
    },
    "ai": {
        "enabled": True,
        "provider": "deepseek",
        "api_key": "",
        "model": "deepseek-v4-flash",
        "daily_limit": 50,
        "cooldown_minutes": 15,
        "min_confidence": 72,
        "style": "TRADER_BRIEF",
    },
}


class NullLogger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None

    def debug(self, *_args, **_kwargs):
        return None


class CoreFlowTest(unittest.TestCase):
    def test_normalize_hk_code(self):
        self.assertEqual(normalize_hk_code("00700.HK"), "HK.00700")
        self.assertEqual(normalize_hk_code("700"), "HK.00700")
        self.assertEqual(normalize_hk_code("HK.09988"), "HK.09988")

    def test_signal_is_based_on_underlying_trend(self):
        engine = SignalEngine(SETTINGS)
        item = WatchItem("HK.00700", "腾讯控股", Direction.LONG, RiskLevel.MEDIUM, False)
        signal = engine.generate(item, TrendResult(Trend.BULLISH, 82, Strength.STRONG, {"source": "underlying"}))
        self.assertEqual(signal.action, SignalAction.BUY_CALL)
        self.assertEqual(signal.underlying_code, "HK.00700")
        self.assertIsNone(signal.product_code)

    def test_product_filter_uses_signal_direction_as_execution_tool(self):
        products = [
            DerivativeProduct("HK.00700", "HK.CALL", "购", ProductType.CALL_WARRANT, turnover=500000, leverage=5, strike_price=102, expire_date="2099-01-01", iv=40, street_ratio=20, spread=0.002, last_price=0.1),
            DerivativeProduct("HK.00700", "HK.PUT", "沽", ProductType.PUT_WARRANT, turnover=500000, leverage=5, strike_price=98, expire_date="2099-01-01", iv=40, street_ratio=20, spread=0.002, last_price=0.1),
        ]
        ranked = ProductFilter(SETTINGS).rank_for_signal(products, SignalAction.BUY_CALL, MarketSnapshot("HK.00700", last_price=100))
        self.assertEqual([product.code for product in ranked], ["HK.CALL"])

    def test_mock_scan_selects_call_without_seeded_watchlist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(str(Path(tmpdir) / "test.db"))
            db.init()
            watchlist = WatchlistService(db)
            self.assertEqual(watchlist.list(), [])
            watchlist.add("00700.HK", "腾讯控股", Direction.LONG, RiskLevel.MEDIUM, False)
            push = PushService(db, FeishuClient(""), NullLogger())
            job = IntradayScanJob(SETTINGS, db, MockQuoteClient(), watchlist, push, NullLogger())

            signals = job.run_once()

            self.assertEqual(len(signals), 1)
            self.assertEqual(signals[0].action, SignalAction.BUY_CALL)
            self.assertEqual(signals[0].product_code, "HK.MOCKCALL")

    def test_position_engine_take_profit_uses_product_pnl(self):
        position = Position(product_code="HK.MOCKCALL", buy_price=0.18, quantity=100000, buy_time="2026-06-24 10:30:00")
        result = PositionEngine(SETTINGS).analyze(position, current_price=0.24)
        self.assertEqual(result.action, SignalAction.TAKE_PROFIT)
        self.assertAlmostEqual(result.pnl_ratio, 33.3333333333)

    def test_ai_analysis_skips_without_api_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(str(Path(tmpdir) / "test.db"))
            db.init()
            service = DeepSeekAnalysisService(SETTINGS, db, NullLogger())
            signal = SignalEngine(SETTINGS).generate(
                WatchItem("HK.00700", "腾讯控股", Direction.LONG, RiskLevel.MEDIUM, False),
                TrendResult(Trend.BULLISH, 82, Strength.STRONG, {}),
            )
            message = service.maybe_build_message(
                MarketSnapshot("HK.00700", last_price=100),
                TrendResult(Trend.BULLISH, 82, Strength.STRONG, {}),
                signal,
                [DerivativeProduct("HK.00700", "HK.CALL", "购", ProductType.CALL_WARRANT)],
                "fallback",
            )
            self.assertEqual(message, "fallback")


if __name__ == "__main__":
    unittest.main()
