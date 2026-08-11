"""ICICI savings statement parser tests.

The word streams keep the real PDF layout geometry. The tests replace all
personal data, account numbers, references, and amounts with test values.
"""

from typing import Any

from bank_statement_parser.parsers.icici import IciciBankStatementParser


def _word(text: str, x0: float, doctop: float) -> dict[str, Any]:
    return {"text": text, "x0": x0, "x1": x0 + 10.0, "doctop": doctop}


def _build_last_page_words() -> list[dict[str, Any]]:
    """Page with header row, two UPI debits, then Total + post-txn sections.

    The second debit is the LAST transaction on the page — its narration
    must not absorb the trailing "Account Related Other Information"
    section or the table that follows it.
    """
    words: list[dict[str, Any]] = []

    # Header row
    y = 100.0
    for token, x in (
        ("DATE", 30.0),
        ("PARTICULARS", 140.0),
        ("DEPOSIT", 380.0),
        ("WITHDRAWAL", 460.0),
        ("BALANCE", 540.0),
    ):
        words.append(_word(token, x, y))

    # B/F opening row
    y = 120.0
    words.append(_word("01-04-2026", 30.0, y))
    words.append(_word("B/F", 140.0, y))
    words.append(_word("10,000.00", 540.0, y))

    # Txn 1 (not last) — narration above + date line + continuation
    y = 140.0
    words.append(_word("UPI/JOHN", 140.0, y))
    words.append(_word("DOE/8000000001@xyz/Paid/SOME", 200.0, y))
    y = 150.0
    words.append(_word("BANK", 140.0, y))
    y = 160.0
    words.append(_word("15-04-2026", 30.0, y))
    words.append(_word("L/100200300400/REF1234567890", 140.0, y))
    words.append(_word("500.00", 470.0, y))
    words.append(_word("9,500.00", 540.0, y))
    y = 170.0  # continuation fragment
    words.append(_word("XYZ/", 140.0, y))

    # Txn 2 (LAST) — narration above + date line + continuation
    y = 190.0
    words.append(_word("UPI/PIZZA", 140.0, y))
    words.append(_word("PLACE/9000000001@ybl/Sent", 200.0, y))
    words.append(_word("using/ACME", 320.0, y))
    y = 200.0
    words.append(_word("30-04-2026", 30.0, y))
    words.append(_word("BANK/200300400500/PAY1234567890ABCD", 140.0, y))
    words.append(_word("9.00", 475.0, y))
    words.append(_word("9,491.00", 540.0, y))
    y = 210.0  # legit continuation fragment of last narration
    words.append(_word("EFGHIJ", 140.0, y))

    # Total row — must terminate narration accumulation
    y = 230.0
    words.append(_word("Total:", 137.0, y))
    words.append(_word("0.00", 367.0, y))
    words.append(_word("509.00", 450.0, y))
    words.append(_word("9,491.00", 531.0, y))

    # POST-TRANSACTION SECTIONS (these were leaking into the last narration)
    y = 260.0
    for token, x in (
        ("Account", 28.0),
        ("Related", 61.0),
        ("Other", 92.0),
        ("Information", 115.0),
    ):
        words.append(_word(token, x, y))

    y = 280.0
    for token, x in (
        ("ACCOUNT", 31.0),
        ("TYPE", 70.0),
        ("ACCOUNT", 134.0),
        ("NUMBER", 173.0),
        ("MICR", 268.0),
        ("CODE", 289.0),
        ("IFS", 361.0),
        ("CODE", 374.0),
        ("NAME", 425.0),
        ("OF", 449.0),
        ("NOMINEE*", 461.0),
    ):
        words.append(_word(token, x, y))

    y = 300.0
    for token, x in (
        ("Savings", 31.0),
        ("XXXXXXXX9999", 134.0),
        ("100200300", 270.0),
        ("ACME0000123", 357.0),
        ("-", 425.0),
    ):
        words.append(_word(token, x, y))

    y = 320.0
    for token, x in (
        ("*", 28.0),
        ("Nominee", 33.0),
        ("name", 64.0),
        ("displayed", 84.0),
        ("only", 118.0),
        ("upon", 133.0),
        ("specific", 152.0),
        ("consent", 178.0),
        ("of", 206.0),
        ("the", 214.0),
        ("customer", 226.0),
    ):
        words.append(_word(token, x, y))

    # Page footer
    y = 600.0
    for token, x in (
        ("Page", 476.0),
        ("3", 492.0),
        ("of", 497.0),
        ("4", 504.0),
        ("M-99999999-99999", 509.0),
    ):
        words.append(_word(token, x, y))

    return words


