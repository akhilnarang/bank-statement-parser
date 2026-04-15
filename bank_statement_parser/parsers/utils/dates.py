"""Date parsing helpers backed by python-dateutil."""

from __future__ import annotations

import re
from datetime import date, datetime

from dateutil import parser as date_parser

_DEFAULT_FORMAT_HINTS = (
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%d %b %y",
    "%d %b %Y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %B %Y",
    "%B %d, %Y",
)


def _normalize_token(token: str) -> str:
    normalized = token.strip().replace("’", "'").replace("`", "")
    normalized = re.sub(r"(?<=\s)'(\d{2})(?=\b)", r"\1", normalized)
    return re.sub(r"\s+", " ", normalized)


def format_date(value: date) -> str:
    """Format a date as DD/MM/YYYY."""
    return value.strftime("%d/%m/%Y")


def parse_date(
    token: str,
    dayfirst: bool = True,
    format_hints: list[str] | None = None,
) -> date | None:
    """Parse a date token using explicit hints first, then dateutil."""
    normalized = _normalize_token(token)
    if not normalized:
        return None

    for hint in [*(format_hints or []), *_DEFAULT_FORMAT_HINTS]:
        try:
            return datetime.strptime(normalized, hint).date()
        except ValueError:
            continue

    try:
        return date_parser.parse(
            normalized,
            dayfirst=dayfirst,
            fuzzy=False,
            default=datetime(2000, 1, 1),
        ).date()
    except ValueError, OverflowError, TypeError:
        return None


def parse_date_text(
    token: str,
    dayfirst: bool = True,
    format_hints: list[str] | None = None,
) -> str | None:
    """Parse and format a date token as DD/MM/YYYY."""
    parsed = parse_date(token, dayfirst=dayfirst, format_hints=format_hints)
    return format_date(parsed) if parsed else None


def parse_multi_token_date(
    tokens: list[str],
    start: int,
) -> tuple[str | None, int]:
    """Parse a DD Mon YY/YYYY date spread across tokens."""
    if start + 2 >= len(tokens):
        return None, 0

    candidate = " ".join(tokens[start : start + 3])
    parsed = parse_date_text(
        candidate,
        dayfirst=True,
        format_hints=["%d %b %y", "%d %b %Y"],
    )
    return (parsed, 3) if parsed else (None, 0)


__all__ = [
    "format_date",
    "parse_date",
    "parse_date_text",
    "parse_multi_token_date",
]
