"""SBI-specific counterparty extraction from statement narrations.

Mapped layouts:

- `UPI/<CR|DR>/<rrn>/<NAME>/<BANK>/<vpa>/<remark>`: the name is segment 3.
- `IMPS/<rrn>/<BANK>-<masked account>-<NAME>/<remark>`: the name follows the
  second dash of segment 2.
- `NEFT*<ifsc>*<utr>*<NAME>`: the name is segment 3.
- `OTHPG <rrn><MERCHANT> <city>`: a debit-card purchase. The merchant is the
  text after the 12-digit RRN, without the last token.

Other SBI narration layouts (ATM/cheque/charges) return None, and the caller
falls back to the raw narration.
"""

import re

_CARD_RE = re.compile(r"^OTHPG\s+\d{12}(.+)$", re.IGNORECASE)


def _extract_upi(narration: str) -> str | None:
    """`UPI/<CR|DR>/<rrn>/<NAME>/<BANK>/<vpa>/<remark>`. Name is segment 3."""
    parts = [p.strip() for p in narration.split("/")]
    if len(parts) >= 4 and parts[1].upper() in ("CR", "DR"):
        return parts[3] or None
    return None


def _extract_imps(narration: str) -> str | None:
    """`IMPS/<rrn>/<BANK>-<masked account>-<NAME>/<remark>`."""
    parts = narration.split("/")
    if len(parts) >= 3 and len(pieces := parts[2].split("-", 2)) == 3:
        return pieces[2].strip() or None
    return None


def _extract_neft(narration: str) -> str | None:
    """`NEFT*<ifsc>*<utr>*<NAME>`. Name is segment 3."""
    parts = narration.split("*")
    if len(parts) >= 4:
        return parts[3].strip() or None
    return None


def _extract_card(narration: str) -> str | None:
    """`OTHPG <rrn><MERCHANT> <city>`. Merchant is the text after the RRN."""
    if not (match := _CARD_RE.match(narration)):
        return None
    tokens = match.group(1).split()
    # ponytail: drops the last token as the city. A city glued to the
    # merchant, or a two-word city, stays partly in the name.
    return " ".join(tokens[:-1] if len(tokens) > 1 else tokens) or None


def extract_counterparty(
    narration: str,
    channel: str | None = None,
    direction: str | None = None,
) -> str | None:
    """Derive a clean counterparty from an SBI statement narration."""
    del channel, direction

    if not narration:
        return None
    head = narration.lstrip().upper()
    if head.startswith("IMPS/"):
        return _extract_imps(narration)
    if head.startswith("NEFT*"):
        return _extract_neft(narration)
    if head.startswith("OTHPG "):
        return _extract_card(narration)
    # Monthly narrations can put a "TO TRANSFER-" label before the UPI layout.
    if (start := head.find("UPI/")) == -1:
        return None
    return _extract_upi(narration[start:])


__all__ = ["extract_counterparty"]