def _build_raw_data() -> dict[str, Any]:
    words = _build_last_page_words()
    text_lines = [
        "DATE PARTICULARS DEPOSIT WITHDRAWAL BALANCE",
        "01-04-2026 B/F 10,000.00",
        "UPI/JOHN DOE/8000000001@xyz/Paid/SOME",
        "BANK",
        "15-04-2026 L/100200300400/REF1234567890 500.00 9,500.00",
        "XYZ/",
        "UPI/PIZZA PLACE/9000000001@ybl/Sent using/ACME",
        "30-04-2026 BANK/200300400500/PAY1234567890ABCD 9.00 9,491.00",
        "EFGHIJ",
        "Total: 0.00 509.00 9,491.00",
        "Account Related Other Information",
        "ACCOUNT TYPE ACCOUNT NUMBER MICR CODE IFS CODE NAME OF NOMINEE*",
        "Savings XXXXXXXX9999 100200300 ACME0000123 -",
        "* Nominee name displayed only upon specific consent of the customer",
        "Page 3 of 4 M-99999999-99999",
    ]
    full_text = (
        "Savings Account XXXXXXXX9999\n"
        "ACCOUNT HOLDERS: MR. SAMPLE NAME\n"
        "period April 01, 2026 - April 30, 2026\n" + "\n".join(text_lines)
    )
    return {
        "file": "synthetic_icici.pdf",
        "pages": [{"text": full_text, "words": words}],
    }


def _build_narration_partition_words() -> list[dict[str, Any]]:
    """Build rows that keep the real ICICI below-date and above-date geometry."""
    words: list[dict[str, Any]] = []

    def add_line(y: float, *tokens: tuple[str, float]) -> None:
        for text, x0 in tokens:
            words.append(_word(text, x0, y))

    # Two MOBILE BANKING credits. The particulars start below the date
    # baseline. The 4.24-point gap keeps each MMT line in the current row.
    add_line(
        1374.44,
        ("13-07-2026", 29.8),
        ("MOBILE", 71.0),
        ("BANKING", 94.2),
        ("1,200.00", 370.4),
        ("2,200.00", 526.8),
    )
    add_line(
        1378.68,
        ("MMT/IMPS/611111111111/Self", 136.3),
        ("transfer/SAMPLE", 236.7),
        ("PERSON/DEMO", 285.7),
        ("Bank", 324.1),
    )
    add_line(1382.92, ("SAMPLE", 136.3), ("PERSON", 158.0))

    add_line(
        1391.38,
        ("13-07-2026", 29.8),
        ("MOBILE", 71.0),
        ("BANKING", 94.2),
        ("800.00", 370.4),
        ("3,000.00", 526.8),
    )
    add_line(
        1395.62,
        ("MMT/IMPS/622222222222/Test/SAMPLE", 136.3),
        ("PERSON/DEMO", 261.9),
        ("Bank", 315.3),
    )

    # This row has inline particulars. Its continuation stays below. The
    # distant UPI line is nearer to the next bare date row. Assign it there.
    add_line(
        1405.51,
        ("13-07-2026", 29.8),
        ("BIL/INFT/TEST000001/", 136.3),
        ("SAMPLE", 211.5),
        ("PERSON", 238.1),
        ("500.00", 376.0),
        ("3,500.00", 526.8),
    )
    add_line(1409.75, ("SAMPLE", 136.3), ("PERSON", 161.0))
    add_line(
        1423.87,
        ("UPI/SAMPLE", 136.3),
        ("PERSON/633333333333@demo/Paid", 174.3),
        ("via", 263.7),
        ("DEMO", 275.0),
    )
    add_line(
        1428.11,
        ("14-07-2026", 29.8),
        ("100.00", 385.0),
        ("3,600.00", 526.8),
    )

    return words


