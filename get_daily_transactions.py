import os
import re
import sys
import json
import jwt
import time
import requests
import gspread
from datetime import date, timedelta
from config import load_config

_CFG = load_config()
APP_ID = _CFG["app_id"]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PEM_PATH = os.path.join(BASE_DIR, "private.pem")
SESSION_PATH = os.path.join(BASE_DIR, "session.json")
CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")
RAW_DUMP_PATH = os.path.join(BASE_DIR, "raw_transactions.json")
DISTRIBUTION_PATH = os.path.join(BASE_DIR, "distribution.json")

# identification_hash is stable across sessions (unlike the account uid, which
# changes every time the ActivoBank consent is renewed). Used to find the right
# account in session.json after each renewal instead of hardcoding a uid.
ACCOUNT_IDENTIFICATION_HASH = _CFG["account_identification_hash"]
SPREADSHEET_ID = _CFG["spreadsheet_id"]
EXPENSES_SHEET = "Gastos del Mes"
INCOMES_SHEET = "Ingresos del Mes"

# Gastos del Mes columns:   Gasto(A) | Reserva(B) | Monto(C) | Fecha(D) | Vía(E) | Notas(F)
# Ingresos del Mes columns: Ingreso(A) | Monto(B) | Fecha(C) | Notas(D)

CARD_MAP = _CFG.get("card_map", {})
CREDIT_CARD_SUFFIX = _CFG.get("credit_card_suffix")

SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ── Enable Banking ────────────────────────────────────────────────────────────

