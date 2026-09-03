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
    """Rows in the real ICICI geometry of July 2026.

    The particulars lines of a row are centred on its date at an 8.47-point
    pitch. A UPI or IMPS row starts with the counterparty name on its own
    line. That line has no channel prefix. Only the symmetry about the date
    tells it apart from the previous row's last line.
    """
    words: list[dict[str, Any]] = []

    def add_line(y: float, *tokens: tuple[str, float]) -> None:
        for text, x0 in tokens:
            words.append(_word(text, x0, y))

    # Two MOBILE BANKING credits. Each has two particulars lines: the name
    # above the date and the MMT line below it, 4.24 points either side.
    add_line(1370.20, ("SAMPLE", 136.3), ("PERSON", 161.0))
    add_line(
        1374.43,
        ("13-07-2026", 29.8),
        ("MOBILE", 71.0),
        ("BANKING", 94.2),
        ("1,200.00", 370.4),
        ("2,200.00", 526.8),
    )
    add_line(
        1378.67,
        ("MMT/IMPS/611111111111/Self", 136.3),
        ("transfer/SAMPLE", 236.7),
        ("PERSON/DEMO", 285.7),
        ("Bank", 324.1),
    )

    add_line(1387.14, ("SAMPLE", 136.3), ("PERSON", 161.0))
    add_line(
        1391.37,
        ("13-07-2026", 29.8),
        ("MOBILE", 71.0),
        ("BANKING", 94.2),
        ("800.00", 370.4),
        ("3,000.00", 526.8),
    )
    add_line(
        1395.61,
        ("MMT/IMPS/622222222222/Test/SAMPLE", 136.3),
        ("PERSON/DEMO", 261.9),
        ("Bank", 315.3),
    )

    # A one-line netbanking row. It has no name line and no continuation.
    add_line(
        1405.52,
        ("13-07-2026", 29.8),
        ("BIL/INFT/TEST000001/", 136.3),
        ("SAMPLE", 211.5),
        ("PERSON", 238.1),
        ("500.00", 376.0),
        ("3,500.00", 526.8),
    )

    # A four-line UPI row: name, UPI line, then two lines below the date.
    # Its name line sits 9.9 points below the one-line row above it.
    add_line(1415.42, ("OTHER", 136.3), ("PERSON", 161.0))
    add_line(
        1423.89,
        ("UPI/OTHER", 136.3),
        ("PERS/633333333333@demo/Paid", 174.3),
        ("via", 263.7),
        ("C/DEMO", 275.0),
    )
    add_line(
        1428.13,
        ("14-07-2026", 29.8),
        ("100.00", 385.0),
        ("3,600.00", 526.8),
    )
    add_line(1432.36, ("BANK/633333333333/DEMO0000000000000000", 136.3))
    add_line(1440.83, ("3", 136.3))

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


def test_leading_name_line_belongs_to_its_own_row() -> None:
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
    narrations = [transaction.narration for transaction in transactions]
    # The MODE column text leads; it never splits the particulars text.
    assert narrations[0] == (
        "MOBILE BANKING SAMPLE PERSON "
        "MMT/IMPS/611111111111/Self transfer/SAMPLE PERSON/DEMO Bank"
    )
    assert narrations[1] == (
        "MOBILE BANKING SAMPLE PERSON MMT/IMPS/622222222222/Test/SAMPLE PERSON/DEMO Bank"
    )
    # The one-line row keeps nothing from the row below it.
    assert narrations[2] == "BIL/INFT/TEST000001/ SAMPLE PERSON"
    assert transactions[2].counterparty == "SAMPLE PERSON"
    assert narrations[3] == (
        "OTHER PERSON UPI/OTHER PERS/633333333333@demo/Paid via C/DEMO "
        "BANK/633333333333/DEMO0000000000000000 3"
    )


def _build_single_line_then_name_line_words() -> list[dict[str, Any]]:
    """The August 2026 shape: a one-line cash deposit, then an IMPS credit
    whose remitter name is its first line. The name line is 9.9 points below
    the deposit's date and 8.47 above the IMPS date."""
    words: list[dict[str, Any]] = []

    def add_line(y: float, *tokens: tuple[str, float]) -> None:
        for text, x0 in tokens:
            words.append(_word(text, x0, y))

    add_line(
        1320.80,
        ("19-08-2026", 29.8),
        ("ICICI", 71.0),
        ("CRM", 94.2),
        ("CAM/00000AAA/CASH", 136.3),
        ("DEP-Other/19-08-26/0000", 210.0),
        ("2,500.00", 370.4),
        ("5,500.00", 526.8),
    )
    add_line(1330.71, ("DEMO", 136.3), ("BROKING", 161.0), ("LIMITED", 200.0))
    add_line(
        1339.18,
        ("21-08-2026", 29.8),
        ("MOBILE", 71.0),
        ("BANKING", 94.2),
        ("MMT/IMPS/644444444444/20260821abc/DEMO", 136.3),
        ("BR/Yes", 300.0),
        ("300.00", 370.4),
        ("5,800.00", 526.8),
    )
    add_line(1347.65, ("Bank", 138.1))
    return words


