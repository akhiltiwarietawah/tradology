"""SQLAlchemy ORM models for trades, legs, orders, and fills."""

from decimal import Decimal
from datetime import datetime, date
from typing import List, Optional, Dict, Any

from sqlalchemy import (
    String,
    Numeric,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


class TradeModel(Base):
    """ORM model representing a strategy trade."""
    __tablename__ = "trades"

    trade_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False, default="delta_india")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entry_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    total_entry_premium: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=Decimal("0.0000"))
    total_exit_premium: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=Decimal("0.0000"))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=Decimal("0.0000"))
    total_fees: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=Decimal("0.0000"))
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=Decimal("0.0000"))
    exit_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    strategy_config: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Relationships
    legs: Mapped[List["TradeLegModel"]] = relationship("TradeLegModel", back_populates="trade", cascade="all, delete-orphan")
    orders: Mapped[List["OrderModel"]] = relationship("OrderModel", back_populates="trade")

    def __repr__(self) -> str:
        return f"<TradeModel(trade_id='{self.trade_id}', date='{self.trade_date}', status='{self.status}', net_pnl={self.net_pnl})>"


class TradeLegModel(Base):
    """ORM model representing an individual option leg (CE or PE)."""
    __tablename__ = "trade_legs"

    leg_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(64), ForeignKey("trades.trade_id", ondelete="CASCADE"), nullable=False, index=True)
    leg_type: Mapped[str] = mapped_column(String(8), nullable=False)  # 'CE' or 'PE'
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    strike: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="sell")
    entry_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 4), nullable=True)
    exit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 4), nullable=True)
    entry_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stop_loss_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 4), nullable=True)
    bracket_order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=Decimal("0.0000"))
    fees: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=Decimal("0.0000"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Relationships
    trade: Mapped["TradeModel"] = relationship("TradeModel", back_populates="legs")
    orders: Mapped[List["OrderModel"]] = relationship("OrderModel", back_populates="leg")

    def __repr__(self) -> str:
        return f"<TradeLegModel(leg_id='{self.leg_id}', type='{self.leg_type}', symbol='{self.symbol}', status='{self.status}')>"


class OrderModel(Base):
    """ORM model representing an exchange order."""
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trade_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("trades.trade_id", ondelete="SET NULL"), nullable=True, index=True)
    trade_leg_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("trade_legs.leg_id", ondelete="SET NULL"), nullable=True, index=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False, default="delta_india")
    exchange_order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    client_order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False)
    filled_quantity: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=Decimal("0.0000"))
    average_fill_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reduce_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Relationships
    trade: Mapped[Optional["TradeModel"]] = relationship("TradeModel", back_populates="orders")
    leg: Mapped[Optional["TradeLegModel"]] = relationship("TradeLegModel", back_populates="orders")
    fills: Mapped[List["FillModel"]] = relationship("FillModel", back_populates="order", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<OrderModel(order_id='{self.order_id}', symbol='{self.symbol}', side='{self.side}', status='{self.status}')>"


class FillModel(Base):
    """ORM model representing an execution fill."""
    __tablename__ = "fills"

    fill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False, index=True)
    exchange_fill_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=Decimal("0.0000"))
    fee_currency: Mapped[str] = mapped_column(String(16), nullable=False, default="USD")
    fill_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Relationships
    order: Mapped["OrderModel"] = relationship("OrderModel", back_populates="fills")

    def __repr__(self) -> str:
        return f"<FillModel(fill_id='{self.fill_id}', order_id='{self.order_id}', price={self.price}, qty={self.quantity})>"
