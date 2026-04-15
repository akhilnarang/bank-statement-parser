"""CLI entrypoint for bank account statement parsing.

Workflow:
1) extract raw PDF structure,
2) select parser profile,
3) print rich tables for quick inspection,
4) optionally export JSON or CSV.
"""

import csv
import getpass
import json
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from bank_statement_parser.extractor import extract_raw_pdf, is_pdf_encrypted
from bank_statement_parser.models import ParsedBankStatement
from bank_statement_parser.parsers.factory import get_parser
from bank_statement_parser.parsers.registry import get_supported_bank_slugs

_SUPPORTED_BANK_SLUGS = get_supported_bank_slugs()


class BankOption(StrEnum):
    hdfc = "hdfc"
    icici = "icici"
    idfc = "idfc"
    indusind = "indusind"
    kotak = "kotak"
    slice = "slice"
    uboi = "uboi"


if tuple(option.value for option in BankOption) != _SUPPORTED_BANK_SLUGS:
    raise RuntimeError("BankOption enum is out of sync with parser registry")


def write_transactions_csv(parsed: ParsedBankStatement, output_path: Path) -> None:
    """Write flattened transaction rows for spreadsheet analysis."""
    fieldnames = [
        "bank",
        "file",
        "date",
        "narration",
        "transaction_type",
        "amount",
        "balance",
        "reference_number",
        "channel",
        "value_date",
    ]

    rows: list[dict[str, str]] = []
    for txn in parsed.transactions:
        rows.append(
            {
                "bank": parsed.bank,
                "file": parsed.file,
                "date": txn.date,
                "narration": txn.narration,
                "transaction_type": txn.transaction_type,
                "amount": txn.amount,
                "balance": txn.balance or "",
                "reference_number": txn.reference_number or "",
                "channel": txn.channel or "",
                "value_date": txn.value_date or "",
            }
        )

    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_compact_table(output_data: ParsedBankStatement) -> None:
    """Render parsed output as Rich tables."""
    console = Console()

    # Header info
    console.print(f"Bank: {output_data.bank}")
    if output_data.account_holder_name:
        console.print(f"Name: {output_data.account_holder_name}")
    if output_data.account_number:
        console.print(f"Account: {output_data.account_number}")
    if output_data.statement_period_start and output_data.statement_period_end:
        console.print(
            f"Period: {output_data.statement_period_start} to {output_data.statement_period_end}"
        )
    if output_data.opening_balance:
        console.print(f"Opening Balance: {output_data.opening_balance}")
    if output_data.closing_balance:
        console.print(f"Closing Balance: {output_data.closing_balance}")
    console.print()

    # Transactions table
    table = Table(title="Transactions")
    table.add_column("Date", style="cyan", no_wrap=True)
    table.add_column("Narration", style="white")
    table.add_column("Channel", style="yellow", no_wrap=True)
    table.add_column("Type", style="white", no_wrap=True)
    table.add_column("Amount", justify="right", style="magenta")
    table.add_column("Balance", justify="right", style="green")

    for txn in output_data.transactions:
        style = "red" if txn.transaction_type == "debit" else "green"
        table.add_row(
            txn.date,
            txn.narration[:60],
            txn.channel or "",
            txn.transaction_type,
            f"[{style}]{txn.amount}[/{style}]",
            txn.balance or "",
        )

    console.print(table)

    # Summary
    console.print()
    console.print(
        f"Debits:  {output_data.debit_count} txns, total {output_data.debit_total}"
    )
    console.print(
        f"Credits: {output_data.credit_count} txns, total {output_data.credit_total}"
    )

    # Reconciliation
    recon = output_data.reconciliation
    if recon:
        console.print()
        recon_table = Table(title="Balance Reconciliation")
        recon_table.add_column("Metric", style="white")
        recon_table.add_column("Value", style="magenta")
        recon_table.add_row("Opening Balance", recon.opening_balance)
        recon_table.add_row("Closing Balance", recon.closing_balance)
        recon_table.add_row("Debit Total", recon.parsed_debit_total)
        recon_table.add_row("Credit Total", recon.parsed_credit_total)
        recon_table.add_row("Computed Closing", recon.computed_closing_balance)

        delta_style = "green" if recon.balance_delta in ("0.00", "0") else "red bold"
        recon_table.add_row(
            "Delta", f"[{delta_style}]{recon.balance_delta}[/{delta_style}]"
        )
        console.print(recon_table)


