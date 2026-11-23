import os
import jwt
import time
import uuid
import json
import requests
import webbrowser
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs
from config import load_config

APP_ID = load_config()["app_id"]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PEM_PATH = os.path.join(BASE_DIR, "private.pem")
SESSION_PATH = os.path.join(BASE_DIR, "session.json")

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

def setup():
    token = generate_jwt()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    valid_until = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")

    body = {
        "access": {"valid_until": valid_until},
        "aspsp": {"name": "Activo Bank", "country": "PT"},
        "state": str(uuid.uuid4()),
        "redirect_url": "https://localhost/",
        "psu_type": "personal"
    }

    r = requests.post("https://api.enablebanking.com/auth", headers=headers, json=body)
    print("Status:", r.status_code)
    print("Response:", r.json())
    r.raise_for_status()
    auth_url = r.json()["url"]

    print("\nAbriendo el navegador para autenticarte en ActivoBank...")
    print("Cuando el navegador falle al cargar, copia la URL completa de la barra de direcciones.\n")
    webbrowser.open(auth_url)

    redirect_url = input("Pega aquí la URL completa: ").strip()
    params = parse_qs(urlparse(redirect_url).query)
    code = params["code"][0]

    token = generate_jwt()
    headers["Authorization"] = f"Bearer {token}"
    r = requests.post("https://api.enablebanking.com/sessions", headers=headers, json={"code": code})
    r.raise_for_status()
    data = r.json()

    session_id = data["session_id"]
    accounts = [
        {
            "uid": a["uid"],
            "iban": a.get("account_id", {}).get("iban"),
            "name": a.get("name"),
            "product": a.get("product"),
            "cash_account_type": a.get("cash_account_type"),
            "identification_hash": a.get("identification_hash"),
        }
        for a in data["accounts"]
    ]

    with open(SESSION_PATH, "w") as f:
        json.dump({"session_id": session_id, "accounts": accounts}, f, indent=2)

    print(f"\nSetup completado. Session ID guardado.")
    print("Cuentas encontradas:")
    for a in accounts:
        print(f"  {a['uid']}  {a['iban']}  {a['name']}")

if __name__ == "__main__":
    setup()
