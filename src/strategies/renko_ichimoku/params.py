"""Frozen Renko + Ichimoku parameters. Not for optimization."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RenkoIchimokuFixedParams:
    """Strategy geometry is fixed. Do not search or auto-tune these values."""

    box_size: float = 15.0
    source: str = "close"
    tenkan: int = 9
    kijun: int = 26
    span_b: int = 52
    cloud_displacement: int = 26


RENKO_ICHIMOKU_FIXED_PARAMS = RenkoIchimokuFixedParams()

# First brick index that can have a displaced cloud + Kijun:
# Span B needs 52 bricks; cloud uses values from 26 bricks earlier → index 77.
ICHIMOKU_READY_INDEX = 52 + 26 - 1  # 77
