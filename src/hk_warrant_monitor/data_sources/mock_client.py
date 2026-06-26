from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from hk_warrant_monitor.core.enums import ProductType
from hk_warrant_monitor.core.models import DerivativeProduct, MarketSnapshot


class MockQuoteClient:
    """Development-only quote client.

    This client exists to test the pipeline without Futu OpenD. It does not add
    watchlist symbols by itself; users still need to explicitly add underlyings.
    """

    def close(self) -> None:
        return None

    def get_market_snapshots(self, codes: list[str]) -> list[MarketSnapshot]:
        snapshots = []
        for code in codes:
            if code in {"HK.800000", "HK.800700"}:
                snapshots.append(
                    MarketSnapshot(
                        code=code,
                        name="指数",
                        last_price=10000.0,
                        change_rate=0.9,
                        volume=1_000_000,
                        turnover=10_000_000_000,
                    )
                )
                continue

            snapshots.append(
                MarketSnapshot(
                    code=code,
                    name=code,
                    last_price=100.0,
                    change_rate=2.1,
                    volume=30_000_000,
                    turnover=3_000_000_000,
                    bid_price=99.95,
                    ask_price=100.05,
                    bid_volume=500_000,
                    ask_volume=420_000,
                )
            )
        return snapshots

    def get_kline(self, code: str, ktype: str, count: int) -> pd.DataFrame:
        base_time = datetime.now() - timedelta(minutes=count)
        rows = []
        for i in range(count):
            close = 80 + i * 0.18
            rows.append(
                {
                    "code": code,
                    "time_key": (base_time + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S"),
                    "open": close - 0.08,
                    "high": close + 0.18,
                    "low": close - 0.22,
                    "close": close,
                    "volume": 1_000_000 + i * 10_000,
                    "turnover": (1_000_000 + i * 10_000) * close,
                }
            )
        return pd.DataFrame(rows)

    def discover_related_products(self, underlying_code: str) -> list[DerivativeProduct]:
        return [
            DerivativeProduct(
                underlying_code=underlying_code,
                code="HK.MOCKCALL",
                name="开发测试认购证",
                product_type=ProductType.CALL_WARRANT,
                issuer="MOCK",
                leverage=6.2,
                strike_price=103.0,
                expire_date=(datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d"),
                iv=48.0,
                street_ratio=22.0,
                spread=0.002,
                volume=8_000_000,
                turnover=1_200_000,
                last_price=0.12,
            ),
            DerivativeProduct(
                underlying_code=underlying_code,
                code="HK.MOCKPUT",
                name="开发测试认沽证",
                product_type=ProductType.PUT_WARRANT,
                issuer="MOCK",
                leverage=5.8,
                strike_price=96.0,
                expire_date=(datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d"),
                iv=50.0,
                street_ratio=25.0,
                spread=0.002,
                volume=4_000_000,
                turnover=900_000,
                last_price=0.11,
            ),
        ]

    def get_product_price(self, product_code: str) -> float:
        if product_code == "HK.MOCKLOSS":
            return 0.08
        return 0.24
