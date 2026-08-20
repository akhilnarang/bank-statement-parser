"""IDFC-specific counterparty extraction from statement narrations.

Narration layouts:

- UPI: `UPI/(CR|DR)/<rrn>/<name>/<vpa>/<bank>/<note>`
- IMPS / IMPS-OPM: `IMPS[-OPM]/<rrn>/<name>/<ifsc>/<acct>/<remark>`
- RTGS / NEFT slash form: `RTGS/<utr>/<name>/<ifsc>[/<remark>]`
- Ecom: `Ecom/<id>/<provider>/<merchant>/<description>`
- POS-VISA / POS-RUPAY: `POS-(VISA|RUPAY)/<merchant>/<rrn>/<loc><date>/<time>`
- REF/POS-... (refund): `REF/POS-VISA/<merchant>/<rrn>/<mcc>/<date>`
- IFT (intra-IDFC): `IFT/<id>/<seg2>/<id>/<seg4>`
- FD creation: `FD <fd_number> Mr./Mrs./Ms. <name>`
- FD maturity: `FD <fd_number> maturity :Account credited/Principal:.../...`
- Transfer to deposit: `TRANSFER TO DEPOSIT: CHEQUE NO. <n>/FT From TO <src> to <dst>`

Returns None when the narration is informational and doesn't match a
known layout; callers fall back to the raw narration.
"""

import re


def _segments(narration: str, sep: str) -> list[str]:
    return [s.strip() for s in narration.split(sep)]


def _seg(parts: list[str], idx: int) -> str | None:
    """Return parts[idx] stripped, or None if out of range / empty."""
    if 0 <= idx < len(parts):
        val = parts[idx].strip()
        return val or None
    return None


def _extract_upi(narration: str) -> str | None:
    """IDFC UPI: `UPI/(CR|DR)/<rrn>/<name>/<vpa>/<bank>/<note>`.

    Counterparty is segment 3 (the name). Falls back to segment 2 when
    segment 1 isn't the direction marker (defensive).
    """
    parts = _segments(narration, "/")
    if len(parts) < 4:
        return None
    if parts[1].upper() in {"CR", "DR"}:
        return _seg(parts, 3)
    # Fallback if the direction segment is absent.
    return _seg(parts, 1)


def _extract_imps(narration: str) -> str | None:
    """IDFC IMPS variants:

    - `IMPS/<rrn>/<name>/<ifsc>/<acct>/<remark>`
    - `IMPS-OPM/<rrn>/<name>/<ifsc>/<acct>/<remark>`

    Counterparty is segment 2 (immediately after the RRN).
    """
    parts = _segments(narration, "/")
    if not parts:
        return None
    head = parts[0].upper()
    if head not in {"IMPS", "IMPS-OPM"}:
        return None
    # parts: [IMPS|IMPS-OPM, rrn, name, ifsc, acct, remark]
    return _seg(parts, 2)


_UTR_PATTERN = re.compile(r"\b([A-Z]{4}[A-Z0-9]\d{7,}(?:\s\d{1,4})?)\b")


def _extract_neft_rtgs(narration: str) -> str | None:
    """IDFC NEFT/RTGS slash form: `(RTGS|NEFT)/<utr>/<name>/<ifsc>[/<remark>]`.

    Counterparty is the segment immediately after the UTR.
    """
    parts = _segments(narration, "/")
    if not parts:
        return None
    head = parts[0].upper()
    if head not in {"RTGS", "NEFT"}:
        return None
    utr_idx = next(
        (i for i, p in enumerate(parts) if _UTR_PATTERN.fullmatch(p)),
        -1,
    )
    if utr_idx == -1 or utr_idx + 1 >= len(parts):
        return None
    return _seg(parts, utr_idx + 1)


def _extract_pos(narration: str) -> str | None:
    """POS card transactions:

    - `POS-VISA/<merchant>/<rrn>/<loc><date>/<time>`
    - `POS-RUPAY/<merchant>/<rrn>/<loc>/<time>`

    Counterparty is segment 1 (the merchant).
    """
    parts = _segments(narration, "/")
    if not parts:
        return None
    head = parts[0].upper()
    if not (head.startswith("POS-")):
        return None
    return _seg(parts, 1)


def _extract_ref_pos(narration: str) -> str | None:
    """Refund: `REF/POS-VISA/<merchant>/<rrn>/<mcc>/<date>`.

    Counterparty is segment 2 (the merchant).
    """
    parts = _segments(narration, "/")
    if len(parts) < 3 or parts[0].upper() != "REF":
        return None
    if not parts[1].upper().startswith("POS"):
        return None
    return _seg(parts, 2)


def _extract_ecom(narration: str) -> str | None:
    """E-commerce: `Ecom/<id>/<gateway>/<counterparty>/<description>`.

    Counterparty is segment 3; segment 4 is an optional free-text
    description (e.g. `Selftransfer`, payee remark). When both are
    present, combine them as `<counterparty> (<description>)` so
    Razorpay/IndiaIdeas rows carry the extra hint without losing the
    payee. For RazorpayTP rows the counterparty segment is sometimes an
    opaque tracking code — there's no way to recover the real merchant,
    so we surface it as-is.
    """
    parts = _segments(narration, "/")
    if not parts or parts[0].upper() != "ECOM":
        return None
    counterparty = _seg(parts, 3)
    description = _seg(parts, 4)
    if counterparty and description:
        return f"{counterparty} ({description})"
    if counterparty:
        return counterparty
    return _seg(parts, 2)


