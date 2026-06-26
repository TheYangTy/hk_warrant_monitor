from __future__ import annotations

import numpy as np
import pandas as pd

from hk_warrant_monitor.core.models import IndicatorSnapshot


class IndicatorCalculator:
    def calculate(self, code: str, ktype: str, kline: pd.DataFrame) -> IndicatorSnapshot:
        if kline.empty:
            return IndicatorSnapshot(code, ktype, None, None, None, None, None, None, None, None, None, None, None, None)

        close = kline["close"].astype(float)
        high = kline["high"].astype(float)
        low = kline["low"].astype(float)
        volume = kline.get("volume", pd.Series(np.zeros(len(kline)))).astype(float)
        turnover = kline.get("turnover", pd.Series(np.zeros(len(kline)))).astype(float)

        ma5 = self._last(close.rolling(5).mean())
        ma10 = self._last(close.rolling(10).mean())
        ma20 = self._last(close.rolling(20).mean())
        ma60 = self._last(close.rolling(60).mean())
        vwap = float(turnover.sum() / volume.sum()) if volume.sum() else None
        rsi = self._rsi(close)
        macd, signal, hist = self._macd(close)
        boll_mid = ma20
        boll_std = self._last(close.rolling(20).std())
        boll_upper = boll_mid + 2 * boll_std if boll_mid is not None and boll_std is not None else None
        boll_lower = boll_mid - 2 * boll_std if boll_mid is not None and boll_std is not None else None

        return IndicatorSnapshot(
            code=code,
            ktype=ktype,
            ma5=ma5,
            ma10=ma10,
            ma20=ma20,
            ma60=ma60,
            vwap=vwap,
            rsi=rsi,
            macd=macd,
            macd_signal=signal,
            macd_hist=hist,
            boll_mid=boll_mid,
            boll_upper=boll_upper,
            boll_lower=boll_lower,
        )

    def _last(self, series: pd.Series) -> float | None:
        value = series.iloc[-1]
        if pd.isna(value):
            return None
        return float(value)

    def _rsi(self, close: pd.Series, period: int = 14) -> float | None:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        if loss.iloc[-1] == 0 or pd.isna(loss.iloc[-1]):
            return None
        rs = gain.iloc[-1] / loss.iloc[-1]
        return float(100 - (100 / (1 + rs)))

    def _macd(self, close: pd.Series) -> tuple[float | None, float | None, float | None]:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        return self._last(macd), self._last(signal), self._last(hist)

