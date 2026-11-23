"""Loads personal identifiers from the gitignored config.json.

Nothing account-specific lives in the source tree: copy config.example.json to
config.json and fill in your own values.
"""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

_REQUIRED = ("app_id", "spreadsheet_id")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit("config.json not found. Copy config.example.json to config.json and fill it in.")
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    missing = [k for k in _REQUIRED if not cfg.get(k)]
    if missing:
        sys.exit(f"config.json is missing required keys: {', '.join(missing)}")
    return cfg
