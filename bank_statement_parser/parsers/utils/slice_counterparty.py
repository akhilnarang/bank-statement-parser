"""Slice-specific counterparty extraction from statement narrations.

Slice narration layouts (all dash-separated):

- `UPI-Debit-<rrn>-<NAME>-<bank_code>-<vpa>[-<remark>]`
  counterparty = NAME (dash-segment 3)
- `UPI-Credit-<rrn>-<NAME>-<bank_code>-<vpa>[-<remark>]`
  counterparty = NAME (dash-segment 3)
- `UPI Debit-<NAME>-<vpa>[-<ifsc>]-<rrn>[-<remark>]`
  counterparty = NAME (dash-segment 1)
- `UPI Credit-<NAME>-<vpa>[-<ifsc>]-<rrn>[-<remark>]`
- `UPI Reversal-<NAME>-<vpa>-<rrn>-<remark>`
- `IMPS Debit-<NAME>-<ifsc>-<masked_acct>-<rrn>[-<remark>]`
  counterparty = NAME
- `IMPS Credit-<NAME>-<ifsc>-<masked_acct>-<rrn>[-<remark>]`
- `<rrn>-Bill payment` / `Bill payment` / `bill payment refund` — Self
  (slice CC bill payment from your slice savings)
- `Deposit` / `monies transfer` / `<rrn>-monies transfer` — Self
  (internal slice savings actions)
"""

import re


def _split_dash(narration: str) -> list[str]:
    return [s.strip() for s in narration.split("-")]


def _seg(parts: list[str], idx: int) -> str | None:
    if 0 <= idx < len(parts):
        val = parts[idx].strip()
        return val or None
    return None


_RRN_DIGITS_RE = re.compile(r"^\d{9,}$")


def _extract_upi_dash_form(narration: str) -> str | None:
    """`UPI-(Debit|Credit)-<rrn>-<NAME>-<bank>-<vpa>[-<remark>]`.

    Counterparty is dash-segment 3 (after the rrn).
    """
    parts = _split_dash(narration)
    if len(parts) < 4 or parts[0].upper() != "UPI":
        return None
    if parts[1].upper() not in {"DEBIT", "CREDIT"}:
        return None
    return _seg(parts, 3)


def _extract_upi_space_form(narration: str) -> str | None:
    """`UPI (Debit|Credit|Reversal)-<NAME>-<vpa>[-<ifsc>]-<rrn>[-<remark>]`.

    The first token (`UPI Debit`, `UPI Credit`, `UPI Reversal`) is one
    dash-segment with a space inside; counterparty is the next segment.
    """
    parts = _split_dash(narration)
    if len(parts) < 2:
        return None
    head = parts[0].upper()
    if head not in {"UPI DEBIT", "UPI CREDIT", "UPI REVERSAL"}:
        return None
    name = _seg(parts, 1)
    if not name:
        return None
    if head == "UPI REVERSAL":
        return f"{name} (Reversal)"
    return name


def _extract_imps(narration: str) -> str | None:
    """`IMPS (Debit|Credit|Reversal)-<NAME>-<ifsc>-<masked_acct>-<rrn>[-<remark>]`.

    Counterparty is dash-segment 1. Reversals carry a suffix.
    """
    parts = _split_dash(narration)
    if len(parts) < 2:
        return None
    head = parts[0].upper()
    if head not in {"IMPS DEBIT", "IMPS CREDIT", "IMPS REVERSAL"}:
        return None
    name = _seg(parts, 1)
    if not name:
        return None
    if head == "IMPS REVERSAL":
        return f"{name} (Reversal)"
    return name


def _extract_rtgs(narration: str) -> str | None:
    """`RTGS (Debit|Credit)-<NAME>-<ifsc>-<masked_acct>-<utr>`.

    Counterparty is dash-segment 1.
    """
    parts = _split_dash(narration)
    if len(parts) < 2:
        return None
    head = parts[0].upper()
    if head not in {"RTGS DEBIT", "RTGS CREDIT"}:
        return None
    return _seg(parts, 1)


_BILL_PAYMENT_LABEL = "Credit Card Bill Payment"
_BILL_PAYMENT_REFUND_LABEL = "Credit Card Bill Payment (Refund)"


def _classify_short_narration(narration: str) -> str | None:
    """Map slice's short single-word narrations to a stable label.

    Slice statements show terse one-word entries for several recurring
    flows that have no actual counterparty info in the narration:
    - `Payment`, `Bill payment`, `<rrn>-Bill payment` — CC bill payment
      to an unspecified issuer (real external party but issuer unknown
      from the narration alone)
    - `bill payment refund` — reversal of the above
    - `Deposit`, `<rrn>-monies transfer`, `Invite & earn`, `Interest Cr.
      for <date>` — slice-internal credits or promo bonuses; map to Self
    """
    head = narration.strip().upper()
    stripped = re.sub(r"^\d{9,}\s*-\s*", "", head)
    if stripped in {"BILL PAYMENT", "PAYMENT"}:
        return _BILL_PAYMENT_LABEL
    if stripped == "BILL PAYMENT REFUND":
        return _BILL_PAYMENT_REFUND_LABEL
    if stripped in {"DEPOSIT", "MONIES TRANSFER", "INVITE & EARN"}:
        return "Self"
    if head.startswith("INTEREST CR.") or head.startswith("INTEREST CR "):
        return "Self"
    return None


def extract_counterparty(
    narration: str,
    channel: str | None = None,
    direction: str | None = None,
) -> str | None:
    """Derive a clean counterparty from a slice statement narration."""
    del channel, direction

    if not narration:
        return None

    label = _classify_short_narration(narration)
    if label is not None:
        return label

    head = narration.lstrip().upper()

    if head.startswith(("UPI-DEBIT-", "UPI-CREDIT-")):
        return _extract_upi_dash_form(narration)
    if head.startswith(("UPI DEBIT-", "UPI CREDIT-", "UPI REVERSAL-")):
        return _extract_upi_space_form(narration)
    if head.startswith(("IMPS DEBIT-", "IMPS CREDIT-", "IMPS REVERSAL-")):
        return _extract_imps(narration)
    if head.startswith(("RTGS DEBIT-", "RTGS CREDIT-")):
        return _extract_rtgs(narration)

    return None


__all__ = ["extract_counterparty"]
