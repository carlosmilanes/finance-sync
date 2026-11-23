# Personal finance sync

Python scripts that pull my bank transactions from ActivoBank (Portugal) through the
[Enable Banking](https://enablebanking.com) PSD2 API and log them into a Google Sheets
budget, one row per transaction.

## What it does

- **`get_daily_transactions.py`** scans the current budget period, parses and cleans the raw
  bank descriptions (card owner, transfers, direct debits, merchant names) and appends only
  the transactions not already in the sheet.
- **`renew_API_session.py`** renews the 90-day PSD2 consent (browser flow).
- **`archive_distribution.py`** archives the sheet at the start of each period (Drive copy via
  OAuth), clears the monthly tabs and re-syncs.

## Design notes

- **Idempotent.** Re-running never duplicates rows: IDs are derived from
  `date + amount + description`, because the API's `transaction_id` is documented as unstable.
- **Rate-limit aware.** The bank allows about 4 calls per account per day, so every real
  response is cached and `--mock` replays it to test logic changes without hitting the API.
- **Pagination** via `continuation_key` is handled in a loop.
- **Stable account matching.** Account `uid` rotates on every consent renewal, so the tracked
  account is resolved by `identification_hash`.
- **No personal data in the repo.** Identifiers live in a gitignored `config.json`
  (see `config.example.json`); keys and tokens are gitignored too.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json   # fill in your own values
```

Full setup (Enable Banking app, Google service account and OAuth client) is in
[`.claude/project.md`](.claude/project.md).

```bash
venv/bin/python renew_API_session.py            # first time, then every 90 days
venv/bin/python get_daily_transactions.py       # sync
venv/bin/python get_daily_transactions.py --mock  # replay cached response
venv/bin/python archive_distribution.py DAY     # start a new period
```

The sheet layout and descriptions are in Spanish; adapt `EXPENSES_SHEET` / `INCOMES_SHEET`
and the description parsing for your own bank.
