"""PDF extraction / decryption tests.

Fixtures are generated in-memory (no real personal data). The key case is
a PDF encrypted with an *empty user password* — the pattern banks use so a
statement opens in a browser without a prompt while still being encrypted.
"""

import io
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from bank_statement_parser.extractor import (
    is_pdf_encrypted,
    prepare_pdf_bytes_if_encrypted,
)


def _write_pdf(path: Path, *, user_password: str | None) -> None:
    """Write a one-page PDF, optionally encrypted with the given user password."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if user_password is not None:
        # owner password differs so the file is genuinely encrypted, but the
        # (empty) user password is what a reader would auto-try.
        writer.encrypt(user_password=user_password, owner_password="owner-secret")
    with path.open("wb") as handle:
        writer.write(handle)


def test_empty_user_password_pdf_not_reported_as_requiring_password(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "empty_pw.pdf"
    _write_pdf(pdf_path, user_password="")

    # Sanity: the file really is encrypted at the PDF level.
    assert PdfReader(str(pdf_path)).is_encrypted is True

    # ...but it does not require a password from the user.
    assert is_pdf_encrypted(pdf_path) is False


def test_empty_user_password_pdf_decrypts_without_password(tmp_path: Path) -> None:
    pdf_path = tmp_path / "empty_pw.pdf"
    _write_pdf(pdf_path, user_password="")

    pdf_bytes, info, _meta = prepare_pdf_bytes_if_encrypted(pdf_path, password=None)

    assert info["is_encrypted"] is True
    assert info["was_decrypted"] is True
    assert pdf_bytes is not None
    # The returned bytes must be a readable, decrypted PDF.
    assert PdfReader(io.BytesIO(pdf_bytes)).is_encrypted is False


def test_unencrypted_pdf_unchanged(tmp_path: Path) -> None:
    pdf_path = tmp_path / "plain.pdf"
    _write_pdf(pdf_path, user_password=None)

    assert is_pdf_encrypted(pdf_path) is False
    pdf_bytes, info, _meta = prepare_pdf_bytes_if_encrypted(pdf_path, password=None)
    assert pdf_bytes is None
    assert info == {"is_encrypted": False, "was_decrypted": False}


def test_real_user_password_still_required(tmp_path: Path) -> None:
    pdf_path = tmp_path / "protected.pdf"
    _write_pdf(pdf_path, user_password="s3cret")

    # A non-empty user password must still be demanded and honored.
    assert is_pdf_encrypted(pdf_path) is True

    with pytest.raises(ValueError, match="Password is required"):
        prepare_pdf_bytes_if_encrypted(pdf_path, password=None)

    pdf_bytes, info, _meta = prepare_pdf_bytes_if_encrypted(pdf_path, password="s3cret")
    assert info["was_decrypted"] is True
    assert pdf_bytes is not None
