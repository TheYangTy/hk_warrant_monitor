from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd

from hk_warrant_monitor.core.enums import ProductType
from hk_warrant_monitor.core.models import DerivativeProduct, MarketSnapshot


class FutuQuoteClient:
    def __init__(self, host: str, port: int, logger: logging.Logger | None = None):
        self.host = host
        self.port = port
        self.logger = logger or logging.getLogger(__name__)
        self.ft: Any | None = None
        self.quote_ctx: Any | None = None

    def connect(self) -> None:
        if self.quote_ctx is not None:
            return
        try:
            import futu as ft
        except ImportError as exc:
            raise RuntimeError("futu-api is not installed. Run `pip install -e .`.") from exc
        self.ft = ft
        self.quote_ctx = ft.OpenQuoteContext(host=self.host, port=self.port)
        self.logger.info("Connected to Futu OpenD at %s:%s", self.host, self.port)

    def close(self) -> None:
        if self.quote_ctx is not None:
            self.quote_ctx.close()
            self.quote_ctx = None

    def get_market_snapshots(self, codes: list[str]) -> list[MarketSnapshot]:
        self.connect()
        ret, data = self.quote_ctx.get_market_snapshot(codes)
        if ret != self.ft.RET_OK:
            raise RuntimeError(f"get_market_snapshot failed: {data}")
        return [self._snapshot_from_row(row) for _, row in data.iterrows()]

    def get_kline(self, code: str, ktype: str, count: int) -> pd.DataFrame:
        self.connect()
        subtype = getattr(self.ft.KLType, ktype)
        ret, data, _ = self.quote_ctx.request_history_kline(code, ktype=subtype, max_count=count)
        if ret != self.ft.RET_OK:
            raise RuntimeError(f"request_history_kline failed for {code} {ktype}: {data}")
        return data

    def get_order_book(self, code: str) -> dict[str, float]:
        self.connect()
        ret, data = self.quote_ctx.get_order_book(code)
        if ret != self.ft.RET_OK:
            self.logger.warning("get_order_book failed for %s: %s", code, data)
            return {}
        bid = data.get("Bid", []) or []
        ask = data.get("Ask", []) or []
        bid_price, bid_volume = (bid[0][0], bid[0][1]) if bid else (0.0, 0.0)
        ask_price, ask_volume = (ask[0][0], ask[0][1]) if ask else (0.0, 0.0)
        return {
            "bid_price": float(bid_price or 0),
            "ask_price": float(ask_price or 0),
            "bid_volume": float(bid_volume or 0),
            "ask_volume": float(ask_volume or 0),
        }

    def get_product_price(self, product_code: str) -> float:
        snapshot = self.get_market_snapshots([product_code])[0]
        return snapshot.last_price

    def subscribe_quotes(self, codes: list[str]) -> None:
        self.connect()
        ret, data = self.quote_ctx.subscribe(codes, [self.ft.SubType.QUOTE])
        if ret != self.ft.RET_OK:
            raise RuntimeError(f"subscribe quote failed: {data}")

    def discover_related_products(self, underlying_code: str) -> list[DerivativeProduct]:
        """Best-effort adapter for HK warrants/CBBC.

        Futu SDK versions expose derivative discovery differently. This method
        tries known method names and normalizes rows when available. It never
        invents products because trading suggestions must use real tradable data.
        """
        self.connect()
        candidates = []
        for method_name in ("get_warrant", "get_warrants", "get_warrant_list"):
            method = getattr(self.quote_ctx, method_name, None)
            if method is None:
                continue
            try:
                ret, data = method(underlying_code)
            except TypeError:
                try:
                    ret, data = method(stock_code=underlying_code)
                except Exception as exc:
                    self.logger.debug("%s failed for %s: %s", method_name, underlying_code, exc)
                    continue
            except Exception as exc:
                self.logger.debug("%s failed for %s: %s", method_name, underlying_code, exc)
                continue
            frame = self._extract_warrant_frame(data)
            if ret == self.ft.RET_OK and frame is not None and not frame.empty:
                candidates.extend(self._products_from_frame(underlying_code, frame))
                break

        if not candidates:
            self.logger.warning(
                "No warrant/CBBC discovery method returned data for %s. "
                "Check your Futu SDK permissions/version or add a product discovery adapter.",
                underlying_code,
            )
        return candidates

    def _snapshot_from_row(self, row: pd.Series) -> MarketSnapshot:
        last_price = float(row.get("last_price", 0) or 0)
        prev_close = float(row.get("prev_close_price", 0) or 0)
        change_rate = self._float_or_none(row.get("change_rate"))
        if change_rate is None and prev_close:
            change_rate = (last_price - prev_close) / prev_close * 100
        return MarketSnapshot(
            code=str(row.get("code", "")),
            name=str(row.get("name", "") or row.get("stock_name", "")),
            last_price=last_price,
            change_rate=float(change_rate or 0),
            volume=float(row.get("volume", 0) or 0),
            turnover=float(row.get("turnover", 0) or 0),
            amplitude=float(row.get("amplitude", 0) or 0),
            turnover_rate=float(row.get("turnover_rate", 0) or 0),
            bid_price=float(row.get("bid_price", 0) or 0),
            ask_price=float(row.get("ask_price", 0) or 0),
            bid_volume=float(row.get("bid_vol", row.get("bid_volume", 0)) or 0),
            ask_volume=float(row.get("ask_vol", row.get("ask_volume", 0)) or 0),
            snapshot_time=datetime.now(),
        )

    def _products_from_frame(self, underlying_code: str, data: pd.DataFrame) -> list[DerivativeProduct]:
        products: list[DerivativeProduct] = []
        for _, row in data.iterrows():
            code = str(row.get("stock", "") or row.get("code", "") or row.get("stock_code", ""))
            if not code:
                continue
            bid_price = self._float_or_none(row.get("bid_price"))
            ask_price = self._float_or_none(row.get("ask_price"))
            spread = self._float_or_none(row.get("spread"))
            if spread is None and bid_price is not None and ask_price is not None:
                spread = max(0.0, ask_price - bid_price)
            products.append(
                DerivativeProduct(
                    underlying_code=underlying_code,
                    code=code,
                    name=str(row.get("name", "") or row.get("stock_name", "")),
                    product_type=self._infer_product_type(row),
                    issuer=str(row.get("issuer", "") or row.get("owner", "")),
                    leverage=self._float_or_none(row.get("effective_leverage") or row.get("leverage")),
                    strike_price=self._float_or_none(row.get("strike_price") or row.get("exercise_price")),
                    expire_date=str(row.get("maturity_time", "") or row.get("expire_date", "") or row.get("last_trade_date", "") or ""),
                    iv=self._float_or_none(row.get("iv") or row.get("implied_volatility")),
                    street_ratio=self._float_or_none(row.get("street_rate") or row.get("street_ratio") or row.get("street_volumn_ratio")),
                    spread=spread,
                    volume=self._float_or_none(row.get("volume")),
                    turnover=self._float_or_none(row.get("turnover")),
                    last_price=self._float_or_none(row.get("cur_price") or row.get("last_price")),
                    extra=row.to_dict(),
                )
            )
        return products

    def _extract_warrant_frame(self, data: Any) -> pd.DataFrame | None:
        if isinstance(data, pd.DataFrame):
            return data
        if isinstance(data, tuple) and data and isinstance(data[0], pd.DataFrame):
            return data[0]
        return None

    def _infer_product_type(self, row: pd.Series) -> ProductType:
        raw = " ".join(str(row.get(key, "")) for key in ("type", "wrt_type", "stock_type", "name")).upper()
        if "BULL" in raw or "牛" in raw:
            return ProductType.BULL_CBBC
        if "BEAR" in raw or "熊" in raw:
            return ProductType.BEAR_CBBC
        if "PUT" in raw or "沽" in raw or raw.strip() == "PUT":
            return ProductType.PUT_WARRANT
        if "CALL" in raw or "购" in raw or raw.strip() == "CALL":
            return ProductType.CALL_WARRANT
        return ProductType.UNKNOWN

    def _float_or_none(self, value: Any) -> float | None:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None
