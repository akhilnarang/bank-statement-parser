"""Kotak-specific counterparty extraction from statement narrations.

Kotak 811 narration layouts:

- UPI: `UPI/<name>/<rrn>/<remark>`
- BBPS bill payment: `811:BBPS/<biller_id>/<biller_name>`
- BBPS reversal: `REV:811:BBPS/<biller_id>/<biller_name>` (flagged as
  reversal in the returned counterparty)
- POS card debit: `PCD/<card_last4>/<merchant>/<loc><date>/<time>`

Bank-internal narrations (`KOTAK811/<ref>`, `811 SUPER CASHBACK ...`,
`CASHBACK FOR BILLPAY`, `CASHBACK EARNED`, `811 SUPER PROGRAM RENEWAL FEE`,
`Int.Pd:<id>:<dates>`) map to `Self` since the counterparty is the bank
itself.
"""


def _segments(narration: str, sep: str) -> list[str]:
    return [s.strip() for s in narration.split(sep)]


def _seg(parts: list[str], idx: int) -> str | None:
    if 0 <= idx < len(parts):
        val = parts[idx].strip()
        return val or None
    return None


def _extract_upi(narration: str) -> str | None:
    """Kotak UPI: `UPI/<name>/<rrn>/<remark>` — counterparty is segment 1."""
    parts = _segments(narration, "/")
    if len(parts) < 2 or parts[0].upper() != "UPI":
        return None
    return _seg(parts, 1)


def _extract_bbps(narration: str) -> str | None:
    """BBPS: `811:BBPS/<biller_id>/<biller_name>` or with `REV:` prefix.

    Counterparty is the biller name (last segment). Reversals get a
    `(Reversal)` suffix so users can tell the original debit from its
    refund.
    """
    is_reversal = False
    body = narration
    head = body.lstrip().upper()
    if head.startswith("REV:"):
        is_reversal = True
        body = body.split(":", 1)[1]  # drop "REV:"
    parts = _segments(body, "/")
    if len(parts) < 3:
        return None
    biller = _seg(parts, 2)
    if not biller:
        return None
    return f"{biller} (Reversal)" if is_reversal else biller


def _extract_pcd(narration: str) -> str | None:
    """POS card debit: `PCD/<card_last4>/<merchant>/<loc><date>/<time>`.

    Counterparty is segment 2 (the merchant).
    """
    parts = _segments(narration, "/")
    if not parts or parts[0].upper() != "PCD":
        return None
    return _seg(parts, 2)


_SELF_PREFIXES = (
    "KOTAK811/",
    "INT.PD:",
    "INT PD:",
)
_SELF_CONTAINS = (
    "CASHBACK",
    "811 SUPER PROGRAM RENEWAL",
)


def extract_counterparty(
    narration: str,
    channel: str | None = None,
    direction: str | None = None,
) -> str | None:
    """Derive a clean counterparty from a Kotak statement narration."""
    del channel, direction  # not needed for Kotak layouts

    if not narration:
        return None

    head = narration.lstrip().upper()

    if head.startswith("UPI/"):
        return _extract_upi(narration)
    if head.startswith(("811:BBPS/", "REV:811:BBPS/")):
        return _extract_bbps(narration)
    if head.startswith("PCD/"):
        return _extract_pcd(narration)

    # Bank-internal narrations (interest, cashbacks, account program fees,
    # internal ref transfers) — counterparty is the bank itself.
    if head.startswith(_SELF_PREFIXES):
        return "Self"
    if any(needle in head for needle in _SELF_CONTAINS):
        return "Self"

    return None


__all__ = ["extract_counterparty"]
