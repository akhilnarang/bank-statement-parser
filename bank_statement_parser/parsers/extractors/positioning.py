"""Helpers for x-position based parser layouts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ColumnThresholds:
    """Named x-position thresholds for word-positioned parsers."""

    date_max: float | None = None
    deposit_max: float | None = None
    withdrawal_max: float | None = None
    ref_min: float | None = None
    amount_min: float | None = None
    balance_min: float | None = None


__all__ = ["ColumnThresholds"]
