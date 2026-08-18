"""Direct unit tests for the per-bank counterparty extractors.

The parsers' integration tests cover counterparty wiring end-to-end with
real fixtures; these tests pin the smaller behaviours each helper
guarantees so refactors stay safe.
"""

from __future__ import annotations

import pytest

from bank_statement_parser.parsers.utils.hdfc_counterparty import (
    extract_counterparty as hdfc_cp,
)
from bank_statement_parser.parsers.utils.idfc_counterparty import (
    extract_counterparty as idfc_cp,
)
from bank_statement_parser.parsers.utils.kotak_counterparty import (
    extract_counterparty as kotak_cp,
)
from bank_statement_parser.parsers.utils.slice_counterparty import (
    extract_counterparty as slice_cp,
)
from bank_statement_parser.parsers.utils.uboi_counterparty import (
    extract_counterparty as uboi_cp,
)

# ---------------------------------------------------------------------------
# IDFC
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "narration,channel,direction,expected",
    [
        # UPI with CR/DR direction segment — counterparty is dash-seg 3
        (
            "UPI/CR/600213508249/JANE DOE/KKBK/9000000/Self",
            "upi",
            "credit",
            "JANE DOE",
        ),
        (
            "UPI/DR/604185945767/MONEY LIC/yespay./Account",
            "upi",
            "debit",
            "MONEY LIC",
        ),
        # IMPS / IMPS-OPM — counterparty is seg 2 regardless of direction
        (
            "IMPS/611753398290/PAYEE NAME/HDFC0000777/7770/CCbills",
            "imps",
            "credit",
            "PAYEE NAME",
        ),
        (
            "IMPS-OPM/600212475660/JOHN DOE/9000000/7771/Selftran sfer",
            "imps",
            "debit",
            "JOHN DOE",
        ),
        # RTGS / NEFT slash form — counterparty is segment after UTR
        (
            "RTGS/ICICR1202602100897361 3/PAYEE NAME/ICIC0000777",
            "rtgs",
            "credit",
            "PAYEE NAME",
        ),
        # POS card
        (
            "POS-VISA/MERCHANT NAME/609215082247/GURUGRA M/15:58:33",
            None,
            "debit",
            "MERCHANT NAME",
        ),
        # REF/POS-VISA refund
        (
            "REF/POS-VISA/MERCHANT NAME/647721/311225",
            None,
            "credit",
            "MERCHANT NAME",
        ),
        # Ecom — counterparty (seg3) + description (seg4) combined
        (
            "Ecom/63889620/RazorpaySo/SomeMerchant/Selftransfer",
            None,
            "debit",
            "SomeMerchant (Selftransfer)",
        ),
        (
            "Ecom/64029737/IndiaIdeas/PPF ASMUTUA/",
            None,
            "debit",
            "PPF ASMUTUA",
        ),
        # Self labels
        ("AddMoney/20260317252100/109 100818138/UPI", None, "credit", "Self"),
        ("MONTHLY SAVINGS INTEREST CREDIT", None, "credit", "Self"),
        ("DELAYINT_ICICR12026033109 896246_20260331", None, "credit", "Self"),
        # FD creation always under account-holder name — Self
        ("FD 10278100174 Mr. JOHN DOE", None, "debit", "Self"),
        # Redemption fees
        (
            "Redemption Fees on FIRST Rewards/Inv2701261331170051/ 30-JAN-2026/",
            None,
            "debit",
            "Redemption Fees on FIRST Rewards",
        ),
    ],
)
def test_idfc_counterparty(narration, channel, direction, expected):
    assert idfc_cp(narration, channel, direction) == expected


def test_idfc_ift_direction_sensitive():
    """Regression: IFT format depends on transaction direction.

    Credit IFT (incoming): seg2 is the gateway (e.g. payroll provider),
    seg4 is the real originator (e.g. employer). Counterparty = seg4.

    Debit IFT (outgoing): seg2 is the recipient, seg4 is the user's
    remark. Counterparty = seg2.
    """
    credit_narr = "IFT/10198879646/PAYROLL GATEWAY/13039654/Real Employer Name"
    assert idfc_cp(credit_narr, None, "credit") == "Real Employer Name"

    debit_narr = "IFT/10280206697/RECIPIENT NAME/15752209/Test"
    assert idfc_cp(debit_narr, None, "debit") == "RECIPIENT NAME"


