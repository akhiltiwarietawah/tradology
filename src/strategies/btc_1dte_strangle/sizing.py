"""Premium-based sizing and scaled combined take-profit."""


def effective_equity(wallet: float, virtual: float) -> float:
    wallet = max(0.0, float(wallet))
    virtual = max(0.0, float(virtual))
    if wallet > 0 and virtual > 0:
        return min(wallet, virtual)
    return wallet or virtual


def contracts_for_strangle(
    effective_usd: float,
    call_premium: float,
    put_premium: float,
    *,
    contract_value: float,
    margin_pct: float,
) -> int:
    budget = float(effective_usd) * float(margin_pct)
    per = (float(call_premium) + float(put_premium)) * float(contract_value)
    if budget <= 0 or per <= 0:
        return 0
    return max(0, int(budget // per))


def scaled_take_profit(n_contracts: int, *, base_usd: float, calibration_contracts: int) -> float:
    if n_contracts <= 0 or calibration_contracts <= 0:
        return base_usd
    return base_usd * (n_contracts / float(calibration_contracts))
