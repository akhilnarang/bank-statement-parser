# AGENTS

Guidance for contributors and coding agents working on this repository.

## Project Purpose

`bank-statement-parser` parses bank account (savings/current) statement PDFs into normalized, comparable output. Companion to `cc-parser` (which handles credit card statements).

Primary goals:

- robust extraction from noisy PDFs (table-based and word-positioned layouts),
- stable schema across bank templates,
- balance verification as the primary correctness signal,
- privacy-safe development (no account-specific hardcoding).

## High-Level Architecture

- `bank_statement_parser/cli.py` — command entrypoint, password prompt, parser selection, Rich table presentation, optional JSON/CSV export.
- `bank_statement_parser/extractor.py` — bank-agnostic raw PDF extraction (encryption detection/decryption, page text/words/tables/blocks, metadata).
- `bank_statement_parser/models.py` — Pydantic models: `ParsedBankStatement`, `BankTransaction`, `BankReconciliation`.
- `bank_statement_parser/parsers/base.py` — `BankStatementParser` abstract base.
- `bank_statement_parser/parsers/registry.py` — canonical parser registry keyed by bank slug.
- `bank_statement_parser/parsers/factory.py` — compatibility wrapper around the registry (no auto-detection — caller passes the bank).
- `bank_statement_parser/parsers/generic.py` — thin orchestrator plus compatibility re-exports for moved helpers.
- `bank_statement_parser/parsers/metadata.py` — shared regex metadata extraction with per-bank overrides.
- `bank_statement_parser/parsers/reconciliation.py` — shared reconciliation and transaction ID helpers.
- `bank_statement_parser/parsers/extractors/` — shared table / word-line / x-position helpers.
- `bank_statement_parser/parsers/utils/` — shared dates, amounts, channel/reference helpers.
- `bank_statement_parser/parsers/{bank}.py` — bank-specific parsers for HDFC, ICICI, IDFC, IndusInd, Slice, UBOI.

## Parser Contract

All parsers extend `GenericBankStatementParser` and override `parse(raw_data) -> ParsedBankStatement`.
Safe shared post-processing lives on `BankStatementParser._post_process()`; it currently assigns deterministic `transaction_id` values without changing parser-specific extraction logic.

Required fields on `ParsedBankStatement`:
- `file`, `bank`, `account_holder_name`, `account_number`
- `statement_period_start`, `statement_period_end` (DD/MM/YYYY)
- `opening_balance`, `closing_balance` (without Cr/Dr suffix)
- `debit_count`, `credit_count`, `debit_total`, `credit_total`
- `transactions` (list of `BankTransaction`)
- `reconciliation` (`BankReconciliation`)

Each `BankTransaction`:
- `date` (DD/MM/YYYY, required), `narration`, `amount` (comma-separated string), `transaction_type` (debit/credit)
- `balance` (running balance), `reference_number`, `channel`, `value_date`, `transaction_id`

## No Auto-Detection

Bank name is always passed explicitly by the caller. Statement narrations routinely mention other banks (UPI via HDFC, NEFT from ICICI, etc.) which makes heuristic detection unreliable. Do not add detection logic.

## Output Modes

- default run: prints tables only, no JSON file.
- `-v`: writes parsed compact JSON.
- `-vv`: writes `{ parsed, debug }`.
- `-vvv`: writes `{ parsed, debug, raw }`.

## Classification and Reconciliation Principles

- Use structural evidence first (column headers, x-positions for word-based layouts, Cr/Dr markers).
- `reconciliation.balance_delta` MUST be `"0.00"` for a correct parse — it's the primary correctness check.
- Treat reconciliation as observability; do not silently coerce totals.
- When parsing word-positioned text (no PDF tables), use x-position thresholds derived from header positions rather than token counting.

## Privacy and Safety Rules

- Never commit real statement PDFs or raw personal data.
- Never add sample values copied from real statements to comments or tests.
- Keep logs and docs generic and template-focused.
- Do not hardcode customer-specific names, account numbers, addresses, or amounts.

## Change Workflow

When modifying parser logic:

1. Keep bank-specific behavior in bank parser modules.
2. Preserve output schema compatibility.
3. Validate with `-vvv` output and verify `balance_delta == "0.00"`.
4. Update `README.md` when behavior changes.
5. Run `uv run ruff check bank_statement_parser/`.
6. Run `uv run ty check bank_statement_parser/`.

## Adding New Bank Parsers

Follow the skill at `.agents/skills/add-bank-parser/SKILL.md`. The skill walks through:
1. Studying the codebase
2. Extracting raw PDF data (mandatory — do not guess from visual layout)
3. Writing the parser (extending `GenericBankStatementParser`)
4. Registering in `parsers/registry.py` (factory/CLI compatibility stays in sync from there)
5. Testing for `balance_delta == "0.00"`

## Coding Conventions

- Use typed Python signatures.
- Add docstrings with `Args` and `Returns` for non-trivial functions.
- Prefer pure helper functions for parsing steps.
- Keep CLI presentation logic out of parser core logic.
- Use `parsers/utils/dates.py` for shared date parsing; downstream date strings must remain `DD/MM/YYYY`.
- Use `parsers/extractors/positioning.py::ColumnThresholds` for word-positioned layouts instead of scattering raw x-threshold numbers.
- Python 3.14 / PEP 758 syntax is allowed here; do not "fix" `except E1, E2:` forms just for style.

## Non-Goals

- OCR model training.
- Guaranteed perfect reconciliation for every issuer template.
- Storing statement data in this repository.
- Auto-detection of bank from PDF content.

## Consumer Contract

`bank-email-fetcher` uses this library programmatically. These are downstream-breaking if changed:

- **Date format is DD/MM/YYYY**: consumers parse with `strptime(date, "%d/%m/%Y")`.
- **Amount strings are comma-separated**: expects `"25,000.00"`, strips commas to convert to Decimal.
- **Bank name is the explicit input**: `get_parser(bank)` — the output model includes the bank slug as-received.
- **Compatibility shims matter**: `extract_raw_pdf`, `parsers.factory.get_parser`, CLI UX, and commonly imported helpers from `parsers.generic` must keep working while internals move.

## Known Limitations

- **No OCR**: only PDFs with a text layer. Scanned image-only PDFs produce empty/garbled output.
- **Page 1 tables often malformed**: some banks (IDFC) merge columns on page 1 but produce clean tables on page 2+. Parsers handle this with fallback strategies.
- **No tables at all for some banks**: ICICI renders transactions as positioned text; those parsers use `group_words_into_lines()` and x-position thresholds.
- **Channel detection is pattern-based**: standard prefixes (UPI/, IMPS/, NEFT/) are recognized; bank-specific non-standard prefixes may need custom handling in the bank's parser.