def test_idfc_returns_none_on_unknown_layout():
    assert idfc_cp("RANDOM UNSTRUCTURED NARRATION", None, "debit") is None


def test_idfc_empty_input():
    assert idfc_cp("", None, "debit") is None
    assert idfc_cp(None, None, "debit") is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Kotak
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "narration,expected",
    [
        # UPI (Kotak's UPI has no direction segment, name is seg 1)
        ("UPI/SAMPLE PAYEE NAME/606285638729/UPI", "SAMPLE PAYEE NAME"),
        ("UPI/Indian Railways/100465065521/COLLECT", "Indian Railways"),
        # BBPS biller payment
        ("811:BBPS/260004949908/SBI CARD", "SBI CARD"),
        ("811:BBPS/260009260615/HDFC BANK CREDIT CARD", "HDFC BANK CREDIT CARD"),
        # BBPS reversal — `(Reversal)` suffix to distinguish
        ("REV:811:BBPS/260009260602/SBI CARD", "SBI CARD (Reversal)"),
        # POS card debit
        ("PCD/7777/SAMPLE MERCHANT/MUMBAI020326/11:00", "SAMPLE MERCHANT"),
        # Bank-internal — Self
        ("KOTAK811/606148966932", "Self"),
        ("KOTAK811/HDBZPVYSIJXYFZIAQSAUM4", "Self"),
        ("CASHBACK FOR BILLPAY", "Self"),
        ("CASHBACK EARNED", "Self"),
        ("811 SUPER CASHBACK MAR26", "Self"),
        ("811 SUPER PROGRAM RENEWAL FEE", "Self"),
        ("Int.Pd:7777777777:01-01-2026 to 31-03-2026", "Self"),
    ],
)
def test_kotak_counterparty(narration, expected):
    assert kotak_cp(narration) == expected


def test_kotak_returns_none_on_unknown_layout():
    assert kotak_cp("RANDOM UNSTRUCTURED NARRATION") is None


# ---------------------------------------------------------------------------
# Slice
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "narration,expected",
    [
        # UPI dash form: UPI-(Debit|Credit)-<rrn>-<NAME>-...
        (
            "UPI-Debit-610978836048-SAMPLE MERCHANT-UTIB-gpay-11235168707@okbizaxis",
            "SAMPLE MERCHANT",
        ),
        (
            "UPI-Credit-647718718335-SOME NAME-PPIW-9000000002@amazonpay-Self trans fer",
            "SOME NAME",
        ),
        # UPI space form: UPI Debit-<NAME>-<vpa>-<ifsc>-<rrn>-<remark>
        (
            "UPI Debit-SAMPLE FINANCIAL TECH-samplebillpay1@fbl-FDRL0000777-801445290636-Sent via Sample Wallet",
            "SAMPLE FINANCIAL TECH",
        ),
        (
            "UPI Credit-PAYER NAME-sampleuser@ptyes-ICIC0000777-398206729125-Sent using Paytm UPI",
            "PAYER NAME",
        ),
        # UPI Reversal — name + (Reversal)
        (
            "UPI Reversal-PAYER NAME-sampleuser.test@icici-607017792391-test",
            "PAYER NAME (Reversal)",
        ),
        # IMPS dash form
        (
            "IMPS Debit-JOHN DOE-HDFC0000777-XX7777-606207330250",
            "JOHN DOE",
        ),
        (
            "IMPS Credit-JANE DOE-ICIC0000777-XX7778-606700017869-Self transfer",
            "JANE DOE",
        ),
        # RTGS
        (
            "RTGS Credit-Mr. JOHN DOE-IDFB0000777-XX7779-IDFBR62026022001881088",
            "Mr. JOHN DOE",
        ),
        # Slice-internal / one-word narrations
        ("Bill payment", "Credit Card Bill Payment"),
        ("Payment", "Credit Card Bill Payment"),
        ("611400166935-Bill payment", "Credit Card Bill Payment"),
        ("bill payment refund", "Credit Card Bill Payment (Refund)"),
        ("Deposit", "Self"),
        ("monies transfer", "Self"),
        ("611400166935-monies transfer", "Self"),
        ("Invite & earn", "Self"),
        ("Interest Cr. for 28-Feb-2026", "Self"),
    ],
)
def test_slice_counterparty(narration, expected):
    assert slice_cp(narration) == expected


