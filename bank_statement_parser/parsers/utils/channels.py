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
    (
        "interest",
        re.compile(
            r"\bINT\.?\s*PAID\b|\bINT\.?\s*PD\b|\bINTEREST\b", re.IGNORECASE
        ),
    ),
    ("ach_credit", re.compile(r"\bACH[\s-]*C\b", re.IGNORECASE)),
    ("ach_debit", re.compile(r"\bACH[\s-]*D\b", re.IGNORECASE)),
    (
        "standing_instruction",
        re.compile(r"\bSI/|\bSTANDING\s*INSTRUCTION\b", re.IGNORECASE),
    ),
    ("emandate", re.compile(r"\bE-?MANDATE\b|\bENACH\b|\bNACH\b", re.IGNORECASE)),
    ("netbanking", re.compile(r"\bBIL\s*/\s*(?:INFT|ONL)\b", re.IGNORECASE)),
    ("netbanking", re.compile(r"\bNET[\s-]*BANKING\b", re.IGNORECASE)),
    ("netbanking", re.compile(r"\bCMS\s*TRANSACTION\b|^\s*CMS\b", re.IGNORECASE)),
    ("debit_card", re.compile(r"\bMCD\s+REF\b", re.IGNORECASE)),
    ("card", re.compile(r"\bPOS\b|\bCARD\b", re.IGNORECASE)),
]

# NEFT/RTGS UTR: 4-letter bank code + 1 alphanumeric (varies per bank) + 7+ digits.
# 7+ trailing digits (12+ char total) excludes 11-char IFSC codes like ABCD0000123
# that also appear in NEFT narrations.
_UTR_PATTERN = re.compile(r"\b([A-Z]{4}[A-Z0-9]\d{7,})\b")

# UPI/IMPS RRN: 12-digit numeric (occasionally longer, up to 22). Conservative —
# only matches the *first* well-bounded numeric run. Used only for channels where
# the narration is structured around the RRN (UPI, IMPS).
_DIGIT_RRN_PATTERN = re.compile(r"\b(\d{12,22})\b")

# Net banking ref: token #3 of `BIL/(INFT|ONL)/<ref>/...`. Alphanumeric, 6-20 chars.
_BIL_REF_PATTERN = re.compile(
    r"\bBIL\s*/\s*(?:INFT|ONL)\s*/\s*([A-Z0-9]{6,20})\b", re.IGNORECASE
)


def detect_channel(narration: str) -> str | None:
    """Detect transaction channel from narration text."""
    for channel, pattern in _CHANNEL_PATTERNS:
        if pattern.search(narration):
            return channel
    return None


def extract_reference_number(narration: str, channel: str | None = None) -> str | None:
    """Extract a reference/UTR number from narration text.

    Channel-aware so the right pattern wins:
    - NEFT/RTGS: alphanumeric UTR (bank code + digits). Falls back to digit RRN
      only if no UTR found, since some statements show UTR in a separate column.
    - UPI/IMPS: 12+ digit RRN.
    - Anything else (cheque, interest, NACH, unknown): no extraction. Picking up
      random digit runs from cheque numbers, dates, or account numbers causes
      false uniqueness collisions downstream.
    """
    ch = channel.lower() if channel else None

    if ch in {"neft", "rtgs"}:
        match = _UTR_PATTERN.search(narration)
        if match:
            return match.group(1)
        match = _DIGIT_RRN_PATTERN.search(narration)
        return match.group(1) if match else None

    if ch in {"upi", "imps"}:
        match = _DIGIT_RRN_PATTERN.search(narration)
        return match.group(1) if match else None

    if ch == "netbanking":
        match = _BIL_REF_PATTERN.search(narration)
        return match.group(1) if match else None

    return None


__all__ = [
    "MONTH_ABBREVS",
    "detect_channel",
    "extract_reference_number",
]
