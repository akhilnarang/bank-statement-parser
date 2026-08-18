"""UBOI-specific counterparty extraction from statement narrations.

Union Bank of India layouts:

- `UPIAB|UPIAR/<rrn>/<CR|DR>/<NAME>/<BANK>/<vpa>` — counterparty is the name
  (segment 3); the vpa (segment 5) is the fallback.
- `IMPSAB|IMPSAR/<rrn>/<NAME>/<acct>` — counterparty is the name (segment 2).
- `POS:<MERCHANT>/<location>/<ref>` — counterparty is the merchant.
- `NEFT:<NAME> <ifsc>` / `RTGS:<NAME> <ref>` / `NEFTO-<NAME> <acct>` — the name
  runs up to a trailing reference/IFSC/account token, which is dropped.
- `CLG:<NAME>` — counterparty is the name.
- `REFUND/<ref>/<ref>` maps to `Refund`; interest-paid lines map to `Interest`.

Returns None when the narration doesn't match a known layout, so the caller
falls back to the raw narration.
"""

import re

_TRAILING_REF_RE = re.compile(r"[A-Z0-9]*\d[A-Z0-9]*$")


def _strip_trailing_ref(text: str) -> str | None:
    """Drop a trailing reference/IFSC/account token from a name.

    A trailing token is dropped only when it is at least 6 characters and
    carries a digit, so a code like `HDFCH0068` or `002168776030` goes but a
    plain name word stays.
    """
    tokens = text.split()
    if len(tokens) > 1 and len(tokens[-1]) >= 6 and _TRAILING_REF_RE.fullmatch(tokens[-1]):
        tokens = tokens[:-1]
    return " ".join(tokens).strip() or None


def _extract_upi(narration: str) -> str | None:
    """`UPIAB|UPIAR/<rrn>/<CR|DR>/<NAME>/<BANK>/<vpa>`. Name, else vpa."""
    parts = [p.strip() for p in narration.split("/")]
    if len(parts) >= 4 and parts[3]:
        return parts[3]
    if len(parts) >= 6 and parts[5]:
        return parts[5]
    return None


def _extract_imps(narration: str) -> str | None:
    """`IMPSAB|IMPSAR/<rrn>/<NAME>/<acct>`. Counterparty is segment 2."""
    parts = [p.strip() for p in narration.split("/")]
    if len(parts) >= 3 and parts[2]:
        return parts[2]
    return None


def _extract_pos(narration: str) -> str | None:
    """`POS:<MERCHANT>/<location>/<ref>`. Counterparty is the merchant."""
    body = narration.split(":", 1)[1] if ":" in narration else narration
    merchant = body.split("/")[0].strip()
    return merchant or None


def extract_counterparty(
    narration: str,
    channel: str | None = None,
    direction: str | None = None,
) -> str | None:
    """Derive a clean counterparty from a UBOI statement narration."""
    del channel, direction

    if not narration:
        return None

    head = narration.lstrip().upper()

    if head.startswith(("UPIAB/", "UPIAR/")):
        return _extract_upi(narration)
    if head.startswith(("IMPSAB/", "IMPSAR/")):
        return _extract_imps(narration)
    if head.startswith("POS:"):
        return _extract_pos(narration)
    if head.startswith("NEFTO-"):
        return _strip_trailing_ref(narration.lstrip()[6:].strip())
    if head.startswith(("NEFT:", "RTGS:", "CLG:")):
        return _strip_trailing_ref(narration.split(":", 1)[1].strip())
    if head.startswith("REFUND/"):
        return "Refund"
    if "INT.PD" in head:
        return "Interest"

    return None


__all__ = ["extract_counterparty"]
