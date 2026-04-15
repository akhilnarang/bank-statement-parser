"""Shared channel, reference, and month helpers."""

from __future__ import annotations

import re

MONTH_ABBREVS = {
    "JAN": "01",
    "FEB": "02",
    "MAR": "03",
    "APR": "04",
    "MAY": "05",
    "JUN": "06",
    "JUL": "07",
    "AUG": "08",
    "SEP": "09",
    "OCT": "10",
    "NOV": "11",
    "DEC": "12",
}

_CHANNEL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("upi", re.compile(r"\bUPI\b", re.IGNORECASE)),
    ("neft", re.compile(r"\bNEFT\b", re.IGNORECASE)),
    ("rtgs", re.compile(r"\bRTGS\b", re.IGNORECASE)),
    ("imps", re.compile(r"\bIMPS\b", re.IGNORECASE)),
    ("atm", re.compile(r"\bATM\b", re.IGNORECASE)),
    ("atm", re.compile(r"\bCASH\s*W/?D", re.IGNORECASE)),
    ("cash_deposit", re.compile(r"\bCASH\s*DEP", re.IGNORECASE)),
    ("cheque", re.compile(r"\bCHQ\b|\bCHEQUE\b", re.IGNORECASE)),
    ("interest", re.compile(r"\bINT\.?\s*PAID\b|\bINTEREST\b", re.IGNORECASE)),
    ("ach_credit", re.compile(r"\bACH[\s-]*C\b", re.IGNORECASE)),
    ("ach_debit", re.compile(r"\bACH[\s-]*D\b", re.IGNORECASE)),
    (
        "standing_instruction",
        re.compile(r"\bSI/|\bSTANDING\s*INSTRUCTION\b", re.IGNORECASE),
    ),
    ("emandate", re.compile(r"\bE-?MANDATE\b|\bENACH\b|\bNACH\b", re.IGNORECASE)),
    ("netbanking", re.compile(r"\bNET[\s-]*BANKING\b", re.IGNORECASE)),
    ("card", re.compile(r"\bPOS\b|\bCARD\b", re.IGNORECASE)),
]

_REF_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(\d{12,22})\b"),
]


def detect_channel(narration: str) -> str | None:
    """Detect transaction channel from narration text."""
    for channel, pattern in _CHANNEL_PATTERNS:
        if pattern.search(narration):
            return channel
    return None


def extract_reference_number(narration: str) -> str | None:
    """Extract a reference/UTR number from narration text."""
    for pattern in _REF_PATTERNS:
        match = pattern.search(narration)
        if match:
            return match.group(1)
    return None


__all__ = [
    "MONTH_ABBREVS",
    "detect_channel",
    "extract_reference_number",
]
