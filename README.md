## bank-statement-parser

Parses bank account statement PDFs (savings/current accounts) into structured output for reconciliation and analysis. Parallel to [`cc-parser`](https://github.com/akhilnarang/cc-parser) but for bank account statements instead of credit card statements.

Supported banks: HDFC, ICICI, IDFC FIRST, IndusInd, Kotak Mahindra, Slice, Union Bank of India.

Adding a new bank? Use the skill at `.agents/skills/add-bank-parser/` to guide the process.

## Output

Each parser returns a `ParsedBankStatement` with:
- `account_holder_name`, `account_number`
- `statement_period_start`, `statement_period_end` (DD/MM/YYYY)
- `opening_balance`, `closing_balance`
- `transactions` — list of `BankTransaction` with date, narration, amount, debit/credit, running balance, reference number, channel (upi/neft/rtgs/imps/etc.), and a `counterparty` derived from the narration
- `reconciliation` — balance verification (`opening + credits - debits` vs `closing`, delta must be `0.00`)

### Counterparty labels

The per-bank counterparty extractor cleans a payee/beneficiary out of structured
narrations. Two canonical labels replace an extracted name when the narration is
about the account holder's own money:

- `Self` — an internal move, cashback, or interest credit with no external party.
- `<Bank> FD` (e.g. `IDFC FD`, `Slice FD`) — a fixed-deposit booking or maturity.
  A booking debits the account; a maturity credits principal (and interest) back.

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
uv run ty check bank_statement_parser/
```

Notes:
- `tests/` is intentionally empty right now, so `uv run pytest tests/` exits with "no tests ran".
- Parser registration is centralized in `bank_statement_parser/parsers/registry.py`; `factory.py`, the CLI, and compatibility re-exports continue to work.
- Shared parser internals now live under `bank_statement_parser/parsers/{extractors,utils,metadata,reconciliation}` with compatibility shims preserved from `parsers/generic.py`.