def test_slice_returns_none_on_unknown_layout():
    assert slice_cp("RANDOM UNSTRUCTURED NARRATION") is None


# ---------------------------------------------------------------------------
# HDFC
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "narration,expected",
    [
        # UPI — counterparty is dash-seg 1
        (
            "UPI-CRED Club-cred.club@axisb-UTIB0000777-646231181766-payment on CRED",
            "CRED Club",
        ),
        (
            "UPI-PUNE METRO-PAYTM-79223175@PTYBL-YESB 0PTMUPI-204749582306-SENTUSINGPAYTMU",
            "PUNE METRO",
        ),
        # IMPS — counterparty is dash-seg 2
        (
            "IMPS-609982869894-SAMPLE BROKER NAME ACCOUNT-UTIB-XXXXXXXXXXX7777 -WITHDRAWAL",
            "SAMPLE BROKER NAME ACCOUNT",
        ),
        # ACHC credit — seg1 is scheme
        ("ACHC-SCHEMENAMEHERE202526-1760154", "SCHEMENAMEHERE202526"),
        # ACH D- debit — text between `ACH D-` and the trailing `-<ref>`
        ("ACH D- HELIOS 03042026 CAMS-595100021591", "HELIOS 03042026 CAMS"),
        # POS — merchant text after last HH:MM:SS
        (
            "POS400000XXXXXX777761086700154618APR2 600:40:31MUMBAISAMPLEMERCHANT",
            "MUMBAISAMPLEMERCHANT",
        ),
        # Bank-internal
        ("IBSSFUNDSTRANSFERDR-55000005615988", "Self"),
        ("IBSSFUNDSTRANSFERCR-12345678901234", "Self"),
        ("DEBITCARDCASHBACK", "Self"),
    ],
)
def test_hdfc_counterparty(narration, expected):
    assert hdfc_cp(narration) == expected


def test_hdfc_returns_none_on_unknown_layout():
    assert hdfc_cp("RANDOM UNSTRUCTURED NARRATION") is None


# ---------------------------------------------------------------------------
# UBOI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "narration,expected",
    [
        # UPI carries the CR/DR direction as seg 2; counterparty is seg 3.
        ("UPIAB/100000000001/CR/JANE DOE/HDFC/jane@examplebank", "JANE DOE"),
        ("UPIAR/100000000002/DR/JOHN DOE/INDB/ john@examplebank", "JOHN DOE"),
        # IMPS counterparty is seg 2.
        ("IMPSAB/100000000003/Mr JOHN DOE PLACEHO/9000000000", "Mr JOHN DOE PLACEHO"),
        ("IMPSAR/100000000004/Jane Doe Placehol/000000000000", "Jane Doe Placehol"),
        # POS: merchant is the first slash-segment.
        ("POS:EXAMPLE MERCHANT/CITY/100000000005", "EXAMPLE MERCHANT"),
        # NEFT/RTGS/NEFTO/CLG: name up to a trailing ref/IFSC/account token.
        ("NEFT:ACME CORP PRIVATE LIMITED HDFC0000000",
         "ACME CORP PRIVATE LIMITED"),
        ("RTGS:Mr. JOHN DOE PLACEHO IDFB0000000000000000", "Mr. JOHN DOE PLACEHO"),
        ("NEFTO-JANE DOE PLACEHOLDER 000000000000", "JANE DOE PLACEHOLDER"),
        ("CLG:JOHN DOE PLACEHOLDER", "JOHN DOE PLACEHOLDER"),
        # Fixed labels.
        ("REFUND/100000000006/100000000007", "Refund"),
        ("000000000000:Int.Pd:01-01- 2026 to 31-03-2026", "Interest"),
    ],
)
def test_uboi_counterparty(narration, expected):
    assert uboi_cp(narration) == expected


def test_uboi_returns_none_on_unknown_layout():
    assert uboi_cp("1000000000000000/000000000000/000000000000") is None
