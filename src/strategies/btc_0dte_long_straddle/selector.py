"""Option strike selector for ATM Long Straddle."""

import logging
from typing import Tuple, Optional
from datetime import date

from src.core.models.instrument import Instrument, OptionChain, OptionType


class ATMStraddleSelector:
    """Selects ATM Call and ATM Put for current day's expiry (0DTE)."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("straddle_selector")

    def select_atm_straddle(
        self,
        option_chain: OptionChain,
        spot_price: float,
        expiry_date: date,
    ) -> Tuple[Instrument, Instrument]:
        """Find the ATM Call and ATM Put closest to the current spot price for the given expiry."""
        calls = [
            inst for inst in option_chain.calls.values()
            if inst.expiry_date == expiry_date
        ]
        puts = [
            inst for inst in option_chain.puts.values()
            if inst.expiry_date == expiry_date
        ]

        if not calls or not puts:
            raise ValueError(f"No 0DTE options found for expiry {expiry_date}")

        # Find strike closest to spot price
        best_call = min(calls, key=lambda inst: abs((inst.strike_price or 0) - spot_price))
        best_put = min(puts, key=lambda inst: abs((inst.strike_price or 0) - spot_price))

        self.logger.info(
            f"Selected ATM Straddle for Spot {spot_price:.1f} | "
            f"CE: {best_call.symbol} (Strike: {best_call.strike_price}) | "
            f"PE: {best_put.symbol} (Strike: {best_put.strike_price})"
        )
        return best_call, best_put
