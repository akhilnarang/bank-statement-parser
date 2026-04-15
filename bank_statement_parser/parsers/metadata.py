"""Shared statement metadata extraction helpers."""

from __future__ import annotations

import re
from typing import TypeAlias

from bank_statement_parser.parsers.utils import parse_date_text

Metadata: TypeAlias = dict[str, str | None]

_DEFAULT_ACCOUNT_NUMBER_RE = re.compile(
    r"(?:A/?C|ACCOUNT)\s*(?:NO\.?|NUMBER|#)\s*:?\s*(\d[\dX*\s]{6,20}\d)",
    re.IGNORECASE,
)
_DEFAULT_PERIOD_RE = re.compile(
    r"(?:STATEMENT\s+(?:OF|FOR)\s+(?:THE\s+)?(?:PERIOD|MONTH)?\s*"
    r"(?:FROM|:)?\s*)?"
    r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})\s*(?:TO|[-–])\s*(\d{2}[/\-]\d{2}[/\-]\d{2,4})",
    re.IGNORECASE,
)
_DEFAULT_OPENING_BALANCE_RE = re.compile(
    r"OPENING\s+BALANCE\s*:?\s*([\d,]+\.\d{2})",
    re.IGNORECASE,
)
_DEFAULT_CLOSING_BALANCE_RE = re.compile(
    r"CLOSING\s+BALANCE\s*:?\s*([\d,]+\.\d{2})",
    re.IGNORECASE,
)
_DEFAULT_NAME_RE = re.compile(
    r"(?:ACCOUNT\s+HOLDER|CUSTOMER\s+NAME|NAME)\s*:?\s*(.+)",
    re.IGNORECASE,
)


class MetadataExtractor:
    """Regex-based metadata extractor with override-friendly hooks."""

    account_number_pattern: re.Pattern[str] | None = _DEFAULT_ACCOUNT_NUMBER_RE
    period_pattern: re.Pattern[str] | None = _DEFAULT_PERIOD_RE
    opening_balance_pattern: re.Pattern[str] | None = _DEFAULT_OPENING_BALANCE_RE
    closing_balance_pattern: re.Pattern[str] | None = _DEFAULT_CLOSING_BALANCE_RE
    name_pattern: re.Pattern[str] | None = _DEFAULT_NAME_RE

    def extract_account_number(self, full_text: str) -> str | None:
        if self.account_number_pattern is None:
            return None
        match = self.account_number_pattern.search(full_text)
        if not match:
            return None
        return re.sub(r"\s+", "", match.group(1))

    def extract_account_holder_name(self, full_text: str) -> str | None:
        if self.name_pattern is None:
            return None
        match = self.name_pattern.search(full_text)
        if not match:
            return None
        name = match.group(1).strip()
        name = re.split(r"\s{2,}|\t|\n", name)[0].strip()
        return name or None

    def extract_period(self, full_text: str) -> tuple[str | None, str | None]:
        if self.period_pattern is None:
            return None, None
        match = self.period_pattern.search(full_text)
        if not match:
            return None, None
        return (
            parse_date_text(match.group(1)),
            parse_date_text(match.group(2)),
        )

    def extract_opening_balance(self, full_text: str) -> str | None:
        if self.opening_balance_pattern is None:
            return None
        match = self.opening_balance_pattern.search(full_text)
        return match.group(1) if match else None

    def extract_closing_balance(self, full_text: str) -> str | None:
        if self.closing_balance_pattern is None:
            return None
        match = self.closing_balance_pattern.search(full_text)
        return match.group(1) if match else None

    def extract(self, full_text: str) -> Metadata:
        period_start, period_end = self.extract_period(full_text)
        return {
            "account_number": self.extract_account_number(full_text),
            "account_holder_name": self.extract_account_holder_name(full_text),
            "period_start": period_start,
            "period_end": period_end,
            "opening_balance": self.extract_opening_balance(full_text),
            "closing_balance": self.extract_closing_balance(full_text),
        }


def extract_metadata(
    full_text: str,
    extractor: MetadataExtractor | None = None,
) -> Metadata:
    """Extract statement metadata using the provided extractor."""
    return (extractor or MetadataExtractor()).extract(full_text)


__all__ = ["Metadata", "MetadataExtractor", "extract_metadata"]
