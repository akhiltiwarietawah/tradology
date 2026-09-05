"""Risk limits, tick rounding, and order parameter validations."""

import math
from typing import Tuple
from src.core.models.instrument import Instrument


def round_to_tick(price: float, tick_size: float = 0.1) -> float:
    """Round price to the nearest tick size."""
    if tick_size <= 0:
        return price
    precision = max(0, -int(math.floor(math.log10(tick_size))))
    steps = round(price / tick_size)
    return round(steps * tick_size, precision)


def validate_order_size(quantity: float, instrument: Instrument) -> Tuple[bool, str, float]:
    """
    Validate and adjust order quantity according to instrument specifications.
    Returns (is_valid, error_msg, adjusted_quantity).
    """
    if quantity <= 0:
        return False, f"Quantity must be positive: {quantity}", quantity

    min_size = instrument.min_order_size
    if quantity < min_size:
        return False, f"Quantity {quantity} is less than min_order_size {min_size}", quantity

    return True, "", quantity
