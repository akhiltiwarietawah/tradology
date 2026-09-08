"""Option strike selector for discovering ~$100 OTM Call and Put legs."""

import logging
from typing import List, Dict, Tuple, Optional
from src.core.models.instrument import Instrument, OptionChain
from src.core.models.market_data import Ticker


class OptionSelectionError(Exception):
    """Raised when option strikes matching criteria cannot be found."""
    pass


class OptionSelector:
    """Selects same-day expiry OTM short strangle legs with ~ $100 target premium."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("option_selector")

    @staticmethod
    def premium_band(target_premium: float, tolerance_usd: float) -> Tuple[float, float]:
        return max(1.0, target_premium - tolerance_usd), target_premium + tolerance_usd

    @staticmethod
    def is_premium_in_band(price: float, target_premium: float, tolerance_usd: float) -> bool:
        lo, hi = OptionSelector.premium_band(target_premium, tolerance_usd)
        return lo <= price <= hi

    def _collect_side(
        self,
        instruments: List[Instrument],
        tickers_map: Dict[str, Ticker],
        spot_price: float,
        is_call: bool,
        min_acceptable_prem: float,
        max_acceptable_prem: float,
        target_premium: float,
    ) -> List[Tuple[Instrument, Ticker, float, float]]:
        candidates: List[Tuple[Instrument, Ticker, float, float]] = []
        side = "Call" if is_call else "Put"
        for inst in instruments:
            if inst.strike_price is None:
                continue
            if is_call and inst.strike_price <= spot_price:
                continue
            if not is_call and inst.strike_price >= spot_price:
                continue

            ticker = tickers_map.get(inst.symbol) or tickers_map.get(inst.instrument_id)
            if not ticker:
                continue

            prem = ticker.sell_premium
            if prem <= 0:
                self.logger.debug(
                    f"{side} strike {inst.strike_price} skipped: no bid "
                    f"(mark=${ticker.mark_price:.2f}, mid=${ticker.mid_price:.2f})"
                )
                continue

            if min_acceptable_prem <= prem <= max_acceptable_prem:
                candidates.append((inst, ticker, prem, abs(prem - target_premium)))
            else:
                self.logger.debug(
                    f"{side} strike {inst.strike_price} bid ${prem:.2f} outside "
                    f"[${min_acceptable_prem:.2f}-${max_acceptable_prem:.2f}] "
                    f"(mark=${ticker.mark_price:.2f})"
                )
        return candidates

    def select_strangle_legs(
        self,
        option_chain: OptionChain,
        tickers_map: Dict[str, Ticker],
        spot_price: float,
        target_premium: float = 100.0,
        tolerance_usd: float = 30.0,
    ) -> Tuple[Instrument, Ticker, Instrument, Ticker]:
        """
        Find best OTM Call and OTM Put contracts whose *sellable bid* is in band.

        Market sells fill at the bid, not mark/mid. Using mark selected a PE
        whose mark was $80.50 (in $70-$130) while the bid/fill was $64.
        """
        if spot_price <= 0:
            raise OptionSelectionError(f"Invalid underlying spot price: {spot_price}")

        min_acceptable_prem, max_acceptable_prem = self.premium_band(target_premium, tolerance_usd)

        call_candidates = self._collect_side(
            option_chain.calls, tickers_map, spot_price, True,
            min_acceptable_prem, max_acceptable_prem, target_premium,
        )
        put_candidates = self._collect_side(
            option_chain.puts, tickers_map, spot_price, False,
            min_acceptable_prem, max_acceptable_prem, target_premium,
        )

        if not call_candidates:
            raise OptionSelectionError(
                f"No OTM Call with sellable bid between ${min_acceptable_prem:.2f} and "
                f"${max_acceptable_prem:.2f} (Spot: ${spot_price:.2f})"
            )

        if not put_candidates:
            raise OptionSelectionError(
                f"No OTM Put with sellable bid between ${min_acceptable_prem:.2f} and "
                f"${max_acceptable_prem:.2f} (Spot: ${spot_price:.2f})"
            )

        call_candidates.sort(key=lambda x: x[3])
        put_candidates.sort(key=lambda x: x[3])

        best_call_inst, best_call_ticker, best_call_prem, _ = call_candidates[0]
        best_put_inst, best_put_ticker, best_put_prem, _ = put_candidates[0]

        self.logger.info(
            f"Selected CE: {best_call_inst.symbol} (Strike: {best_call_inst.strike_price}, "
            f"Sell bid: ${best_call_prem:.2f}, mark: ${best_call_ticker.mark_price:.2f}, "
            f"ask: ${best_call_ticker.best_ask:.2f})"
        )
        self.logger.info(
            f"Selected PE: {best_put_inst.symbol} (Strike: {best_put_inst.strike_price}, "
            f"Sell bid: ${best_put_prem:.2f}, mark: ${best_put_ticker.mark_price:.2f}, "
            f"ask: ${best_put_ticker.best_ask:.2f})"
        )

        return best_call_inst, best_call_ticker, best_put_inst, best_put_ticker