def extract_with_password_prompt(
    pdf_path: Path,
    include_blocks: bool,
) -> dict[str, Any]:
    """Extract raw PDF data, prompting for password when required."""
    if not is_pdf_encrypted(pdf_path):
        return extract_raw_pdf(pdf_path, include_blocks=include_blocks, password=None)

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        password = getpass.getpass("PDF is encrypted. Enter password: ")
        try:
            return extract_raw_pdf(
                pdf_path,
                include_blocks=include_blocks,
                password=password,
            )
        except ValueError as error:
            if "Failed to decrypt PDF" in str(error) and attempt < max_attempts:
                print(f"Incorrect password ({attempt}/{max_attempts}). Try again.")
                continue
            raise

    raise ValueError("Failed to decrypt PDF.")


def parse_statement(
    pdf: Path = typer.Argument(..., help="Path to the PDF file"),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output JSON path when using -v",
    ),
    export_csv: Path | None = typer.Option(
        None,
        "--export-csv",
        help="Write flattened transaction CSV",
    ),
    export_json: Path | None = typer.Option(
        None,
        "--export-json",
        help="Write parsed JSON",
    ),
    export_raw_json: Path | None = typer.Option(
        None,
        "--export-raw-json",
        help="Write raw extractor JSON",
    ),
    skip_blocks: bool = typer.Option(
        False,
        "--skip-blocks",
        help="Skip PyMuPDF block extraction",
    ),
    verbose: int = typer.Option(
        0,
        "-v",
        count=True,
        help="Write JSON output (-v parsed, -vv +debug, -vvv +raw)",
    ),
    bank: BankOption = typer.Option(
        ...,
        "--bank",
        help="Bank name (required)",
    ),
) -> None:
    """Parse a bank account statement PDF and print normalized tables."""
    if not pdf.exists():
        raise typer.BadParameter(f"File not found: {pdf}")
    if pdf.suffix.lower() != ".pdf":
        raise typer.BadParameter("Input must be a .pdf file")

    try:
        raw_data = extract_with_password_prompt(pdf, include_blocks=not skip_blocks)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    parser_impl = get_parser(bank.value)
    parsed = parser_impl.parse(raw_data)

    print_compact_table(parsed)
    typer.echo(f"Transactions: {len(parsed.transactions)}")

    if verbose > 0:
        output_path: Path = output or (Path.cwd() / f"run_{uuid.uuid7().hex}.json")
        parsed_dict = parsed.model_dump()
        parsed_dict["bank_parser"] = parser_impl.bank

        if verbose >= 3:
            output_obj: Any = {
                "parsed": parsed_dict,
                "debug": parser_impl.build_debug(raw_data),
                "raw": raw_data,
            }
        elif verbose == 2:
            output_obj = {
                "parsed": parsed_dict,
                "debug": parser_impl.build_debug(raw_data),
            }
        else:
            output_obj = parsed_dict

        output_path.write_text(
            json.dumps(output_obj, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        typer.echo(f"Wrote extraction to {output_path}")

    if export_json is not None:
        parsed_dict = parsed.model_dump()
        parsed_dict["bank_parser"] = parser_impl.bank
        export_json.write_text(
            json.dumps(parsed_dict, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        typer.echo(f"Wrote parsed JSON to {export_json}")

    if export_raw_json is not None:
        export_raw_json.write_text(
            json.dumps(raw_data, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        typer.echo(f"Wrote raw JSON to {export_raw_json}")

    if export_csv is not None:
        write_transactions_csv(parsed, export_csv)
        typer.echo(f"Wrote CSV to {export_csv}")


def main() -> None:
    """Program entrypoint for console script execution."""
    typer.run(parse_statement)


if __name__ == "__main__":
    main()
