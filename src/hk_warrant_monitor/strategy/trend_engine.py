from __future__ import annotations

import pandas as pd

from hk_warrant_monitor.core.enums import Strength, Trend
from hk_warrant_monitor.core.models import IndicatorSnapshot, MarketSnapshot, TrendResult


class TrendEngine:
    def analyze(
        self,
        snapshot: MarketSnapshot,
        indicators: dict[str, IndicatorSnapshot],
        index_snapshots: dict[str, MarketSnapshot] | None = None,
        kline_frames: dict[str, pd.DataFrame] | None = None,
    ) -> TrendResult:
        score = 50
        details: dict[str, object] = {}
        primary = indicators.get("K_5M") or next(iter(indicators.values()), None)
        if primary is None:
            return TrendResult(Trend.NEUTRAL, score, Strength.WEAK, {"reason": "missing indicators"})

        ma_score = self._ma_score(primary, snapshot.last_price)
        momentum_score = self._momentum_score(primary)
        index_score = self._index_score(index_snapshots or {})
        price_score = 8 if snapshot.change_rate > 1 else -8 if snapshot.change_rate < -1 else 0
        volume_score = self._volume_score(kline_frames or {})
        vwap_score = self._vwap_score(primary, snapshot.last_price)
        orderbook_score = self._orderbook_score(snapshot)
        breakout_score = self._breakout_score(snapshot.last_price, kline_frames or {})
        volatility_score = self._volatility_score(snapshot, primary)
        chase_penalty = self._chase_penalty(snapshot, primary, kline_frames or {})

        score += (
            ma_score
            + momentum_score
            + index_score
            + price_score
            + volume_score
            + vwap_score
            + orderbook_score
            + breakout_score
            + volatility_score
            + chase_penalty
        )
        score = max(0, min(100, score))
        trend = Trend.BULLISH if score >= 65 else Trend.BEARISH if score <= 35 else Trend.NEUTRAL
        strength = Strength.STRONG if score >= 80 or score <= 20 else Strength.MEDIUM if score >= 65 or score <= 35 else Strength.WEAK
        details.update(
            {
                "ma_score": ma_score,
                "momentum_score": momentum_score,
                "index_score": index_score,
                "price_score": price_score,
                "volume_score": volume_score,
                "vwap_score": vwap_score,
                "orderbook_score": orderbook_score,
                "breakout_score": breakout_score,
                "volatility_score": volatility_score,
                "chase_penalty": chase_penalty,
                "snapshot_change_rate": snapshot.change_rate,
            }
        )
        return TrendResult(trend, score, strength, details)

    def _ma_score(self, indicator: IndicatorSnapshot, price: float) -> int:
        values = [indicator.ma5, indicator.ma10, indicator.ma20, indicator.ma60]
        if any(v is None for v in values):
            return 0
        ma5, ma10, ma20, ma60 = values
        if price > ma5 > ma10 > ma20 > ma60:
            return 18
        if price < ma5 < ma10 < ma20 < ma60:
            return -18
        if ma5 and ma20 and ma5 > ma20:
            return 8
        if ma5 and ma20 and ma5 < ma20:
            return -8
        return 0

    def _momentum_score(self, indicator: IndicatorSnapshot) -> int:
        score = 0
        if indicator.rsi is not None:
            if 55 <= indicator.rsi <= 72:
                score += 8
            elif indicator.rsi >= 78:
                score -= 4
            elif indicator.rsi <= 40:
                score -= 8
        if indicator.macd_hist is not None:
            score += 8 if indicator.macd_hist > 0 else -8 if indicator.macd_hist < 0 else 0
        return score

    def _index_score(self, snapshots: dict[str, MarketSnapshot]) -> int:
        if not snapshots:
            return 0
        avg = sum(s.change_rate for s in snapshots.values()) / len(snapshots)
        if avg > 0.6:
            return 6
        if avg < -0.6:
            return -6
        return 0

    def _volume_score(self, frames: dict[str, pd.DataFrame]) -> int:
        frame = self._primary_frame(frames)
        if frame is None or len(frame) < 25 or "volume" not in frame:
            return 0
        volume = frame["volume"].astype(float)
        close = frame["close"].astype(float)
        latest = volume.iloc[-1]
        avg = volume.iloc[-21:-1].mean()
        if not avg:
            return 0
        ratio = latest / avg
        price_up = close.iloc[-1] > close.iloc[-2]
        price_down = close.iloc[-1] < close.iloc[-2]
        if ratio >= 2.0 and price_up:
            return 8
        if ratio >= 1.5 and price_up:
            return 5
        if ratio >= 2.0 and price_down:
            return -8
        if ratio >= 1.5 and price_down:
            return -5
        return 0

    def _vwap_score(self, indicator: IndicatorSnapshot, price: float) -> int:
        if not indicator.vwap or not price:
            return 0
        distance_pct = (price - indicator.vwap) / indicator.vwap * 100
        if 0.2 <= distance_pct <= 3:
            return 5
        if -3 <= distance_pct <= -0.2:
            return -5
        if distance_pct > 8:
            return -4
        return 0

    def _orderbook_score(self, snapshot: MarketSnapshot) -> int:
        bid = snapshot.bid_volume
        ask = snapshot.ask_volume
        if bid <= 0 or ask <= 0:
            return 0
        ratio = bid / ask
        if ratio >= 1.8:
            return 5
        if ratio <= 0.55:
            return -5
        return 0

    def _breakout_score(self, price: float, frames: dict[str, pd.DataFrame]) -> int:
        frame = self._primary_frame(frames)
        if frame is None or len(frame) < 30 or not price:
            return 0
        previous = frame.iloc[-31:-1]
        recent_high = float(previous["high"].astype(float).max())
        recent_low = float(previous["low"].astype(float).min())
        if recent_high and price > recent_high:
            return 10
        if recent_low and price < recent_low:
            return -10
        near_high = recent_high and (recent_high - price) / recent_high * 100 <= 0.3
        near_low = recent_low and (price - recent_low) / recent_low * 100 <= 0.3
        if near_high:
            return 4
        if near_low:
            return -4
        return 0

    def _volatility_score(self, snapshot: MarketSnapshot, indicator: IndicatorSnapshot) -> int:
        score = 0
        if snapshot.amplitude >= 12:
            score -= 6
        elif snapshot.amplitude >= 8:
            score -= 3

        if indicator.boll_mid and indicator.boll_upper and indicator.boll_lower:
            boll_width = (indicator.boll_upper - indicator.boll_lower) / indicator.boll_mid * 100
            if boll_width >= 12:
                score -= 4
            elif boll_width <= 3:
                score += 2
        return score

    def _chase_penalty(
        self,
        snapshot: MarketSnapshot,
        indicator: IndicatorSnapshot,
        frames: dict[str, pd.DataFrame],
    ) -> int:
        penalty = 0
        if indicator.rsi is not None and indicator.rsi >= 78:
            penalty -= 6
        if indicator.ma20 and snapshot.last_price > indicator.ma20 * 1.08:
            penalty -= 5
        if indicator.vwap and snapshot.last_price > indicator.vwap * 1.08:
            penalty -= 5

        frame = self._primary_frame(frames)
        if frame is not None and len(frame) >= 30 and snapshot.last_price:
            recent_high = float(frame.iloc[-30:]["high"].astype(float).max())
            recent_low = float(frame.iloc[-30:]["low"].astype(float).min())
            if recent_low and recent_high:
                position = (snapshot.last_price - recent_low) / (recent_high - recent_low) if recent_high != recent_low else 0
                if position >= 0.95 and snapshot.change_rate >= 5:
                    penalty -= 6
        return penalty

    def _primary_frame(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
        frame = frames.get("K_5M")
        if frame is None:
            frame = frames.get("K_1M")
        if frame is None:
            frame = next(iter(frames.values()), None)
        if frame is None or frame.empty:
            return None
        required = {"high", "low", "close"}
        if not required.issubset(frame.columns):
            return None
        return frame
