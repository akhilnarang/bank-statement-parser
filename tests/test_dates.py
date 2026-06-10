"""Date parsing guard tests.

Bare numeric tokens must not be coerced into dates (they would otherwise
misclassify narration tokens as transaction date lines). Real statement
date formats must still parse. All values are synthetic.
"""

import pytest

from bank_statement_parser.parsers.utils.dates import parse_date_text


@pytest.mark.parametrize("token", ["12", "2026", "1234", "007", "0", "99", "foo"])
def test_bare_numbers_and_junk_are_not_dates(token: str) -> None:
    assert parse_date_text(token) is None


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("01/04/2026", "01/04/2026"),
        ("01-04-2026", "01/04/2026"),
        ("01/04/26", "01/04/2026"),
        ("01-04-26", "01/04/2026"),
        ("15-Apr-2026", "15/04/2026"),
        ("02 May 2026", "02/05/2026"),
        ("02 May 26", "02/05/2026"),
        ("April 01, 2026", "01/04/2026"),
    ],
)
def test_real_formats_still_parse(token: str, expected: str) -> None:
    assert parse_date_text(token) == expected


def test_separator_only_dates_are_accepted() -> None:
    # Dotted separator variant should still reach the dateutil fallback.
    assert parse_date_text("1.4.26") == "01/04/2026"
