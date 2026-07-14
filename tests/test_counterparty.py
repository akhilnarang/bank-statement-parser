"""Counterparty extraction tests.

Synthetic narrations modelled after real ICICI savings statement layouts.
Names, account numbers, RRNs/UTRs, IFSC codes, and merchant identifiers
are fabricated.
"""

from __future__ import annotations

import pytest

from bank_statement_parser.parsers.utils.counterparty import extract_counterparty


# (narration, channel, expected_counterparty)
CASES: list[tuple[str, str | None, str | None]] = [
    # UPI: UPI/<merchant>/<vpa>/<remarks>/<sender bank>/<rrn>/<txn id>
    (
        "UPI/Sample Metro/sample-99999999/Sent using/SAMPLE BANKL/100200300400/SAMPLE12345678901234567XXXX XXXXXXX",
        "upi",
        "Sample Metro",
    ),
    (
        "UPI/JOHN DOE/9000000001@xyz/Paid via X/ACME BANK/100200300400/SOME2401010101A1B2C3D4E5F6 ZZZZ",
        "upi",
        "JOHN DOE",
    ),
    (
        "UPI/PIZZA SHOP/pizzashop@bank/PizzaOrder/SAMPLE PAY/200300400500/RR123456ABCDEFGHIJKLMN/",
        "upi",
        "PIZZA SHOP",
    ),
    # UPI mandate execution — counterparty still in segment 1
    (
        "UPI/Sample Pla/sample@axis/MandateExe/SAMPLE BANK/100200300400/SAMPLEa1b2c3d4e5f6 ZZZZ/",
        "upi",
        "Sample Pla",
    ),
    # IMPS: MMT/IMPS/<rrn>/<remark>/<beneficiary>/<bank>
    (
        "MMT/IMPS/200300400500/Self transfer/SAMPLE BENE/Sample MOBILE BANKING Bank Of X",
        "imps",
        "SAMPLE BENE",
    ),
    (
        "MMT/IMPS/100200300400/Self transfer/Counter Party/QRSTUV0000005",
        "imps",
        "Counter Party",
    ),
    # IMPS with leading "MOBILE BANKING " prefix and missing remark (5 segs)
    (
        "MOBILE BANKING MMT/IMPS/300400500600/OTHER PAYEE/XYZB0FORONE",
        "imps",
        "OTHER PAYEE",
    ),
    # IMPS with leading prefix and full 6-seg layout
    (
        "MOBILE BANKING MMT/IMPS/400500600700/test/SAMPLE BENE/Sample Bank Of X",
        "imps",
        "SAMPLE BENE",
    ),
    # ICICI net banking: BIL/INFT/<txn id>/<remark>/<payee>  (within ICICI)
    (
        "BIL/INFT/AB99999999/Note/ SAMPLE PAYEE NAME",
        "netbanking",
        "SAMPLE PAYEE NAME",
    ),
    (
        "BIL/INFT/EGI9999999/Return/ SAMPLE PAYEE NAME",
        "netbanking",
        "SAMPLE PAYEE NAME",
    ),
    # ICICI BIL/INFT with only 4 segments — last segment is payee
    (
        "BIL/INFT/AB99999999/ SAMPLE PAYEE",
        "netbanking",
        "SAMPLE PAYEE",
    ),
    # ICICI BIL/ONL/<txn id>/<beneficiary>/...  (third-party transfers)
    (
        "BIL/ONL/000999888777/SAMPLE BENEFICIARY/QPRTHXMPM02RCA/Self transfer",
        "netbanking",
        "SAMPLE BENEFICIARY",
    ),
    (
        "BIL/ONL/000111222333/SAMPLE BENEFICIARY/RSGT887LPWIUXE",
        "netbanking",
        "SAMPLE BENEFICIARY",
    ),
    # NEFT dash format: NEFT-<utr>-<counterparty>-<remark>-<acct>-<ifsc>
    (
        "NEFT-ABCDN12025010100012345-Some Department-CREDIT NOTE-9000000000001-ABCD0000999",
        "neft",
        "Some Department",
    ),
    (
        "NEFT-WXYZP00111222333-Card Operations-REFUND-9000000000002-WXYZ0000001",
        "neft",
        "Card Operations",
    ),
    # NEFT slash format with IFSC first then UTR — counterparty is the last
    # segment (the payee).
    (
        "NEFT/ABCD0000123/Some Bank Name/WXYZN12025010100012345/payee",
        "neft",
        "payee",
    ),
    # RTGS slash format (ICICI): RTGS/<utr>/<dest_bank>/<beneficiary>.
    # Beneficiary is the last segment, not the one immediately after the UTR
    # (which is the destination bank).
    (
        "RTGS/MNOPR12025010100099991/SAMPLE BANK/SAMPLE BENE",
        "rtgs",
        "SAMPLE BENE",
    ),
    (
        "RTGS/MNOPR12025010100099992/SAMPLE FIN/SamplePay",
        "rtgs",
        "SamplePay",
    ),
    # RTGS dash format (incoming): RTGS-<utr>-<beneficiary>-<acct>-<ifsc>
    (
        "RTGS-WXYZR52025010100099993-SAMPLE BENEFICIARY NAME-00099999999999 -WXYZ0000999",
        "rtgs",
        "SAMPLE BENEFICIARY NAME",
    ),
    # NEFT dash format: NEFT-<utr>-<counterparty>-<remark>-<acct>-<ifsc>
    (
        "NEFT-MNOPN62025010100099994-Credit Card Operations Team-CREDIT BALANCE REFUN-4000999999999-MNOP0000999",
        "neft",
        "Credit Card Operations Team",
    ),
    # NEFT dash format with embedded "/URGENT/" remark — the slash inside the
    # remark must not flip separator detection from "-" to "/".
    (
        "NEFT-EFGHN52025010100099995-SAMPLE BENEFICIARY NAME-/URGENT/-019999999999999-EFGH0000999",
        "neft",
        "SAMPLE BENEFICIARY NAME",
    ),
    # BIL/NEFT slash format: BIL/NEFT/<utr>/<remark>/<beneficiary>/<bank>.
    # Channel detection still tags this as 'neft' because NEFT is in the
    # narration, but the layout is BIL-prefixed netbanking.
    (
        "BIL/NEFT/IJKLN12025010100099996/Self transfer/SAMPLE BENE/XYZBANK",
        "neft",
        "SAMPLE BENE",
    ),
    # Cheque clearing: CLG/<payer>/<serial>/<bank code>/<date><instrument ref>.
    # The last segment can carry a trailing continuation token from the PDF text
    # flow — it must not end up in the name.
    (
        "CLG/SAMPLE CUSTOMER NAME/000099/ABC/01.01.20250101202500099900099 99999999999999",
        "cheque",
        "SAMPLE CUSTOMER NAME",
    ),
    # Same layout without the trailing continuation token.
    (
        "CLG/SAMPLE CUSTOMER NAME/000099/ABC/01.01.2025",
        "cheque",
        "SAMPLE CUSTOMER NAME",
    ),
    # A payer name containing a slash (joint account) survives: the name is read
    # relative to the fixed three-field suffix, not as segment 1.
    (
        "CLG/SAMPLE NAME/JOINT NAME/000099/ABC/01.01.2025",
        "cheque",
        "SAMPLE NAME/JOINT NAME",
    ),
    # A trailing slash is formatting, not a field: empty tail segments are
    # dropped before the suffix window is taken, so the payer is unaffected.
    ("CLG/SAMPLE NAME/000099/ABC/01.01.2025/", "cheque", "SAMPLE NAME"),
    ("CLG/SAMPLE NAME/000099/ABC/01.01.2025//", "cheque", "SAMPLE NAME"),
    # Malformed / truncated CLG rows → None rather than a garbage name.
    ("CLG/SAMPLE CUSTOMER NAME", "cheque", None),
    ("CLG/", "cheque", None),
    ("CLG/////", "cheque", None),
    # Truncated: payer + serial + bank code but no date/ref field.
    ("CLG/SAMPLE CUSTOMER NAME/000099/ABC", "cheque", None),
    # Empty payer segments (stray slashes) shift the suffix window — the split
    # is not the layout we assume, so refuse rather than emit a holed name.
    ("CLG//000099/ABC/01.01.2025", "cheque", None),
    ("CLG//SAMPLE NAME/000099/ABC/01.01.2025", "cheque", None),
    ("CLG/SAMPLE NAME//000099/ABC/01.01.2025", "cheque", None),
    ("CLG/SAMPLE NAME/000099//ABC/01.01.2025", "cheque", None),
    # Suffix fields that don't validate: serial must be digits, bank code must
    # be letters, and the trailing field must start with the date.
    ("CLG/SAMPLE NAME/NOTNUM/ABC/01.01.2025", "cheque", None),
    ("CLG/SAMPLE NAME/000099/12345/01.01.2025", "cheque", None),
    ("CLG/SAMPLE NAME/000099/ABC/NOTADATE", "cheque", None),
    # Payer position occupied by digits → not a name.
    ("CLG/000099/ABC/01.01.2025/99999999", "cheque", None),
    ("CLG/000099/000012/HDF/01.01.2025", "cheque", None),
    # Other cheque narrations have no structured payer segment.
    ("CHQ PAID 000099", "cheque", None),
    # Channels we don't have a structured format for: return None so caller
    # falls back to narration.
    ("MCD REF PAY WWW 250101", "debit_card", None),
    ("999999999999:Int.Pd:01-04-2025 to 01-07-2025", "interest", None),
    ("CMS TRANSACTION CMS/ EXCESS CREDIT REFUND/ICICI BANK LTD CRE", "netbanking", None),
    # No channel hint → no extraction, even for a CLG-shaped narration.
    ("CLG/SAMPLE CUSTOMER NAME/000099/ABC/01.01.2025", None, None),
    # Edge: empty narration
    ("", "upi", None),
    # Edge: UPI with too few segments
    ("UPI/", "upi", None),
    ("UPI/JustOne", "upi", "JustOne"),
]


@pytest.mark.parametrize(("narration", "channel", "expected"), CASES)
def test_extract_counterparty(
    narration: str, channel: str | None, expected: str | None
) -> None:
    assert extract_counterparty(narration, channel) == expected