def generate_jwt():
    with open(PEM_PATH, "rb") as f:
        private_key = f.read()
    iat = int(time.time())
    payload = {
        "iss": "enablebanking.com",
        "aud": "api.enablebanking.com",
        "iat": iat,
        "exp": iat + 3600,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": APP_ID})


def _last_working_day(year, month):
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    while last.weekday() >= 5:
        last -= timedelta(days=1)
    return last


def get_distribution_start():
    if os.path.exists(DISTRIBUTION_PATH):
        with open(DISTRIBUTION_PATH) as f:
            return date.fromisoformat(json.load(f)["start"])
    today = date.today()
    pm = today.month - 1 if today.month > 1 else 12
    py = today.year if today.month > 1 else today.year - 1
    return _last_working_day(py, pm) + timedelta(days=1)


def get_fetch_window():
    # Scan the full current distribution so no transactions are missed,
    # regardless of how long since the script last ran.
    return get_distribution_start(), date.today()  # date_to is exclusive in the API


def resolve_account_id(session):
    """Find the account uid matching ACCOUNT_IDENTIFICATION_HASH in the current session."""
    for acc in session["accounts"]:
        if acc["identification_hash"] == ACCOUNT_IDENTIFICATION_HASH:
            return acc["uid"]
    raise RuntimeError(
        "Tracked account not found in session.json — the identification_hash "
        "didn't match any account in this session. Run renew_API_session.py "
        "and check that the account is still linked."
    )


def fetch_transactions(session_id, account_id, date_from, date_to):
    """Call the API and return the transaction list. Also saves raw response to file."""
    token = generate_jwt()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://api.enablebanking.com/accounts/{account_id}/transactions"
    params = {
        "date_from": str(date_from),
        "date_to": str(date_to),
        "session_id": session_id,
    }
    txs = []
    while True:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code != 200:
            print(f"API error {r.status_code}: {r.text[:300]}")
            return None
        data = r.json()
        txs.extend(data.get("transactions", []))
        ck = data.get("continuation_key")
        if not ck:
            break
        params["continuation_key"] = ck
    with open(RAW_DUMP_PATH, "w", encoding="utf-8") as f:
        json.dump(txs, f, indent=2, ensure_ascii=False)
    return txs


def fetch_transactions_mock():
    """Return transactions from the saved raw dump instead of calling the API."""
    with open(RAW_DUMP_PATH, encoding="utf-8") as f:
        return json.load(f)


# ── Transaction parsing ───────────────────────────────────────────────────────

def _tx_date(tx):
    # transaction_date is always null for ActivoBank; fall back to value_date then booking_date.
    for field in ("value_date", "booking_date"):
        v = tx.get(field)
        if v:
            return v
    return str(date.today() - timedelta(days=1))


def _classify(tx):
    """Return 'e' (expense), 'c' (credit card expense), or 'i' (income)."""
    desc = (tx.get("remittance_information") or [""])[0]
    if tx.get("credit_debit_indicator") == "CRDT":
        return "i"
    m = re.search(r"COMPRA (\d{4})", desc)
    if m and m.group(1) == CREDIT_CARD_SUFFIX:
        return "c"
    return "e"


def _clean_desc(tx):
    """Return a human-readable description from remittance_information."""
    raw = (tx.get("remittance_information") or [""])[0].strip()

    # COMPRA XXXX <merchant> [<location>] [CONTACTLESS]
    m = re.match(r"^COMPRA \d{4}\s+", raw)
    if m:
        desc = raw[m.end():]
        desc = re.sub(r"\s+CONTACTLESS\s*$", "", desc, flags=re.IGNORECASE)
        return desc.strip()

    # CRED. XXXX <merchant> <location-ref>  (refunds — go to incomes)
    m = re.match(r"^CRED\.\s*\d{4}\s+", raw)
    if m:
        desc = raw[m.end():]
        desc = re.sub(r"\s+\d{3,4}-\d{3}\s+\w+$", "", desc)
        return desc.strip()

    # DD <creditor> <long-reference>
    m = re.match(r"^DD\s+", raw)
    if m:
        desc = raw[m.end():]
        desc = re.sub(r"\s+\d{5,}.*$", "", desc)
        return desc.strip().rstrip("-").strip()

    # TRF MB WAY P <beneficiary>
    m = re.match(r"^TRF\s+MB\s+WAY\s+P\s+", raw, re.IGNORECASE)
    if m:
        return raw[m.end():].strip()

    # TRF P <beneficiary>  (outgoing transfer)
    m = re.match(r"^TRF\s+P\s+", raw, re.IGNORECASE)
    if m:
        return raw[m.end():].strip()

    # TRF DE <sender>  (incoming transfer — goes to incomes)
    m = re.match(r"^TRF\s+DE\s+", raw, re.IGNORECASE)
    if m:
        return raw[m.end():].strip()

    return raw


def _via_label(tx):
    """Return the Vía column value: card owner, transfer type, or direct debit."""
    desc = (tx.get("remittance_information") or [""])[0]
    m = re.match(r"^COMPRA (\d{4})\b", desc)
    if m:
        return CARD_MAP.get(m.group(1), m.group(1))
    if re.match(r"^TRF\s+MB\s+WAY\b", desc, re.IGNORECASE):
        return "MBWay"
    if re.match(r"^TRF\b", desc, re.IGNORECASE):
        return "Transferencia"
    if re.match(r"^DD\b", desc):
        return "Débito directo"
    return ""


# ── Deduplication IDs ─────────────────────────────────────────────────────────

def _make_id(prefix, date_compact, amount, description):
    return f"{prefix}-{date_compact}-{amount:.2f}-{description}"


def _to_compact(val):
    """Convert a sheet date value (serial float or ISO string) to 'YYYYMMDD'."""
    if isinstance(val, (int, float)):
        d = date(1899, 12, 30) + timedelta(days=int(val))
        return d.strftime("%Y%m%d")
    return str(val).replace("-", "")


def _read_existing_ids(ws, col_desc, col_amount, col_date, col_via=None):
    """Reconstruct transaction IDs from existing sheet rows."""
    rows = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    ids = set()
    for row in rows[1:]:  # skip header
        try:
            desc = row[col_desc]
            amount = float(row[col_amount])
            date_compact = _to_compact(row[col_date])
            if not desc or not date_compact:
                continue
            if col_via is not None:
                via = row[col_via] if len(row) > col_via else ""
                prefix = "c" if via == "Crédito" else "e"
            else:
                prefix = "i"
            ids.add(_make_id(prefix, date_compact, amount, desc))
        except (IndexError, ValueError, TypeError):
            continue
    return ids


def _next_empty_row(ws):
    """Return the 1-indexed row number of the first empty row after col A data."""
    col_a = ws.col_values(1)  # stops at last non-empty cell in col A
    return len(col_a) + 1


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    use_mock = "--mock" in sys.argv
    date_from, date_to = get_fetch_window()

    if date_from >= date_to:
        print("First day of distribution — nothing to fetch yet.")
        return

    # Step 1: fetch transactions
    if use_mock:
        print(f"[MOCK] Reading from {RAW_DUMP_PATH}")
        txs = fetch_transactions_mock()
    else:
        with open(SESSION_PATH) as f:
            session = json.load(f)
        account_id = resolve_account_id(session)
        print(f"Fetching {date_from} → {date_to - timedelta(days=1)}...")
        txs = fetch_transactions(session["session_id"], account_id, date_from, date_to)

    if txs is None:
        print("API request failed. Aborting.")
        return
    if not txs:
        print("No transactions in window.")
        return

    print(f"{'[MOCK] ' if use_mock else ''}Fetched {len(txs)} transaction(s).")

    # Step 2: split into buckets
    expenses, incomes = [], []
    for tx in txs:
        kind = _classify(tx)
        rec = {
            "prefix": kind,
            "date": _tx_date(tx),
            "desc": _clean_desc(tx),
            "amount": float(tx.get("transaction_amount", {}).get("amount", 0)),
        }
        if kind in ("e", "c"):
            rec["via"] = _via_label(tx)
            expenses.append(rec)
        else:
            incomes.append(rec)

    print(f"  {len(expenses)} expense(s), {len(incomes)} income(s).")

    gc = gspread.service_account(filename=CREDENTIALS_PATH, scopes=SHEETS_SCOPES)
    ss = gc.open_by_key(SPREADSHEET_ID)
    expenses_ws = ss.worksheet(EXPENSES_SHEET)
    incomes_ws = ss.worksheet(INCOMES_SHEET)

    # Gastos del Mes:   Gasto(A) | Reserva(B) | Monto(C) | Fecha(D) | Vía(E) | Notas(F)
    # Ingresos del Mes: Ingreso(A) | Monto(B) | Fecha(C) | Notas(D)

    expenses.sort(key=lambda t: t["date"])
    incomes.sort(key=lambda t: t["date"])

    # Step 3: log missing incomes
    existing_income_ids = _read_existing_ids(incomes_ws, col_desc=0, col_amount=1, col_date=2)
    income_rows = []
    for tx in incomes:
        tx_id = _make_id("i", tx["date"].replace("-", ""), tx["amount"], tx["desc"])
        if tx_id not in existing_income_ids:
            income_rows.append([tx["desc"], tx["amount"], tx["date"], ""])

    if income_rows:
        next_row = _next_empty_row(incomes_ws)
        incomes_ws.update(
            values=income_rows,
            range_name=f"A{next_row}:D{next_row + len(income_rows) - 1}",
            value_input_option="USER_ENTERED",
        )
    new_i = len(income_rows)

    # Step 4: log missing expenses
    existing_expense_ids = _read_existing_ids(
        expenses_ws, col_desc=0, col_amount=2, col_date=3, col_via=4
    )
    expense_rows = []
    for tx in expenses:
        tx_id = _make_id(tx["prefix"], tx["date"].replace("-", ""), tx["amount"], tx["desc"])
        if tx_id not in existing_expense_ids:
            expense_rows.append([tx["desc"], "", tx["amount"], tx["date"], tx["via"], ""])

    if expense_rows:
        next_row = _next_empty_row(expenses_ws)
        expenses_ws.update(
            values=expense_rows,
            range_name=f"A{next_row}:F{next_row + len(expense_rows) - 1}",
            value_input_option="USER_ENTERED",
        )
    new_e = len(expense_rows)

    print(f"Added {new_e} expense(s) and {new_i} income(s) to Finanzas.")
    if new_e == 0 and new_i == 0:
        print("All transactions already logged.")


if __name__ == "__main__":
    main()
