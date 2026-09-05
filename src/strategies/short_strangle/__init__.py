"""Short Strangle strategy package initialization."""

from src.strategies.short_strangle.models import ShortStrangleConfig
from src.strategies.short_strangle.selector import OptionSelector, OptionSelectionError
from src.strategies.short_strangle.strategy import BTCShortStrangleStrategy

__all__ = [
    "ShortStrangleConfig",
    "OptionSelector",
    "OptionSelectionError",
    "BTCShortStrangleStrategy",
]
