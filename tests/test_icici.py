"""ICICI savings statement parser tests.

Synthetic word streams modelled after real PDF layouts. No real personal
data — names, account numbers, refs, and amounts are fabricated.
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


def _build_embedded_amount_raw_data() -> dict[str, Any]:
    """Date line whose PARTICULARS token embeds an amount-like substring.

    ICICI narrations contain fragments like
    "SENDER/707070/UBI/01.02.2099..." where the "01.02" reads as an amount.
    Such a token sits in the PARTICULARS column (x≈140), NOT an amount
    column, and must be kept as narration — never consumed as an amount.

    All values below are fabricated, not drawn from any real statement.
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
    words.append(_word("11,111.00", 540.0, y))

    # Credit whose narration token carries an embedded "01.02" date fragment
    y = 140.0
    words.append(_word("15-04-2026", 30.0, y))
    words.append(_word("SENDER/707070/UBI/01.02.2099445566778899001122", 140.0, y))
    words.append(_word("7,777.00", 380.0, y))
    words.append(_word("18,888.00", 540.0, y))
    y = 150.0  # continuation fragment
    words.append(_word("987654321098", 140.0, y))

    full_text = (
        "Savings Account XXXXXXXX9999\n"
        "ACCOUNT HOLDERS: MR. SAMPLE NAME\n"
        "period April 01, 2026 - April 30, 2026\n"
        "DATE PARTICULARS DEPOSIT WITHDRAWAL BALANCE\n"
        "01-04-2026 B/F 11,111.00\n"
        "15-04-2026 SENDER/707070/UBI/01.02.2099445566778899001122 7,777.00 18,888.00\n"
        "987654321098\n"
    )
    return {
        "file": "synthetic_icici_embedded_amount.pdf",
        "pages": [{"text": full_text, "words": words}],
    }


def test_narration_token_with_embedded_amount_is_not_dropped() -> None:
    parsed = IciciBankStatementParser().parse(_build_embedded_amount_raw_data())

    assert len(parsed.transactions) == 1, [t.narration for t in parsed.transactions]
    txn = parsed.transactions[0]

    assert txn.transaction_type == "credit"
    assert txn.amount == "7,777.00"
    assert txn.balance == "18,888.00"
    # The PARTICULARS token must survive as narration, not be eaten as an amount.
    assert "SENDER/707070/UBI" in txn.narration, txn.narration
    assert "987654321098" in txn.narration, txn.narration


def _build_clg_clearing_raw_data() -> dict[str, Any]:
    """A cheque-clearing whose narration starts on the line ABOVE its date.

    ICICI clearing narrations begin with a "CLG/<name>" line rendered one
    visual line above the date row (like UPI/NEFT/etc.). That line must
    attach to the clearing transaction below it, NOT the preceding row.

    All values below are fabricated, not drawn from any real statement.
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
    words.append(_word("44,000.00", 540.0, y))

    # Txn A — a transfer with its own below-continuation fragment
    y = 140.0
    words.append(_word("14-04-2026", 30.0, y))
    words.append(_word("BIL/INFT/EKI0000001/Gift/", 140.0, y))
    words.append(_word("8,800.00", 380.0, y))
    words.append(_word("52,800.00", 540.0, y))
    y = 150.0  # genuine continuation of Txn A
    words.append(_word("zz99", 140.0, y))

    # Txn B — cheque clearing: narration starts on the line ABOVE the date row
    y = 160.0
    words.append(_word("CLG/PAYEE NAME", 140.0, y))
    y = 170.0
    words.append(_word("15-04-2026", 30.0, y))
    words.append(_word("PAYER/636363/HDF/02.03.2099889900112233", 140.0, y))
    words.append(_word("3,300.00", 380.0, y))
    words.append(_word("56,100.00", 540.0, y))
    y = 180.0  # below-continuation of Txn B
    words.append(_word("778899001122", 140.0, y))

    full_text = (
        "Savings Account XXXXXXXX9999\n"
        "ACCOUNT HOLDERS: MR. SAMPLE NAME\n"
        "period April 01, 2026 - April 30, 2026\n"
        "DATE PARTICULARS DEPOSIT WITHDRAWAL BALANCE\n"
        "01-04-2026 B/F 44,000.00\n"
        "14-04-2026 BIL/INFT/EKI0000001/Gift/ 8,800.00 52,800.00\n"
        "zz99\n"
        "CLG/PAYEE NAME\n"
        "15-04-2026 PAYER/636363/HDF/02.03.2099889900112233 3,300.00 56,100.00\n"
        "778899001122\n"
    )
    return {
        "file": "synthetic_icici_clg.pdf",
        "pages": [{"text": full_text, "words": words}],
    }


def test_clg_clearing_narration_attaches_to_its_own_transaction() -> None:
    parsed = IciciBankStatementParser().parse(_build_clg_clearing_raw_data())

    assert len(parsed.transactions) == 2, [t.narration for t in parsed.transactions]
    txn_a, txn_b = parsed.transactions

    # The CLG line belongs to the clearing (Txn B), not the preceding transfer.
    assert "CLG/PAYEE NAME" not in txn_a.narration, txn_a.narration
    assert "BIL/INFT/EKI0000001" in txn_a.narration, txn_a.narration
    assert "zz99" in txn_a.narration, txn_a.narration

    assert txn_b.narration.startswith("CLG/PAYEE NAME"), txn_b.narration
    assert "PAYER/636363/HDF" in txn_b.narration, txn_b.narration
    assert "778899001122" in txn_b.narration, txn_b.narration
