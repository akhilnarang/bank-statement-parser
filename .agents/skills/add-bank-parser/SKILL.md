---
name: add-bank-parser
description: Add a new bank-specific account statement PDF parser. Use when adding support for parsing a new bank's savings/current account statement PDF.
---

# Add a New Bank Statement Parser

**This skill is interactive.** It requires running Python/Bash to extract PDF data, iterating on the parser, and testing. Do not run this in the background. If you need tool permissions, ask for them.

Arguments: `$ARGUMENTS` — bank slug and path to sample PDF.

## Step 1: Study the codebase

Read these files to understand the patterns:
- `bank_statement_parser/models.py` — output schema (see Output Schema section below)
- `bank_statement_parser/parsers/generic.py` — compatibility re-exports and the generic parser flow
- `bank_statement_parser/parsers/registry.py` — canonical parser registration
- `bank_statement_parser/parsers/utils/` and `bank_statement_parser/parsers/extractors/` — reusable helpers you should prefer

Don't read a specific parser yet — wait until step 2 reveals whether the PDF uses tables or word-positioned text, then pick the most relevant existing parser to study.

## Step 2: Extract raw PDF data

**MANDATORY. Do not write any parser code before completing this step.**

The visual PDF layout and what pdfplumber extracts are often very different. You must run code to see what the extraction library actually produces. Run this via `uv run python -c "..."` from the `bank-statement-parser` directory:

```python
from bank_statement_parser.extractor import extract_raw_pdf
from pathlib import Path
raw = extract_raw_pdf(Path("<pdf_path>"), include_blocks=False, password=None)
```

Then examine the output **interactively** — this may take multiple rounds:

1. **Print all tables on all pages** (every row, not just the first few). Determine which table has transactions, the column count, and header names.
2. **Print page 1 text** (first ~800 chars) to find metadata patterns (account number, holder name, statement period).
   3. **If tables are empty or single-row**, the bank renders transactions as positioned text, not tables. Print word-lines instead:
    ```python
    from bank_statement_parser.parsers.extractors.wordlines import group_words_into_lines
    lines = group_words_into_lines(raw["pages"][N]["words"])
    ```
4. **For word-line parsing**, print x-positions (`w["x0"]`) of the header line and a few data lines to determine column boundaries.

If the PDF is encrypted, ask the user for the password.

Based on what you find, read the most relevant existing parser:
- **Clean tables** (proper headers, separate columns) → study `uboi.py`
- **Malformed tables** (merged columns on page 1, clean on page 2+) → study `idfc.py`
- **No tables / word-positioned text** → study `icici.py` or `slice.py`
- **Packed single-row tables** (all transactions in ONE row with `\n`-delimited cells) → study `hdfc.py`

## Step 3: Write the parser

Create `bank_statement_parser/parsers/{bank}.py`. Base your implementation on the **actual pdfplumber output from step 2**.

- Extend `GenericBankStatementParser`, override `parse()`
- Follow the structure of the existing parser you studied
- Prefer shared helpers from `parsers/utils/`, `parsers/extractors/`, `parsers/metadata.py`, and `parsers/reconciliation.py`
- Keep `parsers/generic.py` compatibility imports working; it re-exports the common helpers if you need the old import path
- Use `parsers/utils/dates.py` for all date parsing; output must stay `DD/MM/YYYY`

## Step 4: Register

- `parsers/registry.py`: import the class and add one registry entry
- Keep CLI/factory compatibility intact; `factory.py` and the CLI already source supported banks from the registry

## Step 5: Test and iterate

Run: `uv run bank-statement-parser <pdf_path> --bank {bank}`

Check:
- [ ] Transaction count matches the PDF
- [ ] Debits and credits are correctly classified
- [ ] **`reconciliation.balance_delta` is `0.00`** — this is the critical check
- [ ] Opening and closing balance extracted
- [ ] Account number extracted
- [ ] Statement period extracted
- [ ] Narrations are clean (no date fragments or junk from merged cells)
- [ ] `uv run ruff check bank_statement_parser/`
- [ ] `uv run ty check bank_statement_parser/`

If delta is not 0.00 or transactions are missing, go back to step 2 to examine the raw data more closely, fix the parser, and re-test. This is iterative.

## Output Schema

