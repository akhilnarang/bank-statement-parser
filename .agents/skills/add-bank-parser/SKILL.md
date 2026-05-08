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
- `bank_statement_parser/parsers/base.py` — `BankStatementParser` ABC plus the shared `_post_process` / `_build_statement` helpers every parser uses
- `bank_statement_parser/parsers/generic.py` — `GenericBankStatementParser` (the class your parser will extend) and the default extract-tables-then-fall-back-to-wordlines flow
- `bank_statement_parser/parsers/metadata.py` — `MetadataExtractor`; most bank parsers subclass it and override regex class attributes (HDFC, Slice opt out and do manual extraction)
- `bank_statement_parser/parsers/registry.py` — canonical parser registration
- `bank_statement_parser/parsers/utils/` and `bank_statement_parser/parsers/extractors/` — reusable helpers you should prefer over reinventing (dates, amounts, channel detection, counterparty extraction, table parsing, word-line grouping, column thresholds)

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
- **Clean tables** (proper headers, separate columns) → study `uboi.py` or `kotak.py` (kotak shows clean tables plus a separate "Account Summary" table for opening/closing balances and a Chq/Ref column used as a reference fallback)
- **Tables with brought-forward / carried-forward rows and continuation tables across pages** → study `indusind.py`
- **Malformed tables** (merged columns on page 1, clean on page 2+) → study `idfc.py`
- **No tables / word-positioned text** → study `icici.py` or `slice.py`
- **Packed single-row tables** (all transactions in ONE row with `\n`-delimited cells) → study `hdfc.py`

## Step 3: Write the parser

Create `bank_statement_parser/parsers/{bank}.py`. Base your implementation on the **actual pdfplumber output from step 2**.

- Extend `GenericBankStatementParser`, override `parse()`, and set `bank = "{slug}"` and `metadata_extractor = ...` as class attributes
- Prefer subclassing `MetadataExtractor` with bank-specific regexes (`account_number_pattern`, `period_pattern`, `name_pattern`, `opening_balance_pattern`, `closing_balance_pattern`) — see `icici.py` `IciciMetadataExtractor` for an example that also overrides `extract_period()` for non-numeric date formats. If the layout is too irregular for the regex hooks (HDFC, Slice), do manual metadata extraction in `parse()` instead — both patterns are accepted
- Inside `parse()`, call `self._post_process(transactions, raw_data)` (assigns `transaction_id` zero-padded and zero-based: `{bank}_txn_0000`, `_0001`, …) and return via `self._build_statement(...)` so totals/counts formatting stays consistent
- Follow the structure of the existing parser you studied
- Prefer shared helpers from `parsers/utils/`, `parsers/extractors/`, `parsers/metadata.py`, and `parsers/reconciliation.py`
- Use `parsers/utils/dates.py` for all date parsing; output must stay `DD/MM/YYYY`. Pass bank-specific `format_hints=[...]` to `parse_date_text()` rather than editing the shared default list, unless the format is genuinely industry-wide
- Populate `counterparty` via `extract_counterparty(narration, channel)` from `parsers/utils/counterparty.py` when the bank's structured narration layout matches one the helper already understands (UPI, IMPS, NEFT/RTGS, BIL/INFT|ONL — modelled on ICICI savings). It returns `None` when the layout doesn't match, which is the correct value to leave on the field. If your bank uses a different layout, leave `counterparty` unset rather than guessing

## Step 4: Register

