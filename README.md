## bank-statement-parser

Parses bank account statement PDFs (savings/current accounts) into structured output for reconciliation and analysis. Parallel to [`cc-parser`](https://github.com/akhilnarang/cc-parser) but for bank account statements instead of credit card statements.

Supported banks: HDFC, ICICI, IDFC FIRST, IndusInd, Slice, Union Bank of India.

Adding a new bank? Use the skill at `.agents/skills/add-bank-parser/` to guide the process.

## Output

Each parser returns a `ParsedBankStatement` with:
- `account_holder_name`, `account_number`
- `statement_period_start`, `statement_period_end` (DD/MM/YYYY)
- `opening_balance`, `closing_balance`
- `transactions` — list of `BankTransaction` with date, narration, amount, debit/credit, running balance, reference number, channel (upi/neft/rtgs/imps/etc.)
- `reconciliation` — balance verification (`opening + credits - debits` vs `closing`, delta must be `0.00`)

## Usage

```bash
uv run bank-statement-parser /path/to/statement.pdf --bank {hdfc|icici|idfc|indusind|slice|uboi}
```

Optional flags:
- `-v` / `-vv` / `-vvv` — write JSON output (parsed / +debug / +raw extractor payload)
- `--output PATH` — destination for JSON output
- `--export-json PATH` — write parsed JSON to a specific path
- `--export-csv PATH` — write flattened transaction rows
- `--export-raw-json PATH` — write raw pdfplumber extraction payload
- `--skip-blocks` — skip PyMuPDF block extraction for smaller output

The CLI prompts for a password if the PDF is encrypted.

## Privacy

- Statement PDFs contain highly sensitive financial data. Never commit them.
- `*.pdf`, `*.csv`, `*.json` exports are gitignored.
- Share only redacted outputs outside your local machine.

## Development

```bash
uv sync
uv run pytest tests/
uv run ruff check bank_statement_parser/
```