Every parser must return a `ParsedBankStatement` (from `models.py`):

```
ParsedBankStatement:
  file: str                          # PDF filename
  bank: str                          # bank slug
  account_holder_name: str | None
  account_number: str | None
  statement_period_start: str | None # DD/MM/YYYY
  statement_period_end: str | None   # DD/MM/YYYY
  opening_balance: str | None        # amount WITHOUT Cr/Dr suffix
  closing_balance: str | None        # amount WITHOUT Cr/Dr suffix
  debit_count: int
  credit_count: int
  debit_total: str                   # formatted "1,234.56"
  credit_total: str                  # formatted "1,234.56"
  transactions: list[BankTransaction]
  reconciliation: BankReconciliation | None
```

Each `BankTransaction`:
```
BankTransaction:
  date: str                          # DD/MM/YYYY (REQUIRED)
  narration: str                     # transaction description
  amount: str                        # "1,234.56"
  transaction_type: "debit" | "credit"
  balance: str | None                # running balance after this txn
  reference_number: str | None       # UTR/UPI ref
  channel: str | None                # upi, neft, rtgs, imps, atm, card, interest, etc.
  value_date: str | None             # DD/MM/YYYY
  transaction_id: str                # "{bank}_txn_0001" — assigned in parse()
```

`BankReconciliation`:
```
BankReconciliation:
  opening_balance: str
  closing_balance: str
  parsed_debit_total: str
  parsed_credit_total: str
  computed_closing_balance: str      # opening + credits - debits
  balance_delta: str                 # closing - computed (MUST be "0.00")
  transaction_count: int
  debit_count: int
  credit_count: int
```

## Gotchas

- **Some banks have NO tables.** pdfplumber finds zero transaction tables — transactions are word-positioned text. Use `group_words_into_lines()` and x-position thresholds to classify amounts.
- **Page 1 tables are often malformed.** Merged columns on page 1, clean tables on page 2+.
- **Summary rows inside the transaction table.** "Total Debits", "Opening Balance", "B/F" appear as table rows. Always check for these before treating a row as a transaction.
- **Balance suffixes.** Strip "Cr"/"Dr"/"CR"/"DR" before extracting amounts.
- **Currency prefixes on amounts.** Some banks use ₹ or -₹ prefixes (Slice), "r" prefix (IDFC CC). Strip before extracting.
- **Indian number format.** Lakhs grouping: "1,52,581.54". `_extract_amount()` handles this.
- **Date format variety.** DD-MM-YYYY, DD/MM/YYYY, DD Mon YY, DD-MON-YYYY, DD Mon 'YY (apostrophe year). Always normalize output to DD/MM/YYYY.
- **Shared date parser first.** Add any bank-specific format hints via `parsers/utils/dates.py`; do not create another bank-local `_parse_*_date`.
- **Narration newlines.** PDF table cells contain `\n`. Replace with spaces.
- **No auto-detection.** Bank name is always passed explicitly by the caller. Don't implement detection.
- **Multi-page tables.** Reuse column mapping from the first header found.
- **Channel detection gaps.** `detect_channel()` uses standard prefixes (UPI/, IMPS/, NEFT/). Some banks use non-standard prefixes. Add bank-specific detection if needed.
- **x-position classification.** For word-line parsing, use header x-positions to set `ColumnThresholds`. More robust than token counting.
- **Debit/credit from amount sign.** Some banks (Slice) use -₹ for debits and ₹ for credits rather than separate columns.
- **Packed single-row tables.** Some banks (HDFC) render the entire transaction list as ONE table row where each cell contains all values joined by `\n` (e.g., cell[0] = "01 Mar 26\n02 Mar 26\n03 Mar 26\n..."). Split each cell on `\n` and align by index. Narrations span multiple lines and typically end with a marker like "Value Dt DD/MM/YYYY" — use this to split the joined narration back into per-transaction strings.
- **Summary rows that look like data rows.** If multiple tables contain amount rows (e.g., a balance summary table on page 1), make sure your summary-balance regex/anchor is specific enough to avoid matching the wrong one. Anchor on labeled header text like "Opening Balance" rather than just "4 amounts in a row".

## Self-improvement

If you discover new patterns, edge cases, or pitfalls while building a parser, update this skill file with what you learned.
