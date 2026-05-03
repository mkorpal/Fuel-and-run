#!/usr/bin/env python3
"""
garmin_save_token.py
--------------------
Run this ONCE locally to generate a Garmin auth token for a profile
that has MFA enabled. The token is saved locally AND output as a
base64 string you can store as a GitHub secret for automated syncing.

Usage:
  python scripts/garmin_save_token.py marysia
  python scripts/garmin_save_token.py michal

You will be prompted for email, password, and MFA code.
Copy the base64 output and add it as a GitHub secret:
  marysia → GARMIN_MARYSIA_TOKEN
  michal   → GARMIN_TOKEN
"""
import base64
import os
import sys
from pathlib import Path

try:
    from garminconnect import Garmin
except ImportError:
    print("Install garminconnect first: pip install garminconnect")
    sys.exit(1)

profile = sys.argv[1].lower() if len(sys.argv) > 1 else 'michal'
token_file = Path.home() / (
    '.garminconnect_token_marysia.json' if profile == 'marysia' else '.garminconnect_token.json'
)
secret_name = 'GARMIN_MARYSIA_TOKEN' if profile == 'marysia' else 'GARMIN_TOKEN'

print(f"\nGarmin token generator — profile: {profile}")
print("=" * 50)

email    = os.environ.get('GARMIN_EMAIL') or input("Garmin email: ").strip()
password = os.environ.get('GARMIN_PASSWORD') or input("Garmin password: ").strip()

def get_mfa():
    return input("Enter MFA / verification code from your email or authenticator: ").strip()

print("\nLogging in to Garmin Connect...")
# marysia has MFA enabled; michal does not
api = Garmin(email, password, prompt_mfa=get_mfa if profile == 'marysia' else None)

try:
    api.login()
except Exception as e:
    print(f"\n❌ Login failed: {e}")
    sys.exit(1)

# Save token as JSON file locally
api.client.dump(str(token_file))
print(f"\n✅ Token saved locally to {token_file}")

# Encode as base64 for GitHub secret
token_b64 = base64.b64encode(token_file.read_bytes()).decode()

print(f"\nNow add this as GitHub secret  →  {secret_name}")
print("Go to: github.com/mkorpal/Fuel-and-run → Settings → Secrets and variables → Actions → New repository secret")
print("\n" + "─" * 60)
print(token_b64)
print("─" * 60)
print("\nOnce added, trigger the workflow again — no more MFA prompts.")
