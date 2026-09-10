"""Frozen entry/exit rules. Evaluated only on a confirmed brick + its Ichimoku snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from src.strategies.renko_ichimoku.ichimoku import IchimokuSnapshot
from src.strategies.renko_ichimoku.renko import ConfirmedBrick


@dataclass(frozen=True)
class SignalAction:
    kind: str  # exit_long | exit_short | enter_long | enter_short
    reason: str


def long_entry(brick: ConfirmedBrick, ich: IchimokuSnapshot) -> bool:
    return (
        ich.ready
        and brick.direction == 1
        and ich.above_cloud
        and ich.above_kijun
    )


def short_entry(brick: ConfirmedBrick, ich: IchimokuSnapshot) -> bool:
    return (
        ich.ready
        and brick.direction == -1
        and ich.below_cloud
        and ich.below_kijun
    )


def long_exit(ich: IchimokuSnapshot) -> bool:
    return ich.ready and ich.inside_cloud


def short_exit(ich: IchimokuSnapshot) -> bool:
    return ich.ready and ich.at_or_above_kijun


def evaluate_confirmed_brick(position: int, brick: ConfirmedBrick, ich: IchimokuSnapshot) -> List[SignalAction]:
    """position: 1 long, -1 short, 0 flat.

    Exit first, then opposite entry on the same confirmed brick if applicable.
    Never uses unconfirmed / future bricks — caller must pass only confirmed data.
    """
    if not ich.ready:
        return []

    want_long = long_entry(brick, ich)
    want_short = short_entry(brick, ich)
    actions: List[SignalAction] = []

    if position == 1 and long_exit(ich):
        actions.append(SignalAction("exit_long", "long_exit_inside_cloud"))
        if want_short:
            actions.append(SignalAction("enter_short", "short_entry_after_long_exit"))
        return actions

    if position == -1 and short_exit(ich):
        actions.append(SignalAction("exit_short", "short_exit_at_or_above_kijun"))
        if want_long:
            actions.append(SignalAction("enter_long", "long_entry_after_short_exit"))
        return actions

    if position == 0:
        if want_long:
            actions.append(SignalAction("enter_long", "long_entry"))
        elif want_short:
            actions.append(SignalAction("enter_short", "short_entry"))
    return actions