- `parsers/registry.py`: import the class and add one entry to `PARSER_REGISTRY` (keys are the slugs the CLI accepts via `--bank`)
- `cli.py`: add the slug to the `BankOption` `StrEnum`. The CLI module has a runtime sync check (`if tuple(option.value for option in BankOption) != _SUPPORTED_BANK_SLUGS: raise RuntimeError(...)`) that fires at import time, so registering only in `PARSER_REGISTRY` will break every CLI invocation with `BankOption enum is out of sync with parser registry`
- `factory.py` already routes through the registry — no change needed there

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
- [ ] `channel` and `reference_number` populated for UPI/IMPS/NEFT/RTGS/netbanking rows
- [ ] `counterparty` populated where structured narrations exist (UPI/IMPS/NEFT/RTGS/netbanking) — `None` for everything else is correct
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
  channel: str | None                # upi, neft, rtgs, imps, atm, card, interest, netbanking, etc.
  counterparty: str | None           # cleaned merchant/payee from structured narrations
  value_date: str | None             # DD/MM/YYYY
  transaction_id: str                # "{bank}_txn_0000", "{bank}_txn_0001", … — zero-padded, zero-based, assigned by _post_process()
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
- **Currency prefixes on amounts.** Some banks use ₹ or -₹ prefixes (Slice), or stray "`" / "₹" characters get prepended by extraction. `extract_amount()` strips backtick and ₹; for anything else, clean the token before calling it.
- **Indian number format.** Lakhs grouping: "1,52,581.54". `extract_amount()` (from `parsers/utils/amounts.py`) handles this.
- **Date format variety.** DD-MM-YYYY, DD/MM/YYYY, DD Mon YY, DD-MON-YYYY, DD Mon 'YY (apostrophe year). Always normalize output to DD/MM/YYYY.
- **Shared date parser first.** Pass bank-specific formats via `format_hints=[...]` to `parse_date_text()` / `parse_date()` at the call site (this is what every existing parser does). Only edit `_DEFAULT_FORMAT_HINTS` in `parsers/utils/dates.py` if the format is genuinely industry-wide. Do not create another bank-local `_parse_*_date`.
- **Narration newlines.** PDF table cells contain `\n`. Replace with spaces.
- **No auto-detection.** Bank name is always passed explicitly by the caller. Don't implement detection.
- **Multi-page tables.** Reuse column mapping from the first header found.
- **Channel detection gaps.** `detect_channel()` uses standard prefixes (UPI/, IMPS/, NEFT/, BIL/INFT, NACH, etc.). Some banks use non-standard prefixes. Extend `_CHANNEL_PATTERNS` in `parsers/utils/channels.py` only when a pattern is genuinely cross-bank; otherwise do bank-specific tagging in your parser.
- **Reference extraction is channel-aware on purpose.** `extract_reference_number(narration, channel)` returns `None` when `channel` is `None` or unknown — this is deliberate, to avoid pulling random digit runs out of cheque numbers, dates, or account fragments. Always run `detect_channel()` first and pass the result; don't bypass it by parsing digits yourself.
- **Counterparty extraction is channel-driven.** `extract_counterparty()` only handles UPI, IMPS, NEFT/RTGS, and BIL/INFT|ONL netbanking layouts (modelled on ICICI savings). For other channels or unknown layouts it returns `None`, which is the correct behaviour — leave the field unset rather than guessing.
- **x-position classification.** For word-line parsing, use header x-positions to set `ColumnThresholds`. More robust than token counting.
- **Debit/credit from amount sign.** Some banks (Slice) use -₹ for debits and ₹ for credits rather than separate columns.
- **Packed single-row tables.** Some banks (HDFC) render the entire transaction list as ONE table row where each cell contains all values joined by `\n` (e.g., cell[0] = "01 Mar 26\n02 Mar 26\n03 Mar 26\n..."). Split each cell on `\n` and align by index. Narrations span multiple lines and typically end with a marker like "Value Dt DD/MM/YYYY" — use this to split the joined narration back into per-transaction strings.
- **Summary rows that look like data rows.** If multiple tables contain amount rows (e.g., a balance summary table on page 1), make sure your summary-balance regex/anchor is specific enough to avoid matching the wrong one. Anchor on labeled header text like "Opening Balance" rather than just "4 amounts in a row".
- **Word-line parsers must stop narration accumulation at section boundaries.** When reconstructing narrations from word-positioned text (ICICI-style), an unanchored "keep appending lines until next date" loop will absorb post-transaction sections like "Total:", "Account Related Other Information", nominee tables, and page footers into the last transaction's narration. Bail out of the inner loop on these markers — see the `TOTAL:` / `DATE` / `PAGE` checks in `icici.py`.

## Self-improvement

If you discover new patterns, edge cases, or pitfalls while building a parser, update this skill file with what you learned.
