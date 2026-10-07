"""IDFC page-1 merged table: dates come from word positions, not narration."""

from bank_statement_parser.parsers.idfc import IdfcBankStatementParser


def _word(text: str, x0: float, y: float) -> dict:
    return {"text": text, "x0": x0, "doctop": y}


def _date_line(day: str, y: float) -> list[dict]:
    return [
        _word(day, 10, y),
        _word("Mar", 20, y),
        _word("26", 30, y),
        _word("10:00", 40, y),
    ]


def _value_date_line(day: str, y: float) -> list[dict]:
    return [_word(day, 10, y), _word("Mar", 20, y), _word("26", 30, y)]


def test_merged_table_takes_dates_from_word_positions():
    table = [
        [
            "ue Date Transaction Details",
            "Ref/Cheque\nNo.",
            "Withdrawals\n(INR)",
            "Deposits\n(INR)",
            "Balance\n(INR)",
        ],
        ["opening balance", "", "", "", "1,000.00 CR"],
        [
            "NEFT/REF000000000001/SAMPLE PAYER/120\nMar 26 SAMPLE STREET",
            "",
            "",
            "500.00",
            "1,500.00 CR",
        ],
        [
            "IMPS-OPM/100000000001/SAMPLE\nPAYEE Mar 26 /SAMP0000001",
            "",
            "200.00",
            "",
            "1,300.00 CR",
        ],
    ]
    words = (
        _date_line("02", 100)
        + _value_date_line("02", 110)
        + _date_line("03", 200)
        + _value_date_line("03", 210)
    )
    page = {"text": "Withdrawals Deposits", "tables": [table], "words": words}

    txns = IdfcBankStatementParser()._extract_idfc_transactions([page])

    assert [(t.date, t.amount, t.transaction_type) for t in txns] == [
        ("02/03/2026", "500.00", "credit"),
        ("03/03/2026", "200.00", "debit"),
    ]
