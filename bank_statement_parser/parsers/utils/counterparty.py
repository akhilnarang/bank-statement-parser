"""Counterparty extraction from structured bank statement narrations.

Channel-aware: each channel has a known segment layout (mostly modelled on
ICICI savings, but the slash/dash patterns generalize across most Indian
banks). Returns None when the layout doesn't match — callers fall back to
the raw narration.
"""

from __future__ import annotations

import re

from bank_statement_parser.parsers.utils.channels import (
    _DIGIT_RRN_PATTERN,
    _UTR_PATTERN,
)


def _segments(narration: str, sep: str) -> list[str]:
    return [s.strip() for s in narration.split(sep)]


def _first_nonempty_after(segments: list[str], start: int) -> str | None:
    for s in segments[start:]:
        if s:
            return s
    return None


def _last_nonempty(segments: list[str]) -> str | None:
    for s in reversed(segments):
        if s:
            return s
    return None


def _extract_upi(narration: str) -> str | None:
    """UPI/<merchant>/<vpa>/<remarks>/<sender bank>/<rrn>/<txn id>.

    Counterparty is segment 1 (the merchant/recipient name).
    """
    parts = _segments(narration, "/")
    if len(parts) < 2:
        return None
    return parts[1] or None


def _extract_imps(narration: str) -> str | None:
    """ICICI savings IMPS layouts:

    - `MMT/IMPS/<rrn>/<remark>/<beneficiary>/<bank>`        (6 segs)
    - `MMT/IMPS/<rrn>/<beneficiary>/<bank>`                  (5 segs, no remark)
    - `<prefix> MMT/IMPS/<rrn>/<remark>/<beneficiary>/<bank>` (prefixed)

    The beneficiary is consistently the second-to-last segment, with the
    bank as the suffix. Falls back to RRN-based heuristic when no IMPS
    marker is present.
    """
    parts = _segments(narration, "/")
    if not parts:
        return None
    imps_idx = next(
        (i for i, p in enumerate(parts) if p.upper() == "IMPS"),
        -1,
    )
    if imps_idx >= 0:
        # At least IMPS + rrn + beneficiary + bank → 4 segs after IMPS marker
        if len(parts) - imps_idx >= 4:
            return parts[-2] or _first_nonempty_after(parts, imps_idx + 1)
        # No bank suffix → beneficiary is the last meaningful segment
        return _last_nonempty(parts[imps_idx + 1 :])
    # No IMPS marker — fall back to RRN-based heuristic
    for i, seg in enumerate(parts):
        if _DIGIT_RRN_PATTERN.fullmatch(seg):
            if i + 2 < len(parts) and parts[i + 2]:
                return parts[i + 2]
            return _first_nonempty_after(parts, i + 1)
    return None


def _extract_neft_rtgs(narration: str) -> str | None:
    """NEFT/RTGS narration layouts (ICICI savings):

    - `BIL/(NEFT|RTGS)/<utr>/<remark>/<beneficiary>/<bank>` (slash, BIL prefix)
    - `RTGS/<utr>/<dest_bank>/<beneficiary>`                (slash, no BIL)
    - `NEFT/<ifsc>/<dest_bank>/<utr>/<beneficiary>`         (slash, no BIL)
    - `NEFT-<utr>-<beneficiary>-<remark>-<acct>-<ifsc>`     (dash)
    - `RTGS-<utr>-<beneficiary>-<acct>-<ifsc>`              (dash)
    """
    # Pick the separator from the channel marker, not from "any slash in
    # the string" — embedded "/URGENT/" or "/ATTN/" remarks would otherwise
    # trick a dash-separated NEFT-... narration into being split on "/".
    head = narration.lstrip().upper()
    if head.startswith(("NEFT-", "RTGS-")):
        sep = "-"
    elif head.startswith(("NEFT/", "RTGS/", "BIL/")):
        sep = "/"
    else:
        sep = "/" if "/" in narration else "-"
    parts = _segments(narration, sep)
    if not parts:
        return None

    # BIL/NEFT, BIL/RTGS — beneficiary is second-to-last (last is bank)
    if parts[0].upper() == "BIL":
        if len(parts) >= 5:
            return parts[-2] or None
        return _last_nonempty(parts)

    utr_idx = next(
        (i for i, p in enumerate(parts) if _UTR_PATTERN.fullmatch(p)),
        -1,
    )
    if utr_idx == -1:
        return None

    after_utr = [p for p in parts[utr_idx + 1 :] if p]
    if not after_utr:
        return None

    # Dash separator: beneficiary is the segment immediately after UTR.
    if sep == "-":
        return after_utr[0]

    # Slash separator: the segment between UTR and beneficiary is usually a
    # destination-bank or IFSC token, so beneficiary is the *last* segment.
    return after_utr[-1]


_BIL_INFT_RE = re.compile(r"^\s*BIL\s*/\s*INFT\b", re.IGNORECASE)
_BIL_ONL_RE = re.compile(r"^\s*BIL\s*/\s*ONL\b", re.IGNORECASE)


def _extract_netbanking(narration: str) -> str | None:
    """ICICI net banking transfers.

    BIL/INFT/<txn id>/[<remark>/]<payee>   (intra-ICICI) — counterparty is
    the *last* non-empty segment after the txn id.
    BIL/ONL/<txn id>/<beneficiary>/<...>   (third-party) — counterparty is
    segment 3 (the beneficiary name, immediately after the txn id).
    """
    if _BIL_INFT_RE.match(narration):
        parts = _segments(narration, "/")
        # ['BIL', 'INFT', '<txn id>', ..., '<payee>']
        if len(parts) >= 4:
            return _last_nonempty(parts[3:])
        return None

    if _BIL_ONL_RE.match(narration):
        parts = _segments(narration, "/")
        # ['BIL', 'ONL', '<txn id>', '<beneficiary>', ...]
        if len(parts) >= 4:
            return parts[3] or None
        return None

    return None


def extract_counterparty(narration: str, channel: str | None) -> str | None:
    """Derive a clean counterparty from a structured statement narration.

    Returns None when the narration doesn't match a known structured layout.
    Callers should fall back to the raw narration in that case.
    """
    if not narration:
        return None

    ch = channel.lower() if channel else None

    if ch == "upi":
        return _extract_upi(narration)
    if ch == "imps":
        return _extract_imps(narration)
    if ch in {"neft", "rtgs"}:
        return _extract_neft_rtgs(narration)
    if ch == "netbanking":
        return _extract_netbanking(narration)

    return None


__all__ = ["extract_counterparty"]
