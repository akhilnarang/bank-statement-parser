"""Table-parsing tests for the SBI bank-statement parser.

All data here is synthetic (JANE/JOHN DOE, example VPAs, fake refs) — this
repo is public, so no real statement values.
"""

import pytest

from bank_statement_parser.parsers.sbi import SbiBankStatementParser

_HEADER = [
    "Date",
    "Transaction Reference",
    None,
    None,
    "Ref.No./Chq.No.",
    "Credit",
    "Debit",
    "Balance",
]


def _parse(table):
    return SbiBankStatementParser()._parse_sbi_table(table)


def test_sbi_table_extracts_txns_balances_and_period():
    table = [
        _HEADER,
        # Opening summary row with a garbled label (no literal "Opening"),
        # matched on the "on DD-MM-YY:" fragment; balance sits in its own cell.
        [
            "Yourn Oupllening",
            "nBualllance on 01-07-26:",
            None,
            "0.00",
            None,
            None,
            None,
            None,
        ],
        [
            "28-07-26",
            "UPI/CR/900000000001/JANE DOE/EXBK/jane@examplebank/Payme",
            None,
            None,
            "-",
            "10000.00",
            "0",
            "10000.00",
        ],
        [
            "31-07-26",
            "UPI/DR/900000000002/JOHN DOE/EXBK/john@examplebank/Paid",
            None,
            None,
            "-",
            "0",
            "5000.00",
            "5000.00",
        ],
        [
            "Your Closing Balance on 31-07-26:",
            None,
            "5000.00",
            None,
            None,
            None,
            None,
            None,
        ],
    ]
    result = _parse(table)
    txns = result["transactions"]

    assert len(txns) == 2
    # 2-digit year is forced to 20YY, not the %y 1900s pivot.
    assert txns[0].date == "28/07/2026"
    assert txns[0].transaction_type == "credit"
    assert txns[0].amount == "10000.00"
    assert txns[0].counterparty == "JANE DOE"
    assert txns[1].transaction_type == "debit"
    assert txns[1].amount == "5000.00"
    assert txns[1].counterparty == "JOHN DOE"
    assert result["opening_balance"] == "0.00"
    assert result["closing_balance"] == "5000.00"
    assert result["period_start"] == "01/07/2026"
    assert result["period_end"] == "31/07/2026"


def test_sbi_table_short_dated_row_does_not_crash():
    # A dated row shorter than the credit/debit columns must not IndexError.
    table = [_HEADER, ["28-07-26", "UPI/CR/900000000001/JANE DOE/EXBK/x/P"]]
    assert _parse(table)["transactions"] == []


def test_sbi_table_without_header_is_ignored():
    assert _parse([["Account", "Summary"], ["foo", "bar"]])["transactions"] == []


_YONO_TEXT = """STATEMENT OF ACCOUNT
State Bank of India
Account Number : 10000000001
Statement From :01-07-2026 to 31-07-2026
"""

_YONO_STAMP = "\n0000000000001 AT 00001 PBB\nEXAMPLE BRANCH, CITY"


def _yono_raw(tables):
    return {"file": "yono.pdf", "pages": [{"text": _YONO_TEXT, "tables": tables}]}


def test_sbi_yono_statement_parses_and_reconciles():
    table = [
        ["", "", "", "", "", "", "Balance"],
        [
            "02/07/2026",
            "02/07/2026",
            "DEP TFR\nUPI/CR/900000000001/JANE DOE\n/EXBK/jane@examplebank/Paym"
            + _YONO_STAMP,
            "-",
            "-",
            "1,500.00",
            "1,500.00",
        ],
        [
            "03/07/2026",
            "03/07/2026",
            "POS ATM PURCH OTHPG\n900000000002EXAMPLE STORE\nCITY",
            "-",
            "200.00",
            "-",
            "1,300.00",
        ],
        [
            "03/07/2026",
            "03/07/2026",
            "POS ATM PURCH OTHPG\n9000000\n00003EXAMPLE STORE",
            "-",
            "100.00",
            "-",
            "1,200.00",
        ],
        [
            "04/07/2026",
            "04/07/2026",
            "DEP TFR\nNEFT*EXBK0000001\n*EXBK1234A5\n678901*JOHN DOE" + _YONO_STAMP,
            "-",
            "-",
            "700.00",
            "1,900.00",
        ],
        ["", "", "", "", "", "", ""],
    ]
    summary = [
        ["Statement Summary : 01-07-2026 To 31-07-2026", None, None, None, None, None],
        [
            "Brought Forward( )",
            "Dr Count",
            "Cr Count",
            "Total Debits( )",
            "Total Credits( )",
            "Closing Balance( )",
        ],
        ["0.00", "2", "2", "300.00", "2,200.00", "1,950.00CR"],
    ]
    parsed = SbiBankStatementParser().parse(_yono_raw([table, summary]))

    assert parsed.statement_period_start == "01/07/2026"
    assert parsed.statement_period_end == "31/07/2026"
    assert parsed.account_number == "10000000001"
    assert parsed.opening_balance == "0.00"
    # The summary closing differs from the last row balance on purpose. This
    # proves the closing comes from the summary, not the last-row fallback.
    assert parsed.closing_balance == "1,950.00"
    assert parsed.reconciliation.balance_delta == "50.00"

    upi, pos, wrapped_pos, neft = parsed.transactions
    assert (upi.date, upi.value_date) == ("02/07/2026", "02/07/2026")
    assert upi.transaction_type == "credit"
    assert upi.channel == "upi"
    assert upi.reference_number == "900000000001"
    assert upi.counterparty == "JANE DOE"
    # Type prefix and branch stamp are stripped. A break at "/" gets no space.
    assert upi.narration == "UPI/CR/900000000001/JANE DOE/EXBK/jane@examplebank/Paym"
    assert pos.transaction_type == "debit"
    assert pos.channel == "card"
    assert pos.reference_number == "900000000002"
    assert pos.narration == "OTHPG 900000000002EXAMPLE STORE CITY"
    assert pos.counterparty == "EXAMPLE STORE"
    # A wrapped RRN is not read, but the row is still a card purchase.
    assert wrapped_pos.channel == "card"
    assert wrapped_pos.reference_number is None
    assert neft.channel == "neft"
    assert neft.reference_number == "EXBK1234A5678901"
    assert neft.counterparty == "JOHN DOE"


def test_sbi_yono_without_table_raises():
    with pytest.raises(ValueError, match="no transaction table"):
        SbiBankStatementParser().parse(_yono_raw([]))

    # A summary with no rows is a valid empty statement.
    summary = [
        ["Brought Forward( )", "Closing Balance( )"],
        ["5.00", "5.00CR"],
    ]
    parsed = SbiBankStatementParser().parse(_yono_raw([summary]))
    assert parsed.transactions == []
    assert parsed.closing_balance == "5.00"
