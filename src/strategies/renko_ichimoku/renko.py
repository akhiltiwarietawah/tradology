"""Traditional Renko from sequential CLOSE prints only.

Confirmed bricks only: a brick is emitted after the close has moved a full
box (or 2 boxes on reversal). Partial moves are not bricks and are never
exposed as projections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class ConfirmedBrick:
    index: int
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    direction: int  # 1 bullish, -1 bearish
    source_bar_index: int


@dataclass
class TraditionalRenko:
    box_size: float = 15.0
    last_close: Optional[float] = None
    direction: int = 0
    bricks: List[ConfirmedBrick] = field(default_factory=list)
    source_bar_index: int = -1

    def apply_close(self, price: float, timestamp: float) -> List[ConfirmedBrick]:
        """Apply one confirmed source CLOSE. Returns newly confirmed bricks only."""
        self.source_bar_index += 1
        if self.last_close is None:
            self.last_close = float(int(price / self.box_size) * self.box_size)
        before = len(self.bricks)
        self._apply_price(float(price), timestamp, self.source_bar_index)
        return self.bricks[before:]

    def _emit(self, brick_open: float, brick_close: float, d: int, t: float, i: int) -> None:
        if d == 1:
            high, low = brick_close, brick_open
        else:
            high, low = brick_open, brick_close
        brick = ConfirmedBrick(
            index=len(self.bricks),
            timestamp=t,
            open=brick_open,
            high=high,
            low=low,
            close=brick_close,
            direction=d,
            source_bar_index=i,
        )
        self.bricks.append(brick)
        self.last_close = brick_close
        self.direction = d

    def _apply_price(self, price: float, t: float, i: int) -> None:
        box = self.box_size
        two = 2.0 * box
        if self.direction == 0:
            while price >= self.last_close + box:
                self._emit(self.last_close, self.last_close + box, 1, t, i)
            while price <= self.last_close - box:
                self._emit(self.last_close, self.last_close - box, -1, t, i)
        elif self.direction == 1:
            while price >= self.last_close + box:
                self._emit(self.last_close, self.last_close + box, 1, t, i)
            while price <= self.last_close - two:
                self._emit(self.last_close, self.last_close - box, -1, t, i)
        else:
            while price <= self.last_close - box:
                self._emit(self.last_close, self.last_close - box, -1, t, i)
            while price >= self.last_close + two:
                self._emit(self.last_close, self.last_close + box, 1, t, i)
