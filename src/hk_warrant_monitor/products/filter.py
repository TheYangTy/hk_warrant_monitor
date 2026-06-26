from __future__ import annotations

from datetime import date, datetime

from hk_warrant_monitor.core.enums import ProductType, SignalAction
from hk_warrant_monitor.core.models import DerivativeProduct, MarketSnapshot


class ProductFilter:
    def __init__(self, settings: dict):
        self.settings = settings["products"]

    def rank_for_signal(
        self,
        products: list[DerivativeProduct],
        action: SignalAction,
        underlying: MarketSnapshot,
    ) -> list[DerivativeProduct]:
        filtered = [p for p in products if self._matches_action(p, action)]
        filtered = [p for p in filtered if self._passes_liquidity(p)]
        filtered = [p for p in filtered if self._passes_expiry(p)]
        filtered = [p for p in filtered if self._passes_leverage(p)]
        filtered = [p for p in filtered if self._passes_iv_and_street(p)]
        filtered = [p for p in filtered if self._passes_moneyness(p, underlying.last_price)]
        return sorted(filtered, key=self._score, reverse=True)

    def _matches_action(self, product: DerivativeProduct, action: SignalAction) -> bool:
        if action in (SignalAction.BUY_CALL, SignalAction.TRY_CALL, SignalAction.WATCH_CALL):
            return product.product_type in (ProductType.CALL_WARRANT, ProductType.BULL_CBBC)
        if action in (SignalAction.BUY_PUT, SignalAction.TRY_PUT, SignalAction.WATCH_PUT):
            return product.product_type in (ProductType.PUT_WARRANT, ProductType.BEAR_CBBC)
        return False

    def _passes_liquidity(self, product: DerivativeProduct) -> bool:
        turnover = product.turnover or 0
        if turnover < self.settings["min_turnover"]:
            return False
        if product.spread is not None and product.last_price:
            spread_pct = product.spread / product.last_price * 100
            if spread_pct > self.settings["max_spread_pct"]:
                return False
        return True

    def _passes_expiry(self, product: DerivativeProduct) -> bool:
        days = self._days_to_expiry(product.expire_date)
        return days is None or days >= self.settings["min_days_to_expiry"]

    def _passes_leverage(self, product: DerivativeProduct) -> bool:
        if product.leverage is None:
            return True
        return self.settings["min_leverage"] <= product.leverage <= self.settings["max_leverage"]

    def _passes_iv_and_street(self, product: DerivativeProduct) -> bool:
        if product.iv is not None and product.iv > self.settings["max_iv"]:
            return False
        if product.street_ratio is not None and product.street_ratio > self.settings["max_street_ratio"]:
            return False
        return True

    def _passes_moneyness(self, product: DerivativeProduct, underlying_price: float) -> bool:
        if not product.strike_price or not underlying_price:
            return True
        diff_pct = abs(product.strike_price - underlying_price) / underlying_price * 100
        return diff_pct <= self.settings["max_moneyness_abs_pct"]

    def _score(self, product: DerivativeProduct) -> float:
        score = 0.0
        score += min((product.turnover or 0) / 100000, 30)
        if product.spread is not None and product.last_price:
            score += max(0, 20 - product.spread / product.last_price * 100)
        if product.street_ratio is not None:
            score += max(0, 20 - product.street_ratio / 3)
        if product.leverage is not None:
            score += max(0, 20 - abs(product.leverage - 6) * 2)
        days = self._days_to_expiry(product.expire_date)
        if days is not None:
            score += min(days / 10, 10)
        return score

    def _days_to_expiry(self, value: str | None) -> int | None:
        if not value:
            return None
        try:
            return (datetime.strptime(value[:10], "%Y-%m-%d").date() - date.today()).days
        except ValueError:
            return None
