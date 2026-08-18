"""SBI-specific counterparty extraction from statement narrations.

Only the UPI layout is currently mapped:

- `UPI/<CR|DR>/<rrn>/<NAME>/<BANK>/<vpa>/<remark>` — counterparty is the name
  (segment 3, after the CR/DR direction marker).

Other SBI narration layouts (NEFT/IMPS/ATM/cheque/charges) are not mapped yet,
so they return None and the caller falls back to the raw narration.
"""


def _extract_upi(narration: str) -> str | None:
    """`UPI/<CR|DR>/<rrn>/<NAME>/<BANK>/<vpa>/<remark>`. Name is segment 3."""
    parts = [p.strip() for p in narration.split("/")]
    if len(parts) >= 4 and parts[1].upper() in ("CR", "DR"):
        return parts[3] or None
    return None


def extract_counterparty(
    narration: str,
    channel: str | None = None,
    direction: str | None = None,
) -> str | None:
    """Derive a clean counterparty from an SBI statement narration."""
    del channel, direction

    if not narration:
        return None
    if narration.lstrip().upper().startswith("UPI/"):
        return _extract_upi(narration)
    return None


__all__ = ["extract_counterparty"]
