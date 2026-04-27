import pytest

from bank_statement_parser.parsers.utils.channels import (
    detect_channel,
    extract_reference_number,
)


# Synthetic narrations modeled after real bank statement formats — names, phone
# numbers, account numbers, and reference IDs are randomized.
# (narration, expected_channel, expected_ref)
CASES: list[tuple[str, str | None, str | None]] = [
    # UPI: 12-digit RRN, sandwiched between counterparty and a UPI txn ID.
    (
        "UPI/JOHN DOE/9000000001@xyz/Paid via X/ACME BANK/100200300400/SOME2401010101A1B2C3D4E5F6 ZZZZ",
        "upi",
        "100200300400",
    ),
    (
        "UPI/PIZZA SHOP/pizzashop@bank/PizzaOrder/SAMPLE PAY/200300400500/RR123456ABCDEFGHIJKLMN/",
        "upi",
        "200300400500",
    ),
    # NEFT UTRs: 4-letter bank code + 1 alphanumeric + digits. The bank-specific
    # 5th char varies (N/R/D/P/numeric). Real PDFs include the recipient account
    # number further along — extractor must NOT pick that up.
    (
        "NEFT-ABCDN12025010100012345-Some Department-CREDIT NOTE-9000000000001-ABCD0000999",
        "neft",
        "ABCDN12025010100012345",
    ),
    (
        "NEFT-WXYZP00111222333-Card Operations-REFUND-9000000000002-WXYZ0000001",
        "neft",
        "WXYZP00111222333",
    ),
    (
        "NEFT-EFGH112233445566-PROVIDENT FUND ORG-/URGENT/RS0000099999-99999999999999999-AB",
        "neft",
        "EFGH112233445566",
    ),
    (
        "NEFT-IJKLD25339306236-CARD ISSUER-/// /SL-99999999999999-IJKL0000ABC",
        "neft",
        "IJKLD25339306236",
    ),
    # RTGS: same UTR shape as NEFT.
    (
        "RTGS/MNOPR12025010101010101/SAMPLE FIN/Counterparty",
        "rtgs",
        "MNOPR12025010101010101",
    ),
    # IFSC codes (11 chars: 4 letters + 0 + 6 alphanumeric) appear in NEFT
    # narrations as the recipient branch. They must NOT be picked up as UTRs.
    # When an IFSC appears *before* the real UTR, the UTR still wins.
    (
        "NEFT/ABCD0000123/Some Bank Name/WXYZN12025010100012345/payee",
        "neft",
        "WXYZN12025010100012345",
    ),
    # NEFT narration with only an IFSC (no UTR, no digit RRN) — return None.
    (
        "NEFT-ABCD0000123-Some Branch-/payee/no other id",
        "neft",
        None,
    ),
    # ICICI net banking transfers. BIL/INFT = internal (within ICICI),
    # BIL/ONL = online/third-party. Token #3 is the txn id.
    (
        "BIL/INFT/AB99999999/Note/ SAMPLE PAYEE NAME",
        "netbanking",
        "AB99999999",
    ),
    (
        "BIL/ONL/000999888777/SAMPLE BENEFICIARY/QPRTHXMPM02RCA/Self transfer",
        "netbanking",
        "000999888777",
    ),
    (
        "BIL/INFT/EGI9999999/Return/ SAMPLE PAYEE NAME",
        "netbanking",
        "EGI9999999",
    ),
    (
        "BIL/ONL/000111222333/SAMPLE BENEFICIARY/RSGT887LPWIUXE",
        "netbanking",
        "000111222333",
    ),
    # Generic NETBANKING marker without BIL prefix — falls through to None for ref.
    (
        "NETBANKING transfer to ANOTHER ACCOUNT",
        "netbanking",
        None,
    ),
    # ICICI CMS (Cash Management Services) — internal credit movement, treated
    # as netbanking since it's the same kind of same-bank fund transfer.
    (
        "CMS TRANSACTION CMS/ EXCESS CREDIT REFUND/ICICI BANK LTD CRE",
        "netbanking",
        None,
    ),
    # ICICI interest credit: `Int.Pd:` shorthand. Must detect interest channel
    # and NOT pick up the leading account number as a ref.
    (
        "999999999999:Int.Pd:01-04-2025 to 01-07-2025",
        "interest",
        None,
    ),
    # UPI autopay (mandate execution). Despite the embedded `BANK/...`, this is
    # still a UPI narration; existing UPI handling should pick the RRN.
    (
        "UPI/Sample Pla/sample@axis/MandateExe/SAMPLE BANK/100200300400/SAMPLEa1b2c3d4e5f6 ZZZZ/",
        "upi",
        "100200300400",
    ),
    # IMPS: 12-digit RRN inside an IMPS narration.
    (
        "MMT/IMPS/100200300400/Self transfer/Counter Party/QRSTUV0000005",
        "imps",
        "100200300400",
    ),
    # Non-payment narrations: cheque clearing, bill pay, interest credit, etc.
    # These have digit runs (cheque numbers, dates, account numbers) that the old
    # blanket regex would falsely pick up. Channel is None, so no extraction.
    (
        "CLG/SAMPLE CUSTOMER NAME/000099/ABC/01.01.20250101202500099900099 99999999999999",
        None,
        None,
    ),
    ("MIN/PAY WWW XYZ/202500000000/999999/", None, None),
    ("BIL/INFT/AB99999999/ SAMPLE PAYEE", "netbanking", "AB99999999"),
    # ICICI MasterCard debit-card refund/reversal. The trailing 6 digits are a
    # YYMMDD date stamp, not a transaction id — leave ref as None.
    ("MCD REF PAY WWW 250101", "debit_card", None),
    ("MCD REF WWW LOUN 260314", "debit_card", None),
    ("999999999999:Int.Pd:01-01-2025 to 01-04-2025", "interest", None),
]


@pytest.mark.parametrize(("narration", "expected_channel", "expected_ref"), CASES)
def test_channel_and_reference_extraction(
    narration: str, expected_channel: str | None, expected_ref: str | None
) -> None:
    channel = detect_channel(narration)
    assert channel == expected_channel
    assert extract_reference_number(narration, channel) == expected_ref


def test_extract_without_channel_returns_none() -> None:
    """No channel hint = no extraction. Avoids false positives on unstructured text."""
    narration = "NEFT-ABCDN12025010100012345-foo-9000000000001"
    assert extract_reference_number(narration) is None


def test_neft_falls_back_to_digit_rrn_when_no_utr_present() -> None:
    """Some statements show the UTR in a separate column and leave the narration
    bare. Digit-run fallback still kicks in for known payment channels."""
    narration = "NEFT inward 100200300400 from XYZ"
    assert extract_reference_number(narration, "neft") == "100200300400"
