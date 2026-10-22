"""Maxcam login via Supabase email OTP.

Usage:
    python maxcam_auth.py request        # sends the code to MAXCAM_EMAIL
    python maxcam_auth.py verify 123456  # exchanges the code for a session
"""
import json
import os
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(HERE, "session.json")


def load_env():
    env = {}
    with open(os.path.join(HERE, ".env"), encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                env[k] = v
    return env


ENV = load_env()
BASE = ENV["SUPABASE_URL"]
HEADERS = {"apikey": ENV["SUPABASE_KEY"], "Content-Type": "application/json"}


def request_code():
    r = requests.post(f"{BASE}/auth/v1/otp", headers=HEADERS,
                      json={"email": ENV["MAXCAM_EMAIL"], "create_user": False}, timeout=30)
    print(r.status_code, r.text[:300])


def _save(data):
    data["expires_at"] = int(time.time()) + int(data.get("expires_in", 3600))
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def verify_code(code):
    r = requests.post(f"{BASE}/auth/v1/verify", headers=HEADERS,
                      json={"type": "email", "email": ENV["MAXCAM_EMAIL"], "token": code.strip()},
                      timeout=30)
    if r.status_code != 200:
        sys.exit(f"verify failed: {r.status_code} {r.text[:300]}")
    _save(r.json())
    print("session saved")


def get_access_token():
    with open(SESSION_FILE, encoding="utf-8") as f:
        s = json.load(f)
    if s["expires_at"] - time.time() > 60:
        return s["access_token"]
    r = requests.post(f"{BASE}/auth/v1/token?grant_type=refresh_token", headers=HEADERS,
                      json={"refresh_token": s["refresh_token"]}, timeout=30)
    r.raise_for_status()
    _save(r.json())
    return r.json()["access_token"]


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "request":
        request_code()
    elif len(sys.argv) == 3 and sys.argv[1] == "verify":
        verify_code(sys.argv[2])
    else:
        sys.exit(__doc__)