def test_single_line_row_does_not_absorb_the_next_name_line() -> None:
    parser = IciciBankStatementParser()
    transactions, _ = parser._parse_icici_page(
        _build_single_line_then_name_line_words()
    )

    assert len(transactions) == 2
    deposit, imps = transactions
    assert deposit.narration == "ICICI CRM CAM/00000AAA/CASH DEP-Other/19-08-26/0000"
    assert "BROKING" not in deposit.narration
    assert imps.narration == (
        "MOBILE BANKING DEMO BROKING LIMITED "
        "MMT/IMPS/644444444444/20260821abc/DEMO BR/Yes Bank"
    )
    assert imps.reference_number == "644444444444"


def _build_header_word_inside_narration_words() -> list[dict[str, Any]]:
    """A UPI row whose name line holds "MandateExe". The word contains "DATE".
    Read as a header, the line is dropped and the row below it then has no
    extent above its date, so its own continuation slips into the next row."""
    words: list[dict[str, Any]] = []

    def add_line(y: float, *tokens: tuple[str, float]) -> None:
        for text, x0 in tokens:
            words.append(_word(text, x0, y))

    add_line(
        14530.22,
        ("UPI/Demo", 140.3),
        ("Sto/store@demo/MandateExe/DEMO", 190.0),
    )
    add_line(
        14538.69,
        ("04-11-2025", 29.8),
        ("BANK/765000000000/DEMO000000000000000000000", 140.3),
        ("2.00", 470.0),
        ("1,000.00", 526.8),
    )
    add_line(14547.16, ("19c1/", 140.3))
    add_line(
        14555.63,
        ("UPI/Demo", 140.3),
        ("Pay/pay@demo/UPI/DEMO", 190.0),
    )
    add_line(
        14564.10,
        ("04-11-2025", 29.8),
        ("BANK/765111111111/DEMO111111111111111111111", 140.3),
        ("2.00", 385.0),
        ("1,002.00", 526.8),
    )
    add_line(14572.58, ("6cb61", 140.3))
    return words


