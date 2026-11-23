# Daily Expenses from ActivoBank via Enable Banking API

Setup guide for reading daily transactions from ActivoBank using the Enable Banking open banking aggregator.

---

## Overview

Since ActivoBank doesn't have a public API for direct access, we use **Enable Banking** as a PSD2-compliant intermediary. Enable Banking connects to ActivoBank on your behalf and exposes a clean REST API for reading transactions.

**What this does:** Run manually whenever you want to sync. The script scans the entire current distribution period (from the new distribution start date to today) and writes any transactions not already logged to a Google Sheet. Deduplication ensures re-runs are always safe.

**Consent validity:** 90 days. Every 90 days you need to re-run `renew_API_session.py` to renew the ActivoBank authorization.

---

## Prerequisites

- Python 3.x installed on macOS
- A terminal
- A browser (Chrome recommended for the auth flow)
- An ActivoBank account with your Multichannel Code handy

---

## Step 1: Create an Enable Banking account

1. Go to [enablebanking.com](https://enablebanking.com) and sign up.
2. Log in at [app.enablebanking.com](https://app.enablebanking.com).

---

## Step 2: Register an application

1. Go to **API applications** in the top menu.
2. Click to add a new application with these values:
   - **Environment:** Production
   - **RSA key:** Generate in the browser
   - **Application name:** `daily-expenses`
   - **Allowed redirect URLs:** `https://localhost/`
   - **Application description:** `Personal script to read previous day transactions from ActivoBank.`
   - **Email for data protection:** your personal email
   - **Privacy URL:** `https://localhost`
   - **Terms URL:** `https://localhost`
3. Click **Register**.
4. When prompted, click **Allow** to download the private key `.pem` file. **This is shown only once — keep it safe.**

---

## Step 3: Link your ActivoBank account

1. In the application panel, click **Activate by linking accounts**.
2. Select: **Country:** Portugal, **ASPSP:** Activo Bank, **Usage type:** Personal.
3. Click **Link** — this opens the Enable Banking consent page.
4. Click **Continue authentication** — this redirects to ActivoBank's login.
5. Log in with your User Code and Multichannel Code (3 specific digits).
6. Confirm the consent screen (90-day validity). Click **Continuar**.
7. The browser will fail to load `https://localhost/` — that's expected. The application status will now show **Active**.

> Note: Use Chrome for this step. Safari has issues with the redirect flow.

---

## Step 4: Set up the local environment

```bash
# Clone the repo and cd into it
cd ~/Documents/dev/projects/finances

# Create a Python virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Place the following files in the project directory (all gitignored):

- `private.pem` — RSA private key downloaded from the Enable Banking panel
- `config.json` — personal identifiers (Enable Banking app ID, spreadsheet ID, account hash, card map); copy `config.example.json` and fill it in
- `credentials.json` — Google service account credentials
- `session.json` — created by `renew_API_session.py` after auth
- `oauth_client_secret.json` — OAuth Desktop app client downloaded from Google Cloud Console (see [Distribution archival](#distribution-archival))
- `token.json` — created automatically on the first `archive_distribution.py` run after you complete the Google consent screen

---

## Step 5: Authorize ActivoBank (first time and every 90 days)

```bash
venv/bin/python renew_API_session.py
```

This opens a browser for the ActivoBank consent flow. After completing it, paste the redirect URL back into the terminal. A `session.json` file is created with the session ID and account UIDs.

After running, complete the browser flow:
1. Click **Continue authentication**
2. Log in to ActivoBank (User Code + Multichannel Code)
3. Confirm the 90-day consent. Click **Continuar**
4. When the browser fails on `https://localhost/?code=...`, copy the full URL
5. Paste it in the terminal and press Enter

---

## Daily sync

```bash
venv/bin/python get_daily_transactions.py
```

Scans the full current distribution and writes any missing transactions to the `Finanzas` spreadsheet. Safe to re-run; deduplication prevents duplicates.

---

## Session renewal (every 90 days)

```bash
venv/bin/python renew_API_session.py
```

Renews the ActivoBank consent before it expires. Same browser flow as Step 5: opens a browser for the ActivoBank login, you confirm the 90-day consent, then paste the failed `https://localhost/?code=...` redirect URL back into the terminal. A fresh `session.json` is written with the new session ID and account data.

**Must be run from a terminal, not automated (e.g. via Shortcuts' Run Shell Script).** The script blocks on an `input()` call waiting for you to paste the redirect URL, and calls `webbrowser.open()` to launch an interactive login — neither works headlessly. The daily sync script has no such interaction and is fine to automate; this one is manual-only.

**Account uid rotates on every renewal.** Enable Banking assigns a new account `uid` each time a session is re-authorized — the FAQ confirms this explicitly and recommends matching accounts across sessions via `identification_hash`, which is stable. `renew_API_session.py` now saves each account's `uid`, `iban`, `name`, `product`, `cash_account_type`, and `identification_hash` to `session.json`. `get_daily_transactions.py` no longer hardcodes an account uid — it resolves the current uid at runtime by matching `ACCOUNT_IDENTIFICATION_HASH` (`account_identification_hash` in `config.json`) against `session.json`'s `accounts` list. If that hash isn't found after a renewal (e.g. the account was unlinked), the script raises an error rather than silently using the wrong account.

**Tracked account:** one ActivoBank checking account (`cash_account_type: CACC`), identified by its `identification_hash` in `config.json`. Other accounts on the same consent (a second checking account, a card account) are ignored by the script.

---

## Distribution archival

At the start of each new distribution:

```bash
venv/bin/python archive_distribution.py DAY
```

where `DAY` is the day-of-month the new distribution starts on (e.g. `30`, `1`) — always
resolved to the most recent date with that day number that isn't in the future (e.g.
`29` on Oct 4 → Sep 29; `2` on Oct 4 → Oct 2; months lacking the day, like `31` in
September, are skipped).

This script:
1. Copies the full `Finanzas` spreadsheet into the `Archivo Finanzas` Drive folder, named `{month}-{year}` (e.g. `6-2026` for a June archive)
2. Clears all data rows from `Gastos del Mes` and `Ingresos del Mes` (headers preserved)
3. Deletes non-monthly entries from `Reservas del Mes` (rows without `mensual` in their Tags)
4. Saves the new distribution start date to `distribution.json`
5. Runs `get_daily_transactions.py` to populate the new distribution immediately

**Ownership of archived copies:** Google service accounts have zero Drive storage quota,
so they can create/edit files they're shared on but can't own newly created or copied
files — attempting to `copy` the spreadsheet as the service account fails with a
`storageQuotaExceeded` 403. Because of this, step 1 authenticates as *you* instead, via
a one-time OAuth consent, so the `Archivo Finanzas` folder and every monthly copy inside
it live entirely in your own Drive, owned by you (no sharing step needed).

### One-time OAuth setup (already done — kept here for reference)

1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials) (same
   project as the service account), configure the OAuth consent screen under
   **Google Auth Platform**: app name, your email as support/contact,
   **External** audience, add yourself as a **test user**, and under **Data Access**
   add the scope `https://www.googleapis.com/auth/drive` (not `drive.file` — that
   narrower scope can't see files the app didn't create, like the existing `Finanzas`
   spreadsheet).
2. Under **Clients**, create an OAuth client of type **Desktop app**, download the
   JSON, save it as `oauth_client_secret.json` in the project directory (gitignored).
3. The first real run of `archive_distribution.py` opens a browser for a one-time
   consent — click through the "Google hasn't verified this app" warning (you're the
   developer and the only test user) — and caches the result to `token.json`
   (gitignored). Later runs reuse it silently. Because the app stays in Testing mode,
   Google invalidates the cached refresh token after ~7 days, so in practice every
   monthly run re-prompts the browser consent — `_drive_session()` catches the failed
   refresh and reopens the consent flow automatically instead of crashing.

---

## Mock mode

Every real API run saves the raw response to `raw_transactions.json`. To re-run the full pipeline without consuming an API call:

```bash
venv/bin/python get_daily_transactions.py --mock
```

Useful for testing logic changes without hitting the rate limit.

**Raw API shape (trimmed real example):** kept here for reference since `raw_transactions.json` is gitignored and gets overwritten on every real run. Confirms which fields ActivoBank actually populates.

```json
[
  {
    "entry_reference": "2026070112026-07-01-05.33.36.921993",
    "merchant_category_code": null,
    "transaction_amount": { "currency": "EUR", "amount": "27.97" },
    "creditor": null,
    "creditor_account": null,
    "creditor_agent": null,
    "debtor": null,
    "debtor_account": { "iban": "PT50000000000000000000000", "other": null },
    "debtor_agent": null,
    "bank_transaction_code": null,
    "credit_debit_indicator": "DBIT",
    "status": "BOOK",
    "booking_date": "2026-07-01",
    "value_date": "2026-06-30",
    "transaction_date": null,
    "balance_after_transaction": null,
    "reference_number": null,
    "reference_number_schema": null,
    "remittance_information": ["DD OCIDENTAL 00406559883 MEDIS       DI72489001"],
    "debtor_account_additional_identification": null,
    "creditor_account_additional_identification": null,
    "exchange_rate": null,
    "note": null,
    "transaction_id": null
  }
]
```

---

## File structure

```
finances/
├── CLAUDE.md                  # Instructions for Claude when working on this project
├── project.md                 # This file
├── get_daily_transactions.py  # Run manually: scans full distribution, writes missing rows to Sheets
├── archive_distribution.py    # Run at start of each new distribution to archive and reset
├── renew_API_session.py       # Run once, then every 90 days to renew ActivoBank auth
├── distribution.json          # New distribution start date (gitignored; written by archive script)
├── raw_transactions.json      # Saved on every real API run; used by --mock flag (gitignored)
├── private.pem                # RSA private key (gitignored — never commit)
├── session.json               # Active session + account UIDs (gitignored, valid ~90 days)
├── credentials.json           # Google service account credentials (gitignored — never commit)
├── config.py                  # Loads config.json
├── config.example.json        # Template for config.json (committed)
├── config.json                # Your real identifiers (gitignored — never commit)
├── oauth_client_secret.json   # OAuth Desktop client for archive_distribution.py (gitignored — never commit)
├── token.json                 # Cached OAuth consent for archive_distribution.py (gitignored)
├── sync.log                   # Run-log the Shortcut appends daily-sync output to (gitignored)
├── requirements.txt           # Python dependencies
└── venv/                      # Python virtualenv (gitignored)
```

---

## Key notes

- **Rate limit:** ActivoBank allows approximately 4 API calls per account per day. Don't run the script multiple times in the same day during testing.
- **Session renewal:** Every 90 days, run `renew_API_session.py` again. The browser flow takes about 5 minutes.
- **Account of interest:** the one checking account with actual daily transactions (set via `account_identification_hash` in `config.json`). Its account `uid` changes on every session renewal — see [Session renewal](#session-renewal-every-90-days) for how the script resolves it via `identification_hash` instead of a hardcoded uid.
- **JWT format:** `iss` must always be `"enablebanking.com"` and `aud` must always be `"api.enablebanking.com"`. The app ID goes in the JWT header as `kid`, not in the payload.
- **Transaction deduplication:** IDs are generated on the fly as `{prefix}-{YYYYMMDD}-{amount:.2f}-{description}` and never stored in the sheet. The script generates the same ID from both the API response and the existing sheet rows (reading Fecha as a full date), then only writes rows whose ID isn't already present. Do not use the API's `transaction_id` field — the FAQ explicitly states it may change between requests. Prefixes: `e` = debit expense, `c` = credit card expense, `i` = income.
- **Pagination:** The transactions endpoint returns a `continuation_key` when results span multiple pages. Always loop until no continuation key is present.
- **Spreadsheet ID:** stored as `spreadsheet_id` in `config.json` (stable across renames; scripts always open by ID, never by name)

---

## API Reference

- API reference: https://enablebanking.com/docs/api/reference/
- FAQ (rate limits, field semantics, deduplication): https://enablebanking.com/docs/faq/
- Python samples: https://github.com/enablebanking/enablebanking-api-samples

---

## Card and transaction type identification

ActivoBank embeds the card suffix and transaction type in the `remittance_information` string. The script parses the prefix to populate the **Vía** column:

| Description prefix | Vía value | Dedup prefix |
|--------------------|-----------|--------------|
| `COMPRA <card A suffix> …` | owner name from `card_map` in `config.json` | `e` |
| `COMPRA <card B suffix> …` | owner name from `card_map` in `config.json` | `e` |
| `COMPRA <credit card suffix> …` | `Crédito` (suffix = `credit_card_suffix` in `config.json`) | `c` |
| `TRF P …` | `Transferencia` | `e` |
| `TRF MB WAY P …` | `MBWay` | `e` |
| `DD …` | `Débito directo` | `e` |
| Other (bank fees, credit card payment) | *(empty)* | `e` |
| CRDT indicator | *(income — no Vía)* | `i` |

**Description cleaning:** The script strips the type prefix and noise from `remittance_information` before writing to the sheet — e.g. `COMPRA 1111 CONTINENTE BOM DIA CANE CONTACTLESS` → `CONTINENTE BOM DIA CANE`. Specifically: `COMPRA XXXX ` prefix and trailing `CONTACTLESS` are removed; `DD ` prefix and trailing reference numbers are removed; `TRF P ` / `TRF DE ` prefixes are removed; `CRED. XXXX ` prefix and location codes are removed.

**Available API fields:** ActivoBank returns null for `creditor.name`, `debtor.name`, `bank_transaction_code`, `merchant_category_code`, and `transaction_date`. The `remittance_information` string is the only source of merchant and type information.

Dedup ID prefixes:
- `e` — all debit expenses (card, transfer, direct debit, fees)
- `c` — credit card expenses (COMPRA with the `credit_card_suffix`)
- `i` — income (CRDT indicator: refunds, incoming transfers)

---

## Distribution period

A "distribution" is the period between paydays. The start date is stored in `distribution.json` and set explicitly each time `archive_distribution.py` runs. If `distribution.json` doesn't exist, the script falls back to computing the start as the day after the last working day of the previous month.

The script is triggered manually and scans the **entire current distribution** on every run. The deduplication system ensures no transaction is ever logged twice, so running it after several missed days (e.g., after a trip) catches everything in a single run.

- Day 1 of distribution: window is empty (nothing to fetch — the day hasn't completed yet)
- Any other day: scans from distribution start to today

---

## Google Sheets integration

**Spreadsheet:** `Finanzas` (ID: `spreadsheet_id` in `config.json`)
**Service account:** the `client_email` in `credentials.json` (must have Editor access on the sheet)

**Expenses tab:** `Gastos del Mes`

| Column | Filled by | Source |
|--------|-----------|--------|
| Gasto | script | cleaned `remittance_information[0]` (see description cleaning above) |
| Reserva | user | — |
| Monto | script | `transaction_amount.amount` |
| Fecha | script | full date (YYYY-MM-DD); format column as `DD MMM` to display e.g. `28 Jun` |
| Vía | script | card owner or transaction type (see table above) |
| Notas | user | — |

**Incomes tab:** `Ingresos del Mes`

| Column | Filled by | Source |
|--------|-----------|--------|
| Ingreso | script | `remittance_information[0]` from API |
| Monto | script | `transaction_amount.amount` |
| Fecha | script | full date (YYYY-MM-DD); format column as `DD MMM` |
| Notas | user | — |

**Reserves tab:** `Reservas del Mes`

| Column | Notes |
|--------|-------|
| Nombre | Reserve name |
| Tags | Comma-separated tags. Rows containing `mensual` are recurring and kept across distributions. Rows without `mensual` are one-time and deleted by the archival script. |
| Asignado | Budget amount for this distribution |
| Gastado | Tracks spending against this reserve (formula) |
| Disponible | Asignado − Gastado (formula) |

Both transactional tabs must have a header row. The script skips row 1 when reading existing entries.

**Column format for Fecha:** In Google Sheets, select the Fecha column → Format → Number → Custom date and time → enter `DD MMM`. The underlying cell value is the full date (for script use); the display shows `28 Jun`.

Script fills only the columns it owns. Reserva and Notas are left empty.

---

## Transaction dates

ActivoBank never populates `transaction_date` (confirmed null on all transactions). The script uses `value_date` → `booking_date` as the cascade. `value_date` is usually one day earlier than `booking_date` and closer to the actual execution date.

---

## Distribution archival naming

Archives are named `{month}-{year}` where month and year are taken from the last day of the distribution being archived (i.e., `new_start - 1 day`). Examples:

- New start = `2026-07-01` → archive name = `6-2026`
- New start = `2026-08-01` → archive name = `7-2026`

The numbering resets naturally each calendar year. The `Finanzas` spreadsheet keeps its name permanently.
