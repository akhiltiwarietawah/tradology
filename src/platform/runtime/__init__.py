"""Multi-user strategy runtime execution package."""

__all__ = ["StrategyRuntimeManager"]


def __getattr__(name: str):
    if name == "StrategyRuntimeManager":
        from src.platform.runtime.manager import StrategyRuntimeManager

        return StrategyRuntimeManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
