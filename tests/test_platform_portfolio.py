"""Tests for platform portfolio performance aggregation."""

from __future__ import annotations

import uuid

import pytest

from src.platform.portfolio_service import PortfolioService


def test_merge_equity_curves_sums_by_timestamp():
    curves = [
        [{"timestamp": "2026-01-01T00:00:00+00:00", "equity": 100}],
        [{"timestamp": "2026-01-01T00:00:00+00:00", "equity": 50}],
    ]
    merged = PortfolioService._merge_equity_curves(curves)
    assert len(merged) == 1
    assert merged[0]["equity"] == 150


def test_curve_metrics_not_available_with_single_point():
    metrics = PortfolioService._curve_metrics([{"timestamp": "t", "equity": 100}])
    assert metrics["available"] is False


def test_curve_metrics_computes_return_and_drawdown():
    points = [
        {"timestamp": "2026-01-01", "equity": 100},
        {"timestamp": "2026-01-02", "equity": 110},
        {"timestamp": "2026-01-03", "equity": 99},
    ]
    metrics = PortfolioService._curve_metrics(points)
    assert metrics["available"] is True
    assert metrics["pnl"] == pytest.approx(-1)
    assert metrics["return_pct"] == pytest.approx(-0.01)
    assert metrics["max_drawdown_pct"] >= 0
