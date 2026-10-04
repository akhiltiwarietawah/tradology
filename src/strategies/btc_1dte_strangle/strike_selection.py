"""Strike selection aligned with btc-backtest 1-DTE strangle (ref straddle + 1.8× wings)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from src.core.models.instrument import Instrument, OptionChain
from src.core.models.market_data import Ticker
from src.strategies.btc_1dte_strangle.models import Btc1DteStrangleConfig


class StrikeSelectionError(Exception):
    pass


def nearest_listed(price: float, strikes: List[float]) -> float:
    return min(strikes, key=lambda k: abs(float(k) - float(price)))


def choose_strikes(
    spot: float,
    atm_straddle: float,
    strikes: List[float],
    distance_mult: float,
) -> Tuple[float, float, float]:
    dist = atm_straddle * distance_mult
    listed = sorted({float(x) for x in strikes})
    atm = nearest_listed(spot, listed)
    above = [k for k in listed if k > max(spot, atm)]
    below = [k for k in listed if k < min(spot, atm)]
    call_k = nearest_listed(spot + dist, above or listed)
    put_k = nearest_listed(spot - dist, below or listed)
    if call_k <= spot and above:
        call_k = above[0]
    if put_k >= spot and below:
        put_k = below[-1]
    return atm, float(call_k), float(put_k)


def iter_reference_strike_pairs(spot: float, strikes: List[float]) -> List[Tuple[float, float]]:
    listed = sorted({float(x) for x in strikes})
    if not listed:
        return []
    atm = nearest_listed(spot, listed)
    ia = listed.index(atm)
    out: List[Tuple[float, float]] = []
    seen: set[Tuple[float, float]] = set()

    def add(ck: float, pk: float) -> None:
        t = (float(ck), float(pk))
        if t in seen or t[0] < t[1]:
            return
        seen.add(t)
        out.append(t)

    add(atm, atm)
    max_off = min(10, len(listed))
    for off_c in range(max_off):
        for off_p in range(max_off):
            if off_c == 0 and off_p == 0:
                continue
            ic = min(ia + off_c, len(listed) - 1)
            ip = max(ia - off_p, 0)
            add(listed[ic], listed[ip])
    return out


def iter_tradable_wing_pairs(
    spot: float,
    straddle: float,
    strikes: List[float],
    distance_mult: float,
) -> List[Tuple[float, float]]:
    _, tgt_call, tgt_put = choose_strikes(spot, straddle, strikes, distance_mult)
    listed = sorted({float(x) for x in strikes})
    call_ks = [k for k in listed if k >= tgt_call]
    put_ks = [k for k in listed if k <= tgt_put]
    if not call_ks:
        call_ks = [k for k in listed if k > spot] or listed[-3:]
    if not put_ks:
        put_ks = [k for k in listed if k < spot] or listed[:3]
    pairs: List[Tuple[float, float]] = []
    seen: set[Tuple[float, float]] = set()
    for ck in call_ks:
        for pk in put_ks:
            if ck <= pk or ck < tgt_call or pk > tgt_put:
                continue
            t = (float(ck), float(pk))
            if t in seen:
                continue
            seen.add(t)
            pairs.append(t)
    pairs.sort(key=lambda t: abs(t[0] - tgt_call) + abs(t[1] - tgt_put))
    return pairs


def _strike_index(instruments: List[Instrument], strike: float) -> Optional[Instrument]:
    for inst in instruments:
        if inst.strike_price is None:
            continue
        if abs(float(inst.strike_price) - float(strike)) < 0.01:
            return inst
    return None


def _sell_premium(tickers_map: Dict[str, Ticker], inst: Instrument) -> float:
    ticker = tickers_map.get(inst.symbol) or tickers_map.get(inst.instrument_id)
    if not ticker:
        return 0.0
    prem = ticker.sell_premium
    if prem and prem > 0:
        return float(prem)
    if ticker.best_bid and ticker.best_bid > 0:
        return float(ticker.best_bid)
    return 0.0


def select_1dte_strangle_legs(
    *,
    option_chain: OptionChain,
    tickers_map: Dict[str, Ticker],
    spot_price: float,
    config: Btc1DteStrangleConfig,
) -> Tuple[Instrument, Ticker, float, Instrument, Ticker, float, float]:
    """Pick reference straddle then OTM wings with live bids."""
    if spot_price <= 0:
        raise StrikeSelectionError(f"Invalid spot: {spot_price}")

    strikes = sorted(
        {
            float(i.strike_price)
            for i in option_chain.calls + option_chain.puts
            if i.strike_price is not None
        }
    )
    if not strikes:
        raise StrikeSelectionError("Empty option chain")

    straddle = None
    ref_ck = ref_pk = None
    for rck, rpk in iter_reference_strike_pairs(spot_price, strikes):
        ce_ref = _strike_index(option_chain.calls, rck)
        pe_ref = _strike_index(option_chain.puts, rpk)
        if not ce_ref or not pe_ref:
            continue
        rc_prem = _sell_premium(tickers_map, ce_ref)
        rp_prem = _sell_premium(tickers_map, pe_ref)
        if rc_prem <= 0 or rp_prem <= 0:
            continue
        straddle = rc_prem + rp_prem
        ref_ck, ref_pk = rck, rpk
        break

    if straddle is None or ref_ck is None or ref_pk is None:
        raise StrikeSelectionError("No reference straddle with two-sided bids in entry window")

    wing_pairs = iter_tradable_wing_pairs(spot_price, straddle, strikes, config.straddle_distance_mult)

    for ck, pk in wing_pairs:
        ce_inst = _strike_index(option_chain.calls, ck)
        pe_inst = _strike_index(option_chain.puts, pk)
        if not ce_inst or not pe_inst:
            continue
        if ce_inst.strike_price and ce_inst.strike_price <= spot_price:
            continue
        if pe_inst.strike_price and pe_inst.strike_price >= spot_price:
            continue
        ce_prem = _sell_premium(tickers_map, ce_inst)
        pe_prem = _sell_premium(tickers_map, pe_inst)
        if ce_prem < config.min_otm_premium_usd or pe_prem < config.min_otm_premium_usd:
            continue
        ce_tick = tickers_map.get(ce_inst.symbol) or tickers_map.get(ce_inst.instrument_id)
        pe_tick = tickers_map.get(pe_inst.symbol) or tickers_map.get(pe_inst.instrument_id)
        if not ce_tick or not pe_tick:
            continue
        return ce_inst, ce_tick, straddle, pe_inst, pe_tick, float(ck), float(pk)

    raise StrikeSelectionError(
        f"No tradable OTM wing pair (min prem ${config.min_otm_premium_usd:.0f}, straddle=${straddle:.2f})"
    )