def test_a_narration_word_that_contains_a_header_keyword_is_kept() -> None:
    parser = IciciBankStatementParser()
    transactions, _ = parser._parse_icici_page(
        _build_header_word_inside_narration_words()
    )

    assert len(transactions) == 2
    first, second = transactions
    assert first.narration == (
        "UPI/Demo Sto/store@demo/MandateExe/DEMO "
        "BANK/765000000000/DEMO000000000000000000000 19c1/"
    )
    assert first.reference_number == "765000000000"
    assert first.counterparty == "Demo Sto"
    assert second.narration == (
        "UPI/Demo Pay/pay@demo/UPI/DEMO BANK/765111111111/DEMO111111111111111111111 6cb61"
    )


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
    words += [
        _word("01-01-2020", 30.0, y),
        _word("B/F", 140.0, y),
        _word("1,000.00", 540.0, y),
    ]

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
    words += [
        _word("888888888888", 136.0, y),
        _word("NEW", 240.0, y),
        _word("ACCOUNT", 265.0, y),
    ]
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
    assert [t.amount for t in transactions] == ["250.00"], [
        t.narration for t in transactions
    ]
    assert transactions[-1].balance == "1,250.00"


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

    # Credit whose narration token carries an embedded "01.02" date fragment.
    # Three particulars lines centred on the date: the remitter name above,
    # the token on the date line, a continuation fragment below.
    y = 140.0
    words.append(_word("REMITTER NAME", 140.0, y - 8.47))
    words.append(_word("15-04-2026", 30.0, y))
    words.append(_word("SENDER/707070/UBI/01.02.2099445566778899001122", 140.0, y))
    words.append(_word("7,777.00", 380.0, y))
    words.append(_word("18,888.00", 540.0, y))
    words.append(_word("987654321098", 140.0, y + 8.47))

    full_text = (
        "Savings Account XXXXXXXX9999\n"
        "ACCOUNT HOLDERS: MR. SAMPLE NAME\n"
        "period April 01, 2026 - April 30, 2026\n"
        "DATE PARTICULARS DEPOSIT WITHDRAWAL BALANCE\n"
        "01-04-2026 B/F 11,111.00\n"
        "REMITTER NAME\n"
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

    # Txn A — a transfer with two particulars lines, 4.24 points either side
    # of the date. The date line itself holds no particulars.
    y = 140.0
    words.append(_word("BIL/INFT/EKI0000001/Gift/", 140.0, y - 4.24))
    words.append(_word("14-04-2026", 30.0, y))
    words.append(_word("8,800.00", 380.0, y))
    words.append(_word("52,800.00", 540.0, y))
    words.append(_word("zz99", 140.0, y + 4.24))

    # Txn B — cheque clearing: narration starts on the line ABOVE the date row
    y = 170.0
    words.append(_word("CLG/PAYEE NAME", 140.0, y - 8.47))
    words.append(_word("15-04-2026", 30.0, y))
    words.append(_word("PAYER/636363/HDF/02.03.2099889900112233", 140.0, y))
    words.append(_word("3,300.00", 380.0, y))
    words.append(_word("56,100.00", 540.0, y))
    words.append(_word("778899001122", 140.0, y + 8.47))

    full_text = (
        "Savings Account XXXXXXXX9999\n"
        "ACCOUNT HOLDERS: MR. SAMPLE NAME\n"
        "period April 01, 2026 - April 30, 2026\n"
        "DATE PARTICULARS DEPOSIT WITHDRAWAL BALANCE\n"
        "01-04-2026 B/F 44,000.00\n"
        "BIL/INFT/EKI0000001/Gift/\n"
        "14-04-2026 8,800.00 52,800.00\n"
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

    # The clearing row resolves end-to-end: cheque channel, payer as
    # counterparty, and no reference (the digit runs are a cheque serial and a
    # date stamp, not a txn id). The trailing continuation token stays out of
    # the name.
    assert txn_b.channel == "cheque"
    assert txn_b.counterparty == "PAYEE NAME PAYER"
    assert txn_b.reference_number is None

    # The unrelated transfer above it is untouched by CLG handling.
    assert txn_a.channel == "netbanking"
    assert txn_a.reference_number == "EKI0000001"


def _build_final_page_without_total() -> dict[str, Any]:
    """The FINAL page of a statement, whose table has NO closing "Total:" row.

    This is the shape that leaked in production. The last transaction ran
    straight into the post-statement sections, and its narration swallowed the
    nominee table, the card-blocking instructions and the transaction-code
    legend — about 1,600 characters of boilerplate. The legend contains the
    phrase "Cash Withdrawal at other Bank's ATM", so channel detection then
    read a plain transfer as an ATM withdrawal.

    The existing footer test supplies a "Total:" row, which is the only
    terminator the old code knew — so it never covered this page shape.

    All values fabricated.
    """
    words: list[dict[str, Any]] = []

    y = 100.0
    for token, x in (
        ("DATE", 30.0),
        ("PARTICULARS", 140.0),
        ("DEPOSIT", 380.0),
        ("WITHDRAWAL", 460.0),
        ("BALANCE", 540.0),
    ):
        words.append(_word(token, x, y))

    y = 120.0
    words.append(_word("01-06-2026", 30.0, y))
    words.append(_word("B/F", 140.0, y))
    words.append(_word("10,000.00", 540.0, y))

    # The last transaction of the statement: a transfer in.
    y = 140.0
    words.append(_word("11-06-2026", 30.0, y))
    words.append(_word("TRF/FROM/SB/000900112233", 140.0, y))
    words.append(_word("21,000.00", 380.0, y))
    words.append(_word("31,000.00", 540.0, y))

    # NO "Total:" row — the footer starts immediately.
    footer_lines = [
        ["Account", "Related", "Other", "Information"],
        ["ACCOUNT", "TYPE", "NAME", "OF", "NOMINEE"],
        ["Savings", "XXXXXXXX3333", "100200300", "ACME0000123"],
        ["Legends", "for", "transactions", "in", "your", "Account", "Statement"],
        ["VAT/MAT/NFS", "Cash", "Withdrawal", "at", "other", "Bank's", "ATM"],
        ["Sincerely,", "Team", "Sample", "Bank"],
    ]
    y = 170.0
    for tokens in footer_lines:
        x = 28.0
        for tok in tokens:
            words.append(_word(tok, x, y))
            x += 40.0
        y += 20.0

    text_lines = [
        "DATE PARTICULARS DEPOSIT WITHDRAWAL BALANCE",
        "01-06-2026 B/F 10,000.00",
        "11-06-2026 TRF/FROM/SB/000900112233 21,000.00 31,000.00",
        "Account Related Other Information",
        "ACCOUNT TYPE NAME OF NOMINEE",
        "Savings XXXXXXXX3333 100200300 ACME0000123",
        "Legends for transactions in your Account Statement",
        "VAT/MAT/NFS Cash Withdrawal at other Bank's ATM",
        "Sincerely, Team Sample Bank",
    ]
    full_text = (
        "Savings Account XXXXXXXX3333\n"
        "ACCOUNT HOLDERS: MR. SAMPLE NAME\n"
        "period June 01, 2026 - June 30, 2026\n" + "\n".join(text_lines)
    )
    return {
        "file": "synthetic_icici_final_page.pdf",
        "pages": [{"text": full_text, "words": words}],
    }


def test_final_page_without_total_does_not_swallow_the_footer() -> None:
    """A missing "Total:" row must not leave the narration walk with no terminator."""
    parsed = IciciBankStatementParser().parse(_build_final_page_without_total())

    assert len(parsed.transactions) == 1, [t.narration for t in parsed.transactions]
    last = parsed.transactions[-1]

    assert last.amount == "21,000.00"
    assert "TRF/FROM/SB/000900112233" in last.narration

    for leak in (
        "Account Related",
        "NOMINEE",
        "ACME0000123",
        "Legends",
        "Withdrawal",
        "ATM",
        "Sincerely",
    ):
        assert leak not in last.narration, (
            f"footer text {leak!r} leaked into the last narration: {last.narration!r}"
        )

    # The swallowed legend is what mis-set the channel in production.
    assert last.channel != "atm"


def test_an_unrecognised_footer_is_still_bounded() -> None:
    """Marker lists only catch the footers we already know about. A tail we have
    never seen must still be bounded, or the next unfamiliar layout reopens this
    same bug."""
    raw = _build_final_page_without_total()
    words = [w for w in raw["pages"][0]["words"] if w["doctop"] <= 140.0]
    y = 170.0
    for n in range(40):
        words.append(_word(f"boilerplate{n}", 28.0, y))
        y += 20.0
    raw["pages"][0]["words"] = words

    parsed = IciciBankStatementParser().parse(raw)

    assert len(parsed.transactions) == 1
    narration = parsed.transactions[0].narration
    assert narration.count("boilerplate") <= 5, narration
    assert len(narration) < 200, narration


def _build_stray_line_words() -> list[dict[str, Any]]:
    """A stray line far above a two-line row. The stray line must not widen
    the row's window below its date, or the next row's name line is absorbed."""
    words: list[dict[str, Any]] = []

    def add_line(y: float, *tokens: tuple[str, float]) -> None:
        for text, x0 in tokens:
            words.append(_word(text, x0, y))

    add_line(1340.00, ("stray", 136.3), ("notice", 170.0))
    add_line(1367.46, ("BIL/NEFT/IN12600000000002/Self/SAMPLE", 136.3))
    add_line(
        1371.70,
        ("21-08-2026", 29.8),
        ("700.00", 470.0),
        ("2,300.00", 526.8),
    )
    add_line(1375.93, ("PERS/DEMO", 136.3), ("BANK", 190.0), ("LTD", 220.0))
    add_line(1384.40, ("Sample", 136.3), ("Person", 170.0))
    add_line(1392.87, ("UPI/Sample", 136.3), ("Pers/sample@demo/Self/State", 190.0))
    add_line(
        1397.11,
        ("22-08-2026", 29.8),
        ("400.00", 470.0),
        ("1,900.00", 526.8),
    )
    add_line(1401.35, ("Bank/655555555555/DEMO0000000000000000", 136.3))
    add_line(1409.82, ("80", 136.3))
    return words


def test_a_stray_line_above_a_row_does_not_widen_its_window() -> None:
    parser = IciciBankStatementParser()
    transactions, _ = parser._parse_icici_page(_build_stray_line_words())

    assert len(transactions) == 2
    first, second = transactions
    assert first.narration.endswith(
        "BIL/NEFT/IN12600000000002/Self/SAMPLE PERS/DEMO BANK LTD"
    )
    assert "Sample Person" not in first.narration
    assert second.narration == (
        "Sample Person UPI/Sample Pers/sample@demo/Self/State "
        "Bank/655555555555/DEMO0000000000000000 80"
    )


def test_header_keywords_inside_a_narration_do_not_drop_the_line() -> None:
    parser = IciciBankStatementParser()
    words: list[dict[str, Any]] = []

    def add_line(y: float, *tokens: tuple[str, float]) -> None:
        for text, x0 in tokens:
            words.append(_word(text, x0, y))

    add_line(
        1423.89,
        ("UPI/Page", 136.3),
        ("Total/pt@demo/Total", 180.0),
        ("Page/DEMO", 260.0),
    )
    add_line(
        1428.13,
        ("14-07-2026", 29.8),
        ("100.00", 385.0),
        ("3,600.00", 526.8),
    )
    add_line(1432.36, ("BANK/633333333333/DEMO0000000000000000", 136.3))
    add_line(
        1444.94,
        ("Total:", 139.2),
        ("100.00", 367.0),
        ("0.00", 450.0),
        ("3,600.00", 531.0),
    )

    transactions, _ = parser._parse_icici_page(words)

    assert len(transactions) == 1
    assert transactions[0].narration == (
        "UPI/Page Total/pt@demo/Total Page/DEMO BANK/633333333333/DEMO0000000000000000"
    )
