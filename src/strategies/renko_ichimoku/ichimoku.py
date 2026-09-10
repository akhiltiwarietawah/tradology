"""Ichimoku on confirmed Renko bricks only. No future bricks in any window.

Cloud at brick i is raw Senkou A/B computed at brick i - displacement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from src.strategies.renko_ichimoku.params import RENKO_ICHIMOKU_FIXED_PARAMS
from src.strategies.renko_ichimoku.renko import ConfirmedBrick


def _hl_mid(highs: Sequence[float], lows: Sequence[float], period: int) -> Optional[float]:
    if len(highs) < period:
        return None
    window_h = highs[-period:]
    window_l = lows[-period:]
    return (max(window_h) + min(window_l)) / 2.0


@dataclass(frozen=True)
class IchimokuSnapshot:
    index: int
    tenkan: Optional[float]
    kijun: Optional[float]
    span_a: Optional[float]
    span_b: Optional[float]
    ready: bool
    above_cloud: bool
    below_cloud: bool
    inside_cloud: bool
    above_kijun: bool
    below_kijun: bool
    at_or_above_kijun: bool


class IncrementalIchimoku:
    def __init__(
        self,
        tenkan: int = RENKO_ICHIMOKU_FIXED_PARAMS.tenkan,
        kijun: int = RENKO_ICHIMOKU_FIXED_PARAMS.kijun,
        span_b: int = RENKO_ICHIMOKU_FIXED_PARAMS.span_b,
        displacement: int = RENKO_ICHIMOKU_FIXED_PARAMS.cloud_displacement,
    ):
        self.tenkan_period = tenkan
        self.kijun_period = kijun
        self.span_b_period = span_b
        self.displacement = displacement
        self.highs: List[float] = []
        self.lows: List[float] = []
        self.span_a_raw: List[Optional[float]] = []
        self.span_b_raw: List[Optional[float]] = []
        self.snapshots: List[IchimokuSnapshot] = []

    def update(self, brick: ConfirmedBrick) -> IchimokuSnapshot:
        """Append one confirmed brick. Uses only this brick and prior bricks."""
        self.highs.append(brick.high)
        self.lows.append(brick.low)
        i = len(self.highs) - 1
        tenkan = _hl_mid(self.highs, self.lows, self.tenkan_period)
        kijun = _hl_mid(self.highs, self.lows, self.kijun_period)
        span_a_now = (tenkan + kijun) / 2.0 if tenkan is not None and kijun is not None else None
        span_b_now = _hl_mid(self.highs, self.lows, self.span_b_period)
        self.span_a_raw.append(span_a_now)
        self.span_b_raw.append(span_b_now)

        span_a = None
        span_b = None
        if self.displacement > 0 and i >= self.displacement:
            span_a = self.span_a_raw[i - self.displacement]
            span_b = self.span_b_raw[i - self.displacement]
        elif self.displacement == 0:
            span_a = span_a_now
            span_b = span_b_now

        close = brick.close
        ready = span_a is not None and span_b is not None and kijun is not None
        if ready:
            cloud_low = min(span_a, span_b)
            cloud_high = max(span_a, span_b)
            above_cloud = close > span_a and close > span_b
            below_cloud = close < span_a and close < span_b
            inside_cloud = cloud_low <= close <= cloud_high
            above_kijun = close > kijun
            below_kijun = close < kijun
            at_or_above_kijun = close >= kijun
        else:
            above_cloud = below_cloud = inside_cloud = False
            above_kijun = below_kijun = at_or_above_kijun = False

        snap = IchimokuSnapshot(
            index=i,
            tenkan=tenkan,
            kijun=kijun,
            span_a=span_a,
            span_b=span_b,
            ready=ready,
            above_cloud=above_cloud,
            below_cloud=below_cloud,
            inside_cloud=inside_cloud,
            above_kijun=above_kijun,
            below_kijun=below_kijun,
            at_or_above_kijun=at_or_above_kijun,
        )
        self.snapshots.append(snap)
        return snap
