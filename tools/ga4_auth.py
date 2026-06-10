#!/usr/bin/env python3
"""
One-time OAuth setup for both GSC and GA4 — run this LOCALLY (needs a browser).

  python3 tools/ga4_auth.py

Opens a browser tab for Google sign-in as mjopolko@gmail.com (the GSC/GA4 owner).
Saves a single token covering both APIs to /tmp/nowservingto-google-token.json,
then prints the deploy command for the VPS.

Requires: secret.json (OAuth desktop client) at one of the candidate paths below.
"""
import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    'https://www.googleapis.com/auth/webmasters.readonly',   # GSC
    'https://www.googleapis.com/auth/analytics.readonly',    # GA4
]

CANDIDATES = [
    Path('/mnt/c/Users/josh/Desktop/secret.json'),
    Path('/var/secrets/nowservingto-oauth-client.json'),
    Path(__file__).resolve().parent.parent / 'secret.json',
]

TOKEN_OUT = Path('/tmp/nowservingto-google-token.json')
VPS_PATH  = '/var/secrets/nowservingto-google-token.json'


def find_client_secret():
    for p in CANDIDATES:
        if p.exists():
            return p
    sys.exit('Cannot find secret.json. Expected one of:\n' +
             '\n'.join(f'  {p}' for p in CANDIDATES))


if __name__ == '__main__':
    client_file = find_client_secret()
    print(f'Using OAuth client: {client_file}')
    print('Opening browser for Google sign-in...\n')

    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    token_data = {
        'token':         creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri':     creds.token_uri,
        'client_id':     creds.client_id,
        'client_secret': creds.client_secret,
        'scopes':        list(creds.scopes),
    }
    TOKEN_OUT.write_text(json.dumps(token_data, indent=2))
    TOKEN_OUT.chmod(0o600)

    print(f'Token saved → {TOKEN_OUT}')
    print('\nDeploy to VPS (run these two lines):')
    print(f'  scp {TOKEN_OUT} nowservingto:/tmp/nowservingto-google-token.json')
    print(f'  ssh nowservingto "sudo mv /tmp/nowservingto-google-token.json {VPS_PATH} && sudo chmod 640 {VPS_PATH} && sudo chown john:www-data {VPS_PATH}"')
