"""Amount parsing helpers shared across parsers."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

AMOUNT_RE = re.compile(r"[-+]?\d[\d,]*\.\d{2}")


def parse_amount(value: str) -> Decimal:
    """Convert an amount string to Decimal (0 on failure)."""
    cleaned = value.replace(",", "").replace("`", "").replace("₹", "").strip()
    cleaned = re.sub(r"\s*(Cr|Dr|CR|DR|C|D)\.?\s*$", "", cleaned)
    try:
        return Decimal(cleaned)
    except InvalidOperation, ValueError:
        return Decimal("0")


def format_amount(value: Decimal) -> str:
    """Format Decimal as comma-separated 2-decimal string."""
    return f"{value:,.2f}"


def extract_amount(token: str) -> str | None:
    """Extract a decimal amount string from a token."""
    cleaned = token.replace("`", "").replace("₹", "").strip()
    match = AMOUNT_RE.search(cleaned)
    return match.group(0) if match else None


__all__ = [
    "AMOUNT_RE",
    "extract_amount",
    "format_amount",
    "parse_amount",
]
