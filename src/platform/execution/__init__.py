"""Platform execution package."""

__all__ = ["OrderExecutionPipeline"]


def __getattr__(name: str):
    if name == "OrderExecutionPipeline":
        from src.platform.execution.pipeline import OrderExecutionPipeline

        return OrderExecutionPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