def test_last_transaction_narration_does_not_absorb_post_txn_section() -> None:
    parsed = IciciBankStatementParser().parse(_build_raw_data())

    assert len(parsed.transactions) == 2, [t.narration for t in parsed.transactions]
    last = parsed.transactions[-1]

    assert last.amount == "9.00"
    assert last.transaction_type == "debit"
    assert last.reference_number == "200300400500"

    leaked_phrases = (
        "Account Related",
        "ACCOUNT TYPE",
        "MICR CODE",
        "Nominee",
        "ICIC0000",
        "ACME0000123",
        "Savings XXXXXXXX",
    )
    for phrase in leaked_phrases:
        assert phrase not in last.narration, (
            f"Post-transaction section text {phrase!r} leaked into last "
            f"narration: {last.narration!r}"
        )

    # And the legitimate narration content should still be present
    assert "PIZZA" in last.narration
    assert "PAY1234567890ABCD" in last.narration

    # Counterparty must be the merchant segment, not the full UPI narration
    assert last.counterparty == "PIZZA PLACE"
    assert parsed.transactions[0].counterparty == "JOHN DOE"


def test_synthetic_statement_reconciles() -> None:
    parsed = IciciBankStatementParser().parse(_build_raw_data())
    assert parsed.reconciliation is not None
    assert parsed.reconciliation.balance_delta == "0.00"
    assert parsed.reconciliation.reconciled is True


def test_narration_is_partitioned_by_nearest_date_baseline() -> None:
    parser = IciciBankStatementParser()
    transactions, _ = parser._parse_icici_page(_build_narration_partition_words())

    assert [transaction.reference_number for transaction in transactions] == [
        "611111111111",
        "622222222222",
        "TEST000001",
        "633333333333",
    ]
    assert [transaction.amount for transaction in transactions] == [
        "1,200.00",
        "800.00",
        "500.00",
        "100.00",
    ]
    assert "MMT/IMPS/611111111111" in transactions[0].narration
    assert "MMT/IMPS/622222222222" in transactions[1].narration
    assert "UPI/SAMPLE" not in transactions[2].narration
    assert transactions[3].narration.startswith("UPI/SAMPLE")


def _build_linked_fd_section_words() -> list[dict[str, Any]]:
    """Build a savings row, its ``Total:`` line, then a Linked FD section.

    ICICI adds the FD section after the savings ``Total:``. The FD section has
    date rows for a different account. The parser must not read these rows as
    savings transactions. The FD balance would then replace the savings closing
    balance and break the reconciliation.
    """
    words: list[dict[str, Any]] = []

    y = 100.0
    for token, x in (
        ("DATE", 30.0),
        ("MODE", 71.0),
        ("PARTICULARS", 140.0),
        ("DEPOSITS", 380.0),
        ("WITHDRAWALS", 455.0),
        ("BALANCE", 540.0),
    ):
        words.append(_word(token, x, y))

    # B/F opening. The account, amount, and date values are fabricated.
    y = 120.0
    words += [_word("01-01-2020", 30.0, y), _word("B/F", 140.0, y), _word("1,000.00", 540.0, y)]

    # One savings credit: 1,000.00 + 250.00 = 1,250.00.
    y = 140.0
    words += [
        _word("15-01-2020", 30.0, y),
        _word("999999999999:Int.Pd", 140.0, y),
        _word("250.00", 385.0, y),
        _word("1,250.00", 540.0, y),
    ]

    # Savings grand total. This line is the section boundary.
    y = 160.0
    words += [
        _word("Total:", 137.0, y),
        _word("250.00", 367.0, y),
        _word("0.00", 450.0, y),
        _word("1,250.00", 531.0, y),
    ]

    # Linked Fixed Deposits section header and its date rows. The account id
    # and amounts are fabricated FD-side values. The parser must exclude them
    # from the savings statement.
    y = 180.0
    for token, x in (
        ("Statement", 136.0),
        ("of", 176.0),
        ("Linked", 190.0),
        ("Fixed", 220.0),
        ("Deposits", 246.0),
    ):
        words.append(_word(token, x, y))
    y = 200.0
    words += [_word("888888888888", 136.0, y), _word("NEW", 240.0, y), _word("ACCOUNT", 265.0, y)]
    y = 220.0
    words += [
        _word("09-01-2020", 30.0, y),
        _word("TRF", 140.0, y),
        _word("FROM", 165.0, y),
        _word("SB", 195.0, y),
        _word("50,000.00", 380.0, y),
        _word("50,000.00", 540.0, y),
    ]

    return words


def test_linked_fd_section_is_not_parsed_as_savings() -> None:
    parser = IciciBankStatementParser()
    transactions, _opening = parser._parse_icici_page(_build_linked_fd_section_words())

    # Keep only the one savings row. Exclude the FD row after the Total.
    assert [t.amount for t in transactions] == ["250.00"], [t.narration for t in transactions]
    assert transactions[-1].balance == "1,250.00"