def _extract_ift(narration: str, direction: str | None) -> str | None:
    """Intra-IDFC funds transfer: `IFT/<txn id>/<seg2>/<id>/<seg4>`.

    Format is direction-sensitive:
    - credit (incoming): seg2 is the routing gateway (e.g. a payroll
      provider), seg4 is the real originator (e.g. the employer). Use
      seg4.
    - debit (outgoing): seg2 is the recipient; seg4 is the user's remark
      (e.g. `Test`). Use seg2.
    """
    parts = _segments(narration, "/")
    if not parts or parts[0].upper() != "IFT":
        return None
    seg2 = _seg(parts, 2)
    seg4 = _seg(parts, 4)
    if direction == "credit":
        return seg4 or seg2
    return seg2 or seg4


_FD_LABEL = "IDFC FD"
_FD_RE = re.compile(
    r"^\s*FD\s+\d+\s+(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?)\s+(.+?)\s*$",
    re.IGNORECASE,
)
_FD_MATURITY_RE = re.compile(r"^\s*FD\s+\d+\s+maturity\b", re.IGNORECASE)
_TRANSFER_DEPOSIT_RE = re.compile(
    r"FT\s+From\s+TO\s+(?P<src>.+?)\s+to\s+(?P<dst>.+?)\s*$",
    re.IGNORECASE,
)


def _names_match(a: str, b: str) -> bool:
    """Loose equality for two name strings, tolerating PDF text truncation
    and stray whitespace (e.g. `JOHN MICHAEL DOE` vs `John michael d`)."""
    norm = lambda s: re.sub(r"\s+", "", s).upper()
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    return na.startswith(nb) or nb.startswith(na)


def _extract_transfer_or_fd(narration: str) -> str | None:
    """`FD <num> ...` or `TRANSFER TO DEPOSIT: ... FT From TO <src> to <dst>`.

    An FD booking (`FD <num> Mr. <name>`) or maturity (`FD <num> maturity ...`)
    is the account holder's own deposit, so returns the "IDFC FD" label. The
    downstream categorizer reads it as an investment (debit) or a redemption
    (credit). Transfer-to-deposit is a cheque move, overwhelmingly self; when
    src ~= dst (modulo truncation), returns Self. Otherwise the destination name.
    """
    if _FD_RE.match(narration) or _FD_MATURITY_RE.match(narration):
        return _FD_LABEL

    m = _TRANSFER_DEPOSIT_RE.search(narration)
    if m:
        src = m.group("src").strip()
        dst = m.group("dst").strip()
        if src and dst and _names_match(src, dst):
            return "Self"
        return dst or src or None

    return None


def extract_counterparty(
    narration: str,
    channel: str | None,
    direction: str | None = None,
) -> str | None:
    """Derive a clean counterparty from an IDFC statement narration.

    `direction` is `"debit"` or `"credit"`; IFT narrations use it to pick
    between the recipient (debit) and the originator (credit). Returns
    None when the narration doesn't match a known layout.
    """
    if not narration:
        return None

    # Try layout-specific extractors in priority order. The first one whose
    # prefix matches the narration head wins, regardless of channel — IDFC
    # narrations are prefix-driven and `detect_channel` can mislabel some
    # POS / Ecom rows.
    head = narration.lstrip().upper()

    if head.startswith("REF/POS"):
        return _extract_ref_pos(narration)
    if head.startswith("POS-"):
        return _extract_pos(narration)
    if head.startswith("ECOM/"):
        return _extract_ecom(narration)
    if head.startswith("IFT/"):
        return _extract_ift(narration, direction)
    if head.startswith(("IMPS/", "IMPS-OPM/")):
        return _extract_imps(narration)
    if head.startswith(("RTGS/", "NEFT/")):
        return _extract_neft_rtgs(narration)
    if head.startswith("UPI/"):
        return _extract_upi(narration)
    if head.startswith("FD ") or "TRANSFER TO DEPOSIT" in head:
        return _extract_transfer_or_fd(narration)

    # Wallet self-top-ups, interest credits, and delayed-interest credits
    # are all "Self" — counterparty is the user's own account.
    if head.startswith("ADDMONEY/"):
        return "Self"
    if "MONTHLY SAVINGS INTEREST" in head or head.startswith("DELAYINT_"):
        return "Self"

    # Redemption fees and their GST components: extract the descriptor
    # before the first `/` (e.g. `Redemption Fees on FIRST Rewards`,
    # `CGST on Redemption Fees on FIRST Rewards`).
    if "REDEMPTION FEES" in head:
        first_seg = narration.split("/", 1)[0].strip()
        return first_seg or None

    # PMSBY (Pradhan Mantri Suraksha Bima Yojana) — annual insurance premium
    # auto-debited; extract the scheme label, dropping the date suffix.
    if "PMSBY" in head and (m := re.match(r"^(.*?PMSBY)\b", narration, re.IGNORECASE)):
        return m.group(1).strip()

    # Channel-only fallback (for narrations whose head we didn't match but
    # still have a known channel — rare in IDFC, but defensive).
    ch = channel.lower() if channel else None
    if ch == "upi":
        return _extract_upi(narration)
    if ch == "imps":
        return _extract_imps(narration)
    if ch in {"neft", "rtgs"}:
        return _extract_neft_rtgs(narration)

    return None


__all__ = ["extract_counterparty"]
