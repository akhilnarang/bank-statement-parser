"""Tests for Slice savings statement parsing helpers.

The Slice statement PDF places a 16-digit bank-internal txn id in the
"Ref No" column for UPI/IMPS rows, while the actual RBI UTR/RRN sits
inside the narration text. The bank-email-parser side captures the UTR
as ``reference_number``, so to keep both sides on the same identifier
namespace (and let the reconciler exact-match in Pass 1) the Slice
statement parser prefers the narration-extracted UTR over the column
ref for UPI rows. IMPS rows keep the column ref because IMPS narrations
typically contain the sender account number, not the IMPS RRN, and
extracting that as a UTR would introduce false uniqueness.
"""

from __future__ import annotations

from bank_statement_parser.parsers.slice import _select_reference


def test_upi_prefers_narration_utr_over_column_ref():
    """Slice row layout: narration carries the 12-digit UTR, ref column
    carries the 16-digit slice-internal txn id. We want the UTR."""
    column_ref = "8001234567890123"
    narration = "UPI-Credit-100200300400-SAMPLE PAYER- KARB-sample.payer-2@okaxis-amazon prime"

    assert _select_reference(narration, "upi", column_ref) == "100200300400"


def test_upi_falls_back_to_column_ref_when_no_utr_in_narration():
    column_ref = "8001234567890123"
    narration = "UPI Credit-no digits here at all"

    assert _select_reference(narration, "upi", column_ref) == "8001234567890123"


def test_upi_returns_none_when_neither_source_has_a_ref():
    assert _select_reference("UPI Credit-narration without digits", "upi", None) is None


def test_imps_keeps_column_ref_even_when_narration_has_long_digits():
    """IMPS narrations carry the *sender account number* (12+ digits) but
    NOT the IMPS RRN. Extracting the account number as a 'reference
    number' would introduce false uniqueness collisions and confuse the
    reconciler. Stick with the column ref for IMPS."""
    column_ref = "8001234567890123"
    narration = "IMPS Credit-Mr Sample Payer-ABCD0009 999-XX5678-999900000001-Selftransfer"

    assert _select_reference(narration, "imps", column_ref) == "8001234567890123"


def test_non_upi_imps_channel_uses_column_ref_first_then_narration_fallback():
    """For interest credits, bill payments, etc. the column ref (if any)
    wins; otherwise the channel-aware narration extractor runs (which
    returns None for non-upi/imps/neft/rtgs/netbanking channels)."""
    assert _select_reference("Interest Cr. for 31-Mar-2026", "interest", "20226091470594") == "20226091470594"
    assert _select_reference("Interest Cr. for 31-Mar-2026", "interest", None) is None


def test_no_channel_falls_back_to_column_ref():
    """When channel detection failed, we have no signal that the
    narration is structured around a UTR — column ref wins."""
    assert _select_reference("Random row", None, "COL-123") == "COL-123"
    assert _select_reference("Random row", None, None) is None


def test_upi_narration_with_multiple_long_digit_runs_picks_first_run():
    """Documented heuristic: when a UPI narration contains more than one
    12+ digit run, ``extract_reference_number`` returns the first one.
    All 8 real Slice UPI narrations in production have exactly one such
    run (the UTR appears between counterparty name and a free-text tail),
    so this is the empirically-stable choice. If a future Slice
    narration shape produces multiple runs and the wrong one is chosen,
    the symptom is "Pass 1 ref-match misses" and the reconciler's
    narration-substring rule still recovers the dedup. Regress here
    only if Slice's narration shape changes to put a non-UTR digit run
    first."""
    # Synthetic case modelled on real layout: counterparty name then
    # UTR, then a tail with another long numeric token.
    narration = "UPI Credit-MERCHANT-merchant@bank-IFSC0000123-100200300400-Order 999888777666"

    assert _select_reference(narration, "upi", "STMT-INTERNAL") == "100200300400"
