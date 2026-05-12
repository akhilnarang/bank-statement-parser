"""HDFC-specific counterparty extraction from statement narrations.

Layouts (consistent across both HDFC statement formats):

- `UPI-<name>-<vpa>-<ifsc>-<rrn>-<remark>` (counterparty = seg 1)
- `IMPS-<rrn>-<name>-<bank>-<masked_acct>-<remark>` (counterparty = seg 2)
- `ACH D- <scheme> <date> <proc>-<ref>` (debit)
- `ACHC-<scheme>-<ref>` (credit; counterparty = seg 1)
- `POS<long_card_masked>...HH:MM:SS<merchant>` — merchant is the text
  after the last timestamp on the line.

`IBSSFUNDSTRANSFERDR/CR-<ref>` and `DEBITCARDCASHBACK` map to `Self`.
"""

import re


def _split_dash(narration: str) -> list[str]:
    return [s.strip() for s in narration.split("-")]


def _seg(parts: list[str], idx: int) -> str | None:
    if 0 <= idx < len(parts):
        val = parts[idx].strip()
        return val or None
    return None


def _extract_upi(narration: str) -> str | None:
    """`UPI-<NAME>-<vpa>-<ifsc>-<rrn>-<remark>`. Counterparty is segment 1."""
    parts = _split_dash(narration)
    if len(parts) < 2 or parts[0].upper() != "UPI":
        return None
    return _seg(parts, 1)


def _extract_imps(narration: str) -> str | None:
    """`IMPS-<rrn>-<NAME>-<bank>-<masked_acct>-<remark>`.

    Counterparty is segment 2. The HDFC PDF text-flow occasionally wraps
    the name onto the next line, leaving a stray space inside what
    should be a single dash-segment (`JOHN DOE PLACEHOLD-I NDB`). We
    accept that as-is since collapsing it would require knowing the
    intended segment boundaries.
    """
    parts = _split_dash(narration)
    if len(parts) < 3 or parts[0].upper() != "IMPS":
        return None
    return _seg(parts, 2)


_ACH_DEBIT_RE = re.compile(r"^ACH\s+D-\s*(.+?)(?:-\d{4,})?$", re.IGNORECASE)


def _extract_ach_debit(narration: str) -> str | None:
    """`ACH D- <SCHEME> <date> <PROC>-<ref>`.

    The dash after `ACH D` is the only structural delimiter. The trailing
    `-<ref>` is dropped; everything else up to it (scheme, date,
    processor) is returned as the counterparty.
    """
    m = _ACH_DEBIT_RE.match(narration.strip())
    if not m:
        return None
    candidate = m.group(1).strip()
    return candidate or None


def _extract_achc(narration: str) -> str | None:
    """`ACHC-<SCHEME>-<ref>`. Counterparty is segment 1 (the scheme)."""
    parts = _split_dash(narration)
    if len(parts) < 2 or parts[0].upper() != "ACHC":
        return None
    return _seg(parts, 1)


_POS_TIME_RE = re.compile(r"\d{1,2}:\d{2}:\d{2}")


def _extract_pos(narration: str) -> str | None:
    """POS card transactions always end with `HH:MM:SS<MERCHANT>`.

    The merchant text is whatever follows the last timestamp on the line.
    PDF whitespace artefacts inside the merchant text are preserved as-is.
    """
    matches = list(_POS_TIME_RE.finditer(narration))
    if not matches:
        return None
    tail = narration[matches[-1].end():].strip()
    return tail or None


def extract_counterparty(
    narration: str,
    channel: str | None = None,
    direction: str | None = None,
) -> str | None:
    """Derive a clean counterparty from an HDFC statement narration."""
    del channel, direction

    if not narration:
        return None

    head = narration.lstrip().upper()

    # Bank-internal flows: HDFC's "Inter-Branch Settlement System" funds
    # transfer (IBSS) and debit-card cashback have no external party.
    if head.startswith(("IBSSFUNDSTRANSFERDR", "IBSSFUNDSTRANSFERCR")):
        return "Self"
    if head.startswith("DEBITCARDCASHBACK"):
        return "Self"

    if head.startswith("UPI-"):
        return _extract_upi(narration)
    if head.startswith("IMPS-"):
        return _extract_imps(narration)
    if head.startswith("ACHC-"):
        return _extract_achc(narration)
    if head.startswith("ACH D-") or head.startswith("ACH D -"):
        return _extract_ach_debit(narration)
    if head.startswith("POS"):
        return _extract_pos(narration)

    return None


__all__ = ["extract_counterparty"]
