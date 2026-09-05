"""Option strike selector for discovering ~$100 OTM Call and Put legs."""

import logging
from typing import List, Dict, Tuple, Optional
from src.core.models.instrument import Instrument, OptionChain, InstrumentType, OptionType
from src.core.models.market_data import Ticker


class OptionSelectionError(Exception):
    """Raised when option strikes matching criteria cannot be found."""
    pass


class OptionSelector:
    """Selects same-day expiry OTM short strangle legs with ~ $100 target premium."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("option_selector")

    def select_strangle_legs(
        self,
        option_chain: OptionChain,
        tickers_map: Dict[str, Ticker],
        spot_price: float,
        target_premium: float = 100.0,
        tolerance_usd: float = 30.0,
    ) -> Tuple[Instrument, Ticker, Instrument, Ticker]:
        """
        Find best OTM Call and OTM Put option contracts closest to target_premium within tolerance.
        
        Rules:
        1. Call Strike > spot_price (OTM Call).
        2. Put Strike < spot_price (OTM Put).
        3. Option premium within [target_premium - tolerance, target_premium + tolerance].
        4. Select candidate with min |premium - target_premium|.
        """
        if spot_price <= 0:
            raise OptionSelectionError(f"Invalid underlying spot price: {spot_price}")

        min_acceptable_prem = max(1.0, target_premium - tolerance_usd)
        max_acceptable_prem = target_premium + tolerance_usd

        call_candidates: List[Tuple[Instrument, Ticker, float, float]] = []
        put_candidates: List[Tuple[Instrument, Ticker, float, float]] = []

        # Evaluate Calls
        for inst in option_chain.calls:
            if inst.strike_price is None or inst.strike_price <= spot_price:
                continue  # Must be strictly OTM

            ticker = tickers_map.get(inst.symbol) or tickers_map.get(inst.instrument_id)
            if not ticker:
                continue

            prem = ticker.mid_price
            if prem <= 0:
                continue

            if min_acceptable_prem <= prem <= max_acceptable_prem:
                diff = abs(prem - target_premium)
                call_candidates.append((inst, ticker, prem, diff))
            else:
                self.logger.debug(
                    f"Call strike {inst.strike_price} prem ${prem:.2f} outside [${min_acceptable_prem:.2f}-${max_acceptable_prem:.2f}]"
                )

        # Evaluate Puts
        for inst in option_chain.puts:
            if inst.strike_price is None or inst.strike_price >= spot_price:
                continue  # Must be strictly OTM

            ticker = tickers_map.get(inst.symbol) or tickers_map.get(inst.instrument_id)
            if not ticker:
                continue

            prem = ticker.mid_price
            if prem <= 0:
                continue

            if min_acceptable_prem <= prem <= max_acceptable_prem:
                diff = abs(prem - target_premium)
                put_candidates.append((inst, ticker, prem, diff))
            else:
                self.logger.debug(
                    f"Put strike {inst.strike_price} prem ${prem:.2f} outside [${min_acceptable_prem:.2f}-${max_acceptable_prem:.2f}]"
                )

        if not call_candidates:
            raise OptionSelectionError(
                f"No OTM Call found with premium between ${min_acceptable_prem:.2f} and ${max_acceptable_prem:.2f} (Spot: ${spot_price:.2f})"
            )

        if not put_candidates:
            raise OptionSelectionError(
                f"No OTM Put found with premium between ${min_acceptable_prem:.2f} and ${max_acceptable_prem:.2f} (Spot: ${spot_price:.2f})"
            )

        # Sort candidates by smallest deviation from target_premium
        call_candidates.sort(key=lambda x: x[3])
        put_candidates.sort(key=lambda x: x[3])

        best_call_inst, best_call_ticker, best_call_prem, _ = call_candidates[0]
        best_put_inst, best_put_ticker, best_put_prem, _ = put_candidates[0]

        self.logger.info(
            f"Selected CE: {best_call_inst.symbol} (Strike: {best_call_inst.strike_price}, Est Premium: ${best_call_prem:.2f})"
        )
        self.logger.info(
            f"Selected PE: {best_put_inst.symbol} (Strike: {best_put_inst.strike_price}, Est Premium: ${best_put_prem:.2f})"
        )

        return best_call_inst, best_call_ticker, best_put_inst, best_put_ticker
